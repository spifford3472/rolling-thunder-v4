"""FT8-aware active-panel command wrapper."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from rolling_thunder.context_navigation import ContextId, ContextNavigationController
from rolling_thunder.ft8.panel import FT8PanelMode, FT8PanelSnapshot


class DelegatePanelCommands(Protocol):
    def activate_context(self, context_id: ContextId) -> None: ...
    def primary(self) -> bool: ...
    def secondary(self) -> bool: ...
    def tertiary(self) -> bool: ...
    def tertiary_long(self) -> bool: ...
    def move_previous(self) -> bool: ...
    def move_next(self) -> bool: ...
    def has_station_selection(self) -> bool: ...
    def select_station(self) -> bool: ...
    def activate_selection(self) -> bool: ...
    def back(self) -> bool: ...
    def synchronize_radio_state(self) -> bool: ...


class PendingCallsignCommands(Protocol):
    def preload_callsign(self, callsign: str) -> bool: ...
    def discard(self) -> object: ...


class FT8PanelCommands(Protocol):
    @property
    def selected_callsign(self) -> str | None: ...
    def snapshot(self) -> FT8PanelSnapshot: ...
    def select_previous(self) -> str | None: ...
    def select_next(self) -> str | None: ...
    def clear_selection(self) -> bool: ...
    def activate_selection(self, snapshot: FT8PanelSnapshot | None = None) -> bool: ...
    def answer_incoming_call(self) -> bool: ...
    def dismiss_incoming_call(self) -> bool: ...
    def abort(self) -> None: ...
    def return_to_browser(self) -> object | None: ...


class FT8AwareActivePanelCommands:
    """Intercept controls only while the FT8 dashboard context is active."""

    def __init__(
        self,
        context_navigation: ContextNavigationController,
        delegate: DelegatePanelCommands,
        ft8_panel: FT8PanelCommands,
        *,
        cycle_band: Callable[[], bool] | None = None,
        enter_ft8: Callable[[], bool] | None = None,
        exit_ft8: Callable[[], bool] | None = None,
        clear_start_status: Callable[[], bool] | None = None,
        pending_callsign: PendingCallsignCommands | None = None,
    ) -> None:
        self._context_navigation = context_navigation
        self._delegate = delegate
        self._ft8_panel = ft8_panel
        self._cycle_band = cycle_band
        self._enter_ft8 = enter_ft8
        self._exit_ft8 = exit_ft8
        self._clear_start_status = clear_start_status
        self._pending_callsign = pending_callsign
        self._last_context_id = context_navigation.state.selected

    def activate_context(self, context_id: ContextId) -> None:
        entering_ft8 = (
            self._last_context_id is not ContextId.FT8
            and context_id is ContextId.FT8
        )
        leaving_ft8 = (
            self._last_context_id is ContextId.FT8
            and context_id is not ContextId.FT8
        )
        if leaving_ft8 and self._exit_ft8 is not None:
            self._exit_ft8()
        if entering_ft8 and self._enter_ft8 is not None:
            self._enter_ft8()
        self._last_context_id = context_id
        self._delegate.activate_context(context_id)

    def primary(self) -> bool:
        if not self._ft8_is_active():
            return self._delegate.primary()
        if self._ft8_panel.snapshot().mode is not FT8PanelMode.BROWSE:
            return False
        accepted = self._cycle_band is not None and self._cycle_band()
        if not accepted:
            return False
        self._ft8_panel.clear_selection()
        if self._pending_callsign is not None:
            self._pending_callsign.discard()
        return True

    def secondary(self) -> bool:
        if not self._ft8_is_active():
            return self._delegate.secondary()
        snapshot = self._ft8_panel.snapshot()
        if snapshot.mode is not FT8PanelMode.BROWSE or snapshot.incoming_call is None:
            return False
        return self._ft8_panel.answer_incoming_call()

    def tertiary(self) -> bool:
        if not self._ft8_is_active():
            return self._delegate.tertiary()
        snapshot = self._ft8_panel.snapshot()
        mode = snapshot.mode
        if mode is FT8PanelMode.ACTIVE:
            self._ft8_panel.abort()
            return True
        if mode is FT8PanelMode.TERMINAL:
            self._ft8_panel.return_to_browser()
            return True
        if mode is FT8PanelMode.BROWSE and snapshot.incoming_call is not None:
            return self._ft8_panel.dismiss_incoming_call()
        return False

    def tertiary_long(self) -> bool:
        if not self._ft8_is_active():
            return self._delegate.tertiary_long()
        if self._ft8_panel.snapshot().mode is not FT8PanelMode.ACTIVE:
            return False
        self._ft8_panel.abort()
        return True

    def move_previous(self) -> bool:
        if not self._ft8_is_active():
            return self._delegate.move_previous()
        before = self._ft8_panel.selected_callsign
        selected = self._ft8_panel.select_previous()
        changed = self._ft8_panel.selected_callsign != before
        if changed and self._clear_start_status is not None:
            self._clear_start_status()
        if changed and selected is not None and self._pending_callsign is not None:
            self._pending_callsign.preload_callsign(selected)
        return changed

    def move_next(self) -> bool:
        if not self._ft8_is_active():
            return self._delegate.move_next()
        before = self._ft8_panel.selected_callsign
        selected = self._ft8_panel.select_next()
        changed = self._ft8_panel.selected_callsign != before
        if changed and self._clear_start_status is not None:
            self._clear_start_status()
        if changed and selected is not None and self._pending_callsign is not None:
            self._pending_callsign.preload_callsign(selected)
        return changed

    def has_station_selection(self) -> bool:
        if self._ft8_is_active():
            return self._ft8_panel.selected_callsign is not None
        return self._delegate.has_station_selection()

    def select_station(self) -> bool:
        """Highlight one CQ only; never call the FT8 authorization callback."""
        if not self._ft8_is_active():
            return self._delegate.select_station()
        if self._ft8_panel.selected_callsign is not None:
            return True
        return self.move_next()

    def activate_selection(self) -> bool:
        if not self._ft8_is_active():
            return self._delegate.activate_selection()
        snapshot = self._ft8_panel.snapshot()
        if snapshot.mode is FT8PanelMode.TERMINAL:
            self._ft8_panel.return_to_browser()
            return True
        if snapshot.mode is not FT8PanelMode.BROWSE:
            return False
        return self._ft8_panel.activate_selection(snapshot)

    def back(self) -> bool:
        if not self._ft8_is_active():
            return self._delegate.back()
        snapshot = self._ft8_panel.snapshot()
        if snapshot.mode is FT8PanelMode.ACTIVE:
            self._ft8_panel.abort()
            return True
        if snapshot.mode is FT8PanelMode.TERMINAL:
            self._ft8_panel.return_to_browser()
            return True
        return self._ft8_panel.clear_selection()

    def synchronize_radio_state(self) -> bool:
        return self._delegate.synchronize_radio_state()

    def _ft8_is_active(self) -> bool:
        return self._context_navigation.state.selected is ContextId.FT8
