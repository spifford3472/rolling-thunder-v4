"""Tests for safe physical-control event dispatch."""

from rolling_thunder.control_dispatcher import ControlDispatcher
from rolling_thunder.physical_controls import (
    ControlAction,
    ControlActionMapper,
    ControlEventGate,
    ControlInputEvent,
    MockControlSource,
)


class RecordingCommands:
    def __init__(self, accepted: bool = True) -> None:
        self.accepted = accepted
        self.actions: list[ControlAction] = []

    def execute(self, action: ControlAction) -> bool:
        self.actions.append(action)
        return self.accepted


def event(input_id: str, event_id: str, occurred_at_s: float) -> ControlInputEvent:
    return ControlInputEvent(
        input_id=input_id,
        event_id=event_id,
        occurred_at_s=occurred_at_s,
    )


def dispatcher(
    events: tuple[ControlInputEvent, ...],
    commands: RecordingCommands,
) -> ControlDispatcher:
    return ControlDispatcher(
        MockControlSource(events),
        ControlActionMapper(
            {
                "voice-button": ControlAction.VOICE,
                "commit-button": ControlAction.COMMIT,
            }
        ),
        ControlEventGate(repeat_suppression_s=0.25),
        commands,
    )


def test_dispatcher_is_nonblocking_and_idle_when_source_is_empty() -> None:
    commands = RecordingCommands()

    result = dispatcher((), commands).dispatch_available()

    assert result.drained == 0
    assert result.accepted == 0
    assert commands.actions == []


def test_dispatcher_maps_and_invokes_approved_action() -> None:
    commands = RecordingCommands()

    result = dispatcher(
        (event("voice-button", "event-1", 1.0),),
        commands,
    ).dispatch_available()

    assert result.drained == 1
    assert result.accepted == 1
    assert result.rejected == 0
    assert result.unknown == 0
    assert commands.actions == [ControlAction.VOICE]


def test_unknown_input_never_reaches_application_commands() -> None:
    commands = RecordingCommands()

    result = dispatcher(
        (event("unknown-button", "event-1", 1.0),),
        commands,
    ).dispatch_available()

    assert result.unknown == 1
    assert result.accepted == 0
    assert commands.actions == []


def test_duplicate_event_is_dispatched_only_once() -> None:
    commands = RecordingCommands()

    result = dispatcher(
        (
            event("commit-button", "event-1", 1.0),
            event("commit-button", "event-1", 2.0),
        ),
        commands,
    ).dispatch_available()

    assert result.accepted == 1
    assert result.rejected == 1
    assert commands.actions == [ControlAction.COMMIT]


def test_rapid_repeat_is_suppressed_before_command_execution() -> None:
    commands = RecordingCommands()

    result = dispatcher(
        (
            event("voice-button", "event-1", 1.0),
            event("voice-button", "event-2", 1.1),
        ),
        commands,
    ).dispatch_available()

    assert result.accepted == 1
    assert result.rejected == 1
    assert commands.actions == [ControlAction.VOICE]


def test_command_rejection_is_reported_without_retry_or_fallback() -> None:
    commands = RecordingCommands(accepted=False)

    result = dispatcher(
        (event("commit-button", "event-1", 1.0),),
        commands,
    ).dispatch_available()

    assert result.accepted == 0
    assert result.rejected == 1
    assert commands.actions == [ControlAction.COMMIT]


def test_different_inputs_are_dispatched_independently() -> None:
    commands = RecordingCommands()

    result = dispatcher(
        (
            event("voice-button", "event-1", 1.0),
            event("commit-button", "event-2", 1.0),
        ),
        commands,
    ).dispatch_available()

    assert result.accepted == 2
    assert result.rejected == 0
    assert commands.actions == [ControlAction.VOICE, ControlAction.COMMIT]


def test_action_observer_records_only_accepted_typed_action_after_execution() -> None:
    import pytest

    commands = RecordingCommands()
    observations: list[tuple[str, float]] = []
    clock_values = iter((10.0, 10.0125))
    observed = ControlDispatcher(
        MockControlSource((event("voice-button", "event-1", 1.0),)),
        ControlActionMapper({"voice-button": ControlAction.VOICE}),
        ControlEventGate(repeat_suppression_s=0.25),
        commands,
        action_observer=lambda token, duration: observations.append((token, duration)),
        clock=lambda: next(clock_values),
    )

    assert observed.dispatch_available().accepted == 1
    assert commands.actions == [ControlAction.VOICE]
    assert observations[0][0] == "voice"
    assert observations[0][1] == pytest.approx(12.5)


def test_rejected_command_is_not_reported_as_accepted_action() -> None:
    commands = RecordingCommands(accepted=False)
    observations: list[tuple[str, float]] = []
    observed = ControlDispatcher(
        MockControlSource((event("commit-button", "event-1", 1.0),)),
        ControlActionMapper({"commit-button": ControlAction.COMMIT}),
        ControlEventGate(repeat_suppression_s=0.25),
        commands,
        action_observer=lambda token, duration: observations.append((token, duration)),
        clock=lambda: 10.0,
    )

    assert observed.dispatch_available().rejected == 1
    assert observations == []
