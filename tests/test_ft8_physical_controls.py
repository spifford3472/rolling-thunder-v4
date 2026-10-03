"""End-to-end physical-control routing tests for the FT8 dashboard context."""

from datetime import UTC, datetime

from rolling_thunder.callsign_capture import CallsignCaptureState
from rolling_thunder.context_navigation import ContextId, ContextNavigationController
from rolling_thunder.control_dispatcher import ControlDispatcher
from rolling_thunder.domain import Frequency, RadioConnectionState, RadioMode, RadioState
from rolling_thunder.ft8.domain import FT8QsoState
from rolling_thunder.ft8.panel import FT8PanelMode, FT8PanelSnapshot
from rolling_thunder.ft8_active_panel_commands import FT8AwareActivePanelCommands
from rolling_thunder.operator_commands import OperatorCommandController
from rolling_thunder.physical_controls import (
    ControlAction,
    ControlActionMapper,
    ControlEventGate,
    ControlInputEvent,
    MockControlSource,
)


class Capture:
    @property
    def state(self) -> CallsignCaptureState:
        return CallsignCaptureState()

    def start_capture(self) -> bool:
        return False

    def discard(self) -> CallsignCaptureState:
        return self.state


class Commit:
    def start_commit(self, pending_callsign: str, radio_state: RadioState) -> bool:
        del pending_callsign, radio_state
        return False


class Delegate:
    def activate_context(self, context_id: ContextId) -> None:
        del context_id

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

    def synchronize_radio_state(self) -> bool:
        return True


class Panel:
    def __init__(self) -> None:
        self.mode = FT8PanelMode.BROWSE
        self.selected_callsign: str | None = None
        self.calls: list[str] = []

    def snapshot(self) -> FT8PanelSnapshot:
        state = FT8QsoState.IDLE
        if self.mode is FT8PanelMode.ACTIVE:
            state = FT8QsoState.WAIT_REPORT
        elif self.mode is FT8PanelMode.TERMINAL:
            state = FT8QsoState.ABORTED
        return FT8PanelSnapshot(mode=self.mode, cq_activity=(), qso_state=state)

    def select_previous(self) -> str | None:
        self.calls.append("previous")
        self.selected_callsign = "K1AAA"
        return self.selected_callsign

    def select_next(self) -> str | None:
        self.calls.append("next")
        self.selected_callsign = "K2BBB"
        return self.selected_callsign

    def clear_selection(self) -> bool:
        self.calls.append("clear")
        changed = self.selected_callsign is not None
        self.selected_callsign = None
        return changed

    def activate_selection(self) -> bool:
        self.calls.append("activate")
        return self.selected_callsign is not None

    def abort(self) -> None:
        self.calls.append("abort")

    def return_to_browser(self) -> object | None:
        self.calls.append("return")
        return object()


def _radio_state() -> RadioState:
    return RadioState(
        connection_state=RadioConnectionState.CONNECTED,
        frequency=Frequency(hz=14_074_000),
        mode=RadioMode.DATA,
        updated_at=datetime(2026, 10, 2, 20, 0, tzinfo=UTC),
    )


def _dispatch(
    input_id: str,
    action: ControlAction,
    *,
    panel: Panel,
    event_id: str,
) -> int:
    navigation = ContextNavigationController(ContextId.FT8)
    active_panel = FT8AwareActivePanelCommands(navigation, Delegate(), panel)
    commands = OperatorCommandController(
        Capture(),
        Commit(),
        navigation,
        _radio_state,
        active_panel,
    )
    source = MockControlSource(
        (
            ControlInputEvent(
                input_id=input_id,
                event_id=event_id,
                occurred_at_s=1.0,
            ),
        )
    )
    dispatcher = ControlDispatcher(
        source,
        ControlActionMapper({input_id: action}),
        ControlEventGate(repeat_suppression_s=0.0),
        commands,
    )
    return dispatcher.dispatch_available().accepted


def test_encoder_clockwise_reaches_ft8_selection_path() -> None:
    panel = Panel()

    accepted = _dispatch(
        "encoder-clockwise",
        ControlAction.MOVE_NEXT,
        panel=panel,
        event_id="rotate-1",
    )

    assert accepted == 1
    assert panel.selected_callsign == "K2BBB"
    assert panel.calls == ["next"]


def test_encoder_short_press_reaches_ft8_activation_path() -> None:
    panel = Panel()
    panel.selected_callsign = "K2BBB"

    accepted = _dispatch(
        "encoder-switch-short",
        ControlAction.ACTIVATE_SELECTION,
        panel=panel,
        event_id="press-1",
    )

    assert accepted == 1
    assert panel.calls == ["activate"]


def test_context_button_3_short_reaches_ft8_abort_path() -> None:
    panel = Panel()
    panel.mode = FT8PanelMode.ACTIVE

    accepted = _dispatch(
        "context-button-3-short",
        ControlAction.PANEL_TERTIARY,
        panel=panel,
        event_id="button3-1",
    )

    assert accepted == 1
    assert panel.calls == ["abort"]
