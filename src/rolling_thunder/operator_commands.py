"""Shared application commands for graphical and physical operator controls."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from rolling_thunder.callsign_capture import CallsignCaptureState
from rolling_thunder.context_navigation import ContextId, ContextNavigationController
from rolling_thunder.domain import RadioState
from rolling_thunder.physical_controls import ControlAction


class CallsignCaptureCommands(Protocol):
    """Existing callsign-capture capabilities used by operator commands."""

    @property
    def state(self) -> CallsignCaptureState:
        """Return the current immutable callsign-capture state."""

    def start_capture(self) -> bool:
        """Start one bounded callsign capture when permitted."""

    def discard(self) -> CallsignCaptureState:
        """Discard the pending callsign when permitted."""


class ContactCommitCommands(Protocol):
    """Existing durable background Commit capability."""

    def start_commit(self, pending_callsign: str, radio_state: RadioState) -> bool:
        """Start one durable contact Commit when permitted."""


class ActivePanelCommands(Protocol):
    """Context-aware capabilities for the active dashboard panel."""

    def activate_context(self, context_id: ContextId) -> None:
        """Synchronize panel state after an explicit context change."""

    def primary(self) -> bool:
        """Run the active panel's first context-sensitive command."""

    def secondary(self) -> bool:
        """Run the active panel's second context-sensitive command."""

    def tertiary(self) -> bool:
        """Run the active panel's third context-sensitive command."""

    def tertiary_long(self) -> bool:
        """Run the active panel's long third command."""

    def move_previous(self) -> bool:
        """Move selection toward the previous active-panel item."""

    def move_next(self) -> bool:
        """Move selection toward the next active-panel item."""

    def activate_selection(self) -> bool:
        """Activate the current selection without bypassing safeguards."""

    def back(self) -> bool:
        """Cancel or clear the current active-panel interaction."""


_CONTEXT_ACTIONS: dict[ControlAction, ContextId] = {
    ControlAction.SELECT_POTA: ContextId.POTA,
    ControlAction.SELECT_DX: ContextId.DX,
    ControlAction.SELECT_REPEATERS: ContextId.REPEATERS,
    ControlAction.SELECT_AI: ContextId.AI,
    ControlAction.SELECT_SETTINGS: ContextId.SETTINGS,
}


class OperatorCommandController:
    """Route approved operator actions through existing application commands."""

    def __init__(
        self,
        capture: CallsignCaptureCommands,
        contact_commit: ContactCommitCommands,
        context_navigation: ContextNavigationController,
        radio_state: Callable[[], RadioState],
        active_panel: ActivePanelCommands | None = None,
        cancel_ptt_alarm: Callable[[], bool] | None = None,
        ptt_unlock_step: Callable[[ControlAction], bool] | None = None,
    ) -> None:
        self._capture = capture
        self._contact_commit = contact_commit
        self._context_navigation = context_navigation
        self._radio_state = radio_state
        self._active_panel = active_panel
        self._cancel_ptt_alarm = cancel_ptt_alarm
        self._ptt_unlock_step = ptt_unlock_step

    def execute(self, action: ControlAction) -> bool:
        """Execute one approved action, returning whether it was accepted."""
        if self._ptt_unlock_step is not None and action in (
            ControlAction.PANEL_PRIMARY, ControlAction.PANEL_TERTIARY,
        ) and self._ptt_unlock_step(action):
            return True
        if action is ControlAction.VOICE:
            return self._capture.start_capture()

        if action is ControlAction.DISCARD:
            if self._cancel_ptt_alarm is not None and self._cancel_ptt_alarm():
                return True
            before = self._capture.state
            after = self._capture.discard()
            return after != before

        if action is ControlAction.COMMIT:
            capture_state = self._capture.state
            if capture_state.commit_state != "READY" or not capture_state.pending_callsign:
                return False
            return self._contact_commit.start_commit(
                capture_state.pending_callsign,
                self._radio_state(),
            )

        if action is ControlAction.NEXT_CONTEXT:
            navigation_state = self._context_navigation.select_next()
            self._activate_context(navigation_state.selected)
            return True

        if action is ControlAction.HOME_CONTEXT:
            navigation_state = self._context_navigation.select_home()
            self._activate_context(navigation_state.selected)
            return True

        if action is ControlAction.PANEL_PRIMARY:
            return self._active_panel is not None and self._active_panel.primary()

        if action is ControlAction.PANEL_SECONDARY:
            return self._active_panel is not None and self._active_panel.secondary()

        if action is ControlAction.PANEL_TERTIARY:
            return self._active_panel is not None and self._active_panel.tertiary()

        if action is ControlAction.PANEL_TERTIARY_LONG:
            return (
                self._active_panel is not None
                and self._active_panel.tertiary_long()
            )

        if action is ControlAction.MOVE_PREVIOUS:
            return self._active_panel is not None and self._active_panel.move_previous()

        if action is ControlAction.MOVE_NEXT:
            return self._active_panel is not None and self._active_panel.move_next()

        if action is ControlAction.ACTIVATE_SELECTION:
            return (
                self._active_panel is not None
                and self._active_panel.activate_selection()
            )

        if action is ControlAction.BACK:
            return self._active_panel is not None and self._active_panel.back()

        context_id = _CONTEXT_ACTIONS.get(action)
        if context_id is None:
            return False
        self._context_navigation.select(context_id)
        self._activate_context(context_id)
        return True

    def _activate_context(self, context_id: ContextId) -> None:
        if self._active_panel is not None:
            self._active_panel.activate_context(context_id)
