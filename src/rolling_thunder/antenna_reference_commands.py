"""Antenna-panel view-only physical command adapter."""

from __future__ import annotations

from typing import Protocol

from rolling_thunder.context_navigation import ContextId, ContextNavigationController


class DelegatePanelCommands(Protocol):
    """Existing command surface preserved outside the antenna context."""

    def activate_context(self, context_id: ContextId) -> None: ...
    def primary(self) -> bool: ...
    def secondary(self) -> bool: ...
    def tertiary(self) -> bool: ...
    def tertiary_long(self) -> bool: ...
    def move_previous(self) -> bool: ...
    def move_next(self) -> bool: ...
    def activate_selection(self) -> bool: ...
    def back(self) -> bool: ...
    def synchronize_radio_state(self) -> bool: ...


class AntennaPanelCommands(Protocol):
    """Safe immutable-view operations exposed to physical controls."""

    def select_previous(self) -> bool: ...
    def select_next(self) -> bool: ...
    def clear_evaluation(self) -> bool: ...


class AntennaAwareActivePanelCommands:
    """Intercept only viewing/navigation while ANTENNAS is active."""

    def __init__(
        self,
        context_navigation: ContextNavigationController,
        delegate: DelegatePanelCommands,
        antenna_panel: AntennaPanelCommands,
    ) -> None:
        self._context_navigation = context_navigation
        self._delegate = delegate
        self._antenna_panel = antenna_panel

    def activate_context(self, context_id: ContextId) -> None:
        self._delegate.activate_context(context_id)

    def primary(self) -> bool:
        return False if self._active() else self._delegate.primary()

    def secondary(self) -> bool:
        return False if self._active() else self._delegate.secondary()

    def tertiary(self) -> bool:
        return False if self._active() else self._delegate.tertiary()

    def tertiary_long(self) -> bool:
        return False if self._active() else self._delegate.tertiary_long()

    def move_previous(self) -> bool:
        if self._active():
            return self._antenna_panel.select_previous()
        return self._delegate.move_previous()

    def move_next(self) -> bool:
        if self._active():
            return self._antenna_panel.select_next()
        return self._delegate.move_next()

    def activate_selection(self) -> bool:
        # Viewing can never actuate radio or open an editing prompt.
        return False if self._active() else self._delegate.activate_selection()

    def back(self) -> bool:
        if self._active():
            return self._antenna_panel.clear_evaluation()
        return self._delegate.back()

    def synchronize_radio_state(self) -> bool:
        return self._delegate.synchronize_radio_state()

    def _active(self) -> bool:
        return self._context_navigation.state.selected is ContextId.ANTENNAS
