"""Tests that operator context changes notify the active panel uniformly."""

from datetime import UTC, datetime

from rolling_thunder.callsign_capture import CallsignCaptureState
from rolling_thunder.context_navigation import ContextId, ContextNavigationController
from rolling_thunder.domain import Frequency, RadioConnectionState, RadioMode, RadioState
from rolling_thunder.operator_commands import OperatorCommandController
from rolling_thunder.physical_controls import ControlAction


class FakeCapture:
    @property
    def state(self) -> CallsignCaptureState:
        return CallsignCaptureState()

    def start_capture(self) -> bool:
        return False

    def discard(self) -> CallsignCaptureState:
        return self.state


class FakeCommit:
    def start_commit(self, pending_callsign: str, radio_state: RadioState) -> bool:
        del pending_callsign, radio_state
        return False


class RecordingActivePanel:
    def __init__(self) -> None:
        self.contexts: list[ContextId] = []

    def activate_context(self, context_id: ContextId) -> None:
        self.contexts.append(context_id)

    def primary(self) -> bool:
        return False

    def secondary(self) -> bool:
        return False

    def tertiary(self) -> bool:
        return False

    def tertiary_long(self) -> bool:
        return False

    def move_previous(self) -> bool:
        return False

    def move_next(self) -> bool:
        return False

    def activate_selection(self) -> bool:
        return False

    def back(self) -> bool:
        return False


def radio_state() -> RadioState:
    return RadioState(
        connection_state=RadioConnectionState.CONNECTED,
        frequency=Frequency(hz=14_250_000),
        mode=RadioMode.USB,
        updated_at=datetime(2026, 8, 8, 1, 0, tzinfo=UTC),
    )


def build_commands(
    navigation: ContextNavigationController,
    active_panel: RecordingActivePanel,
) -> OperatorCommandController:
    return OperatorCommandController(
        FakeCapture(),
        FakeCommit(),
        navigation,
        radio_state,
        active_panel,
    )


def test_direct_context_action_notifies_active_panel_after_navigation() -> None:
    navigation = ContextNavigationController(ContextId.POTA)
    panel = RecordingActivePanel()
    commands = build_commands(navigation, panel)

    assert commands.execute(ControlAction.SELECT_DX) is True

    assert navigation.state.selected is ContextId.DX
    assert panel.contexts == [ContextId.DX]


def test_next_context_notifies_active_panel() -> None:
    navigation = ContextNavigationController(ContextId.POTA)
    panel = RecordingActivePanel()
    commands = build_commands(navigation, panel)

    assert commands.execute(ControlAction.NEXT_CONTEXT) is True

    assert navigation.state.selected is ContextId.DX
    assert panel.contexts == [ContextId.DX]


def test_home_context_notifies_active_panel() -> None:
    navigation = ContextNavigationController(ContextId.SETTINGS)
    panel = RecordingActivePanel()
    commands = build_commands(navigation, panel)

    assert commands.execute(ControlAction.HOME_CONTEXT) is True

    assert navigation.state.selected is ContextId.POTA
    assert panel.contexts == [ContextId.POTA]
