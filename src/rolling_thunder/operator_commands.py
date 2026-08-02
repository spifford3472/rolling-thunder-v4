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
    ) -> None:
        self._capture = capture
        self._contact_commit = contact_commit
        self._context_navigation = context_navigation
        self._radio_state = radio_state

    def execute(self, action: ControlAction) -> bool:
        """Execute one approved action, returning whether it was accepted."""
        if action is ControlAction.VOICE:
            return self._capture.start_capture()

        if action is ControlAction.DISCARD:
            before = self._capture.state
            after = self._capture.discard()
            return after != before

        if action is ControlAction.COMMIT:
            state = self._capture.state
            if state.commit_state != "READY" or not state.pending_callsign:
                return False
            return self._contact_commit.start_commit(
                state.pending_callsign,
                self._radio_state(),
            )

        if action is ControlAction.NEXT_CONTEXT:
            self._context_navigation.select_next()
            return True

        if action is ControlAction.HOME_CONTEXT:
            self._context_navigation.select_home()
            return True

        context_id = _CONTEXT_ACTIONS.get(action)
        if context_id is None:
            return False
        self._context_navigation.select(context_id)
        return True
