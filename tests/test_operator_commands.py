"""Tests for shared graphical and physical operator commands."""

from datetime import UTC, datetime

from rolling_thunder.callsign_capture import CallsignCaptureState
from rolling_thunder.context_navigation import ContextId, ContextNavigationController
from rolling_thunder.domain import (
    Frequency,
    RadioConnectionState,
    RadioMode,
    RadioState,
)
from rolling_thunder.operator_commands import OperatorCommandController
from rolling_thunder.physical_controls import ControlAction


class FakeCapture:
    def __init__(self, state: CallsignCaptureState | None = None) -> None:
        self._state = state or CallsignCaptureState()
        self.start_result = True
        self.start_calls = 0
        self.discard_calls = 0

    @property
    def state(self) -> CallsignCaptureState:
        return self._state

    def start_capture(self) -> bool:
        self.start_calls += 1
        return self.start_result

    def discard(self) -> CallsignCaptureState:
        self.discard_calls += 1
        if self._state.commit_state == "COMMITTING":
            return self._state
        self._state = CallsignCaptureState(last_result="DISCARDED")
        return self._state


class FakeCommit:
    def __init__(self) -> None:
        self.result = True
        self.calls: list[tuple[str, RadioState]] = []

    def start_commit(self, pending_callsign: str, radio_state: RadioState) -> bool:
        self.calls.append((pending_callsign, radio_state))
        return self.result


def connected_radio() -> RadioState:
    return RadioState(
        connection_state=RadioConnectionState.CONNECTED,
        frequency=Frequency(hz=14_250_000),
        mode=RadioMode.USB,
        updated_at=datetime(2026, 7, 27, 22, 0, tzinfo=UTC),
    )


def controller(
    capture: FakeCapture,
    commit: FakeCommit,
    navigation: ContextNavigationController | None = None,
) -> OperatorCommandController:
    return OperatorCommandController(
        capture,
        commit,
        navigation or ContextNavigationController(),
        connected_radio,
    )


def test_voice_delegates_once_and_preserves_busy_result() -> None:
    capture = FakeCapture()
    commit = FakeCommit()
    commands = controller(capture, commit)

    assert commands.execute(ControlAction.VOICE) is True
    capture.start_result = False
    assert commands.execute(ControlAction.VOICE) is False
    assert capture.start_calls == 2
    assert commit.calls == []


def test_commit_requires_ready_pending_callsign() -> None:
    capture = FakeCapture(CallsignCaptureState())
    commit = FakeCommit()
    commands = controller(capture, commit)

    assert commands.execute(ControlAction.COMMIT) is False
    assert commit.calls == []


def test_commit_uses_existing_background_controller_with_radio_snapshot() -> None:
    capture = FakeCapture(
        CallsignCaptureState(
            pending_callsign="KI5VNB",
            commit_state="READY",
        )
    )
    commit = FakeCommit()
    commands = controller(capture, commit)

    assert commands.execute(ControlAction.COMMIT) is True
    assert commit.calls == [("KI5VNB", connected_radio())]


def test_commit_preserves_existing_duplicate_request_result() -> None:
    capture = FakeCapture(
        CallsignCaptureState(
            pending_callsign="W8O",
            commit_state="READY",
        )
    )
    commit = FakeCommit()
    commit.result = False

    assert controller(capture, commit).execute(ControlAction.COMMIT) is False
    assert len(commit.calls) == 1


def test_discard_delegates_without_calling_commit() -> None:
    capture = FakeCapture(
        CallsignCaptureState(
            pending_callsign="KI5VNB",
            commit_state="READY",
        )
    )
    commit = FakeCommit()

    assert controller(capture, commit).execute(ControlAction.DISCARD) is True
    assert capture.discard_calls == 1
    assert capture.state.pending_callsign == ""
    assert commit.calls == []


def test_discard_during_commit_is_rejected_by_existing_capture_policy() -> None:
    state = CallsignCaptureState(
        pending_callsign="KI5VNB",
        commit_state="COMMITTING",
    )
    capture = FakeCapture(state)
    commit = FakeCommit()

    assert controller(capture, commit).execute(ControlAction.DISCARD) is False
    assert capture.state == state
    assert commit.calls == []


def test_each_context_action_selects_exact_existing_context() -> None:
    expected = {
        ControlAction.SELECT_POTA: ContextId.POTA,
        ControlAction.SELECT_DX: ContextId.DX,
        ControlAction.SELECT_REPEATERS: ContextId.REPEATERS,
        ControlAction.SELECT_AI: ContextId.AI,
        ControlAction.SELECT_SETTINGS: ContextId.SETTINGS,
    }

    for action, context_id in expected.items():
        navigation = ContextNavigationController()
        commands = controller(FakeCapture(), FakeCommit(), navigation)

        assert commands.execute(action) is True
        assert navigation.state.selected is context_id
