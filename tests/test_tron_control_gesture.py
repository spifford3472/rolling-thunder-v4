from rolling_thunder.control_dispatcher import ControlDispatcher
from rolling_thunder.physical_controls import (
    ControlAction,
    ControlActionMapper,
    ControlInputEvent,
    MockControlSource,
)
from rolling_thunder.tron_control_gesture import TronCancelTriplePress


class AcceptAll:
    def accept(self, _event: ControlInputEvent) -> bool:
        return True


class RecordingCommands:
    def __init__(self) -> None:
        self.actions: list[ControlAction] = []

    def execute(self, action: ControlAction) -> bool:
        self.actions.append(action)
        return True


def dispatch_gesture(
    events: tuple[ControlInputEvent, ...],
    gesture: TronCancelTriplePress,
) -> RecordingCommands:
    commands = RecordingCommands()
    dispatcher = ControlDispatcher(
        MockControlSource(events),
        ControlActionMapper(
            {
                "discard-button": ControlAction.DISCARD,
                "voice-button": ControlAction.VOICE,
            }
        ),
        AcceptAll(),
        commands,
        event_interceptor=gesture,
    )
    result = dispatcher.dispatch_available()
    assert result.accepted == len(events)
    return commands


def test_three_discard_presses_toggle_and_still_run_discard_action() -> None:
    now = [0.0]
    toggles: list[str] = []
    gesture = TronCancelTriplePress(
        lambda: toggles.append("toggle"),
        clock=lambda: now[0],
    )
    events = tuple(
        ControlInputEvent("discard-button", f"event-{index}", float(index))
        for index in range(3)
    )

    commands = dispatch_gesture(events, gesture)

    assert toggles == ["toggle"]
    assert commands.actions == [ControlAction.DISCARD] * 3


def test_non_discard_action_breaks_the_consecutive_press_sequence() -> None:
    now = [0.0]
    toggles: list[str] = []
    gesture = TronCancelTriplePress(
        lambda: toggles.append("toggle"),
        clock=lambda: now[0],
    )
    events = (
        ControlInputEvent("discard-button", "event-1", 1.0),
        ControlInputEvent("voice-button", "event-2", 1.2),
        ControlInputEvent("discard-button", "event-3", 1.4),
        ControlInputEvent("discard-button", "event-4", 1.6),
        ControlInputEvent("discard-button", "event-5", 1.8),
    )

    dispatch_gesture(events, gesture)

    assert toggles == ["toggle"]


def test_disallowed_state_resets_partial_gesture_and_preserves_discard() -> None:
    now = [0.0]
    enabled = [True]
    toggles: list[str] = []
    gesture = TronCancelTriplePress(
        lambda: toggles.append("toggle"),
        allowed=lambda: enabled[0],
        clock=lambda: now[0],
    )
    assert gesture.intercept(
        ControlInputEvent("discard-button", "event-1", 1.0),
        ControlAction.DISCARD,
    ) is None
    enabled[0] = False
    assert gesture.intercept(
        ControlInputEvent("discard-button", "event-2", 1.2),
        ControlAction.DISCARD,
    ) is None
    enabled[0] = True
    assert gesture.intercept(
        ControlInputEvent("discard-button", "event-3", 1.4),
        ControlAction.DISCARD,
    ) is None
    assert gesture.intercept(
        ControlInputEvent("discard-button", "event-4", 1.6),
        ControlAction.DISCARD,
    ) is None
    assert toggles == []


def test_press_after_window_starts_a_new_sequence() -> None:
    now = [0.0]
    toggles: list[str] = []
    gesture = TronCancelTriplePress(
        lambda: toggles.append("toggle"),
        clock=lambda: now[0],
    )
    for index, timestamp in enumerate((0.0, 2.1, 2.5, 2.9), start=1):
        now[0] = timestamp
        gesture.intercept(
            ControlInputEvent("discard-button", f"event-{index}", timestamp),
            ControlAction.DISCARD,
        )
    assert toggles == ["toggle"]