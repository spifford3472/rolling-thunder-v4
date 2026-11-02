"""Tests for background live callsign capture state."""

from threading import Event

from rolling_thunder.live_callsign_capture import LiveCallsignCaptureController
from rolling_thunder.speech_recognition import SpeechRecognitionError


class FakeRecognizer:
    """Return predetermined tokens after the test releases capture."""

    def __init__(self, tokens: tuple[str, ...]) -> None:
        self.tokens = tokens
        self.started = Event()
        self.release = Event()

    def capture_tokens(self, stop_event: Event | None = None) -> tuple[str, ...]:
        self.started.set()
        if stop_event is None:
            self.release.wait(timeout=2)
        else:
            while not self.release.is_set() and not stop_event.is_set():
                Event().wait(0.005)
        return self.tokens


class FailingRecognizer:
    def capture_tokens(self, _stop_event: Event | None = None) -> tuple[str, ...]:
        raise SpeechRecognitionError("device unavailable")


def wait_until_complete(controller: LiveCallsignCaptureController) -> None:
    for _ in range(200):
        if not controller.status.capturing:
            return
        Event().wait(0.01)
    raise AssertionError("capture worker did not complete")


def test_valid_capture_becomes_committable() -> None:
    recognizer = FakeRecognizer(
        ("KILO", "INDIA", "FIVE", "VICTOR", "NOVEMBER", "BRAVO")
    )
    controller = LiveCallsignCaptureController(recognizer)

    assert controller.start_capture() is True
    assert recognizer.started.wait(timeout=1)
    assert controller.state.voice_state == "LISTENING"
    assert controller.state.commit_state == "DISABLED"
    assert controller.start_capture() is False

    recognizer.release.set()
    wait_until_complete(controller)

    assert controller.state.pending_callsign == "KI5VNB"
    assert controller.state.voice_state == "READY"
    assert controller.state.commit_state == "READY"
    assert controller.state.last_result == "HEARD KI5VNB"


def test_empty_capture_reports_no_speech() -> None:
    recognizer = FakeRecognizer(())
    controller = LiveCallsignCaptureController(recognizer)

    controller.start_capture()
    recognizer.release.set()
    wait_until_complete(controller)

    assert controller.state.pending_callsign == ""
    assert controller.state.voice_state == "FAILED"
    assert controller.state.last_result == "NO SPEECH"


def test_invalid_capture_is_not_committable() -> None:
    recognizer = FakeRecognizer(("KILO", "UNKNOWN", "FIVE"))
    controller = LiveCallsignCaptureController(recognizer)

    controller.start_capture()
    recognizer.release.set()
    wait_until_complete(controller)

    assert controller.state.commit_state == "DISABLED"
    assert controller.state.last_result == "VOICE ERROR"


def test_recognition_failure_surfaces_microphone_error() -> None:
    controller = LiveCallsignCaptureController(FailingRecognizer())

    controller.start_capture()
    wait_until_complete(controller)

    assert controller.state.commit_state == "DISABLED"
    assert controller.state.last_result == "MIC ERROR"


def test_discard_clears_completed_capture() -> None:
    recognizer = FakeRecognizer(
        ("GOLF", "BRAVO", "NINER", "ZERO", "MIKE", "GOLF", "YANKEE")
    )
    controller = LiveCallsignCaptureController(recognizer)
    controller.start_capture()
    recognizer.release.set()
    wait_until_complete(controller)

    discarded = controller.discard()

    assert discarded.pending_callsign == ""
    assert discarded.commit_state == "DISABLED"
    assert discarded.last_result == "DISCARDED"


def test_selected_spot_callsign_preloads_live_capture_state() -> None:
    controller = LiveCallsignCaptureController(FakeRecognizer(()))

    assert controller.preload_callsign("k1dx") is True
    assert controller.state.pending_callsign == "K1DX"
    assert controller.state.commit_state == "READY"
    assert controller.state.last_result == "SELECTED K1DX"


def test_completed_voice_capture_overwrites_selected_spot_callsign() -> None:
    recognizer = FakeRecognizer(
        ("KILO", "INDIA", "FIVE", "VICTOR", "NOVEMBER", "BRAVO")
    )
    controller = LiveCallsignCaptureController(recognizer)
    assert controller.preload_callsign("K1DX") is True

    assert controller.start_capture() is True
    recognizer.release.set()
    wait_until_complete(controller)

    assert controller.state.pending_callsign == "KI5VNB"
    assert controller.state.last_result == "HEARD KI5VNB"


def test_cancel_signals_worker_and_completion_fires_afterward() -> None:
    recognizer = FakeRecognizer(("KILO",))
    completed = Event()
    controller = LiveCallsignCaptureController(
        recognizer, on_finished=completed.set
    )

    assert controller.start_capture()
    assert recognizer.started.wait(1)
    assert controller.cancel_capture()
    assert completed.wait(1)
    assert controller.state.last_result == "CANCELLED"
    assert not controller.status.capturing
