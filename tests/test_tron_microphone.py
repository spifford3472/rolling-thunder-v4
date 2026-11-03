"""Offline worker, bounded queue, and preemption tests without audio hardware."""

from threading import Event, get_ident

from rolling_thunder.audio_capture import AudioCaptureCancelled, AudioCaptureError
from rolling_thunder.tron_microphone import (
    TronMicrophoneService,
    TronWorkerEvent,
)


class FakeModelProvider:
    def warm(self, _sample_rate: int = 16_000) -> None:
        return None

    def create_recognizer(self, _sample_rate: int, _grammar: tuple[str, ...]) -> object:
        raise AssertionError("capture tests must not initialize Vosk")


def make_service(**overrides: object) -> TronMicrophoneService:
    values: dict[str, object] = {
        "audio_device": "plughw:CARD=Array,DEV=0",
        "model_provider": FakeModelProvider(),
        "retry_delay_s": 0.05,
    }
    values.update(overrides)
    return TronMicrophoneService(**values)  # type: ignore[arg-type]


def test_queue_saturation_drops_oldest_without_blocking() -> None:
    service = make_service(queue_size=2)
    for generation in range(3):
        assert service.events.publish(
            TronWorkerEvent(generation, "recognition_error", message=str(generation))
        )

    assert service.events.dropped_count == 1
    assert [item.message for item in service.drain_events(8)] == ["1", "2"]


def test_dispatch_is_bounded_current_generation_and_on_caller_thread() -> None:
    service = make_service(queue_size=10)
    service.events.publish(TronWorkerEvent(99, "recognition_error", message="stale"))
    service.events.publish(
        TronWorkerEvent(service.generation, "recognition_error", message="current")
    )
    observed: list[tuple[str, int]] = []
    caller = get_ident()

    count = service.dispatch_pending_events(
        lambda event: observed.append((event.message, get_ident())),
        limit=1,
    )

    assert count == 0
    assert observed == []
    assert service.dispatch_pending_events(
        lambda event: observed.append((event.message, get_ident())),
        limit=8,
    ) == 1
    assert observed == [("current", caller)]


def test_callsign_preemption_cancels_recording_before_capture(monkeypatch) -> None:
    service = make_service()
    recording = Event()
    callsign_started = Event()
    captures = 0

    def fake_capture(**kwargs: object) -> bytes:
        nonlocal captures
        captures += 1
        stop_event = kwargs["stop_event"]
        assert isinstance(stop_event, Event)
        recording.set()
        if stop_event.wait(1):
            raise AudioCaptureCancelled("cancelled by callsign")
        raise AssertionError("test recording should be preempted")

    monkeypatch.setattr("rolling_thunder.tron_microphone.capture_alsa_pcm", fake_capture)
    assert service.start_listening()
    assert recording.wait(1)

    assert service.request_callsign(lambda: (callsign_started.set() or True))
    assert callsign_started.wait(1)
    assert service.coordinator.gate.owner == "callsign"
    assert captures == 1

    service.callsign_finished()
    assert service.shutdown(timeout_s=1)


def test_microphone_disconnect_publishes_error_and_stops_cleanly(monkeypatch) -> None:
    service = make_service()
    attempted = Event()

    def disconnected(**_kwargs: object) -> bytes:
        attempted.set()
        raise AudioCaptureError("device disconnected")

    monkeypatch.setattr("rolling_thunder.tron_microphone.capture_alsa_pcm", disconnected)
    assert service.start_listening()
    assert attempted.wait(1)

    events = service.drain_events(limit=8)
    assert any(event.kind == "audio_error" for event in events)
    assert service.shutdown(timeout_s=1)


def test_shutdown_cancels_worker_during_recording(monkeypatch) -> None:
    service = make_service()
    recording = Event()
    cancelled = Event()

    def fake_capture(**kwargs: object) -> bytes:
        stop_event = kwargs["stop_event"]
        assert isinstance(stop_event, Event)
        recording.set()
        stop_event.wait(1)
        cancelled.set()
        raise AudioCaptureCancelled("shutdown")

    monkeypatch.setattr("rolling_thunder.tron_microphone.capture_alsa_pcm", fake_capture)
    assert service.start_listening()
    assert recording.wait(1)
    assert service.shutdown(timeout_s=1)
    assert cancelled.is_set()
    assert service.coordinator.gate.owner is None


def test_stalled_tron_preemption_reports_without_starting_callsign(monkeypatch) -> None:
    now = [1.0]
    service = make_service(clock=lambda: now[0])
    recording = Event()
    release_recording = Event()
    callsign_started = Event()

    def stuck_capture(**_kwargs: object) -> bytes:
        recording.set()
        release_recording.wait(1)
        raise AudioCaptureCancelled("released after test")

    monkeypatch.setattr(
        "rolling_thunder.tron_microphone.capture_alsa_pcm", stuck_capture
    )
    assert service.start_listening()
    assert recording.wait(1)
    assert service.request_callsign(lambda: (callsign_started.set() or True))

    now[0] = 4.0
    assert service.callsign_preemption_stalled(timeout_s=2.0)
    assert not service.callsign_preemption_stalled(timeout_s=2.0)
    assert not callsign_started.is_set()

    release_recording.set()
    assert callsign_started.wait(1)
    service.callsign_finished()
    assert service.shutdown(timeout_s=1)


def test_service_is_idle_until_operator_requests_listening() -> None:
    service = make_service()
    assert not service.listening_requested
    assert service.coordinator.gate.owner is None
    assert service.shutdown(timeout_s=1)


def test_callsign_preempts_while_vosk_model_is_loading() -> None:
    warming = Event()
    finish_warm = Event()

    class BlockingProvider(FakeModelProvider):
        def warm(self, _sample_rate: int = 16_000) -> None:
            warming.set()
            finish_warm.wait(1)

    service = make_service(model_provider=BlockingProvider())
    assert service.start_listening()
    assert warming.wait(1)

    callsign_started = Event()
    assert service.request_callsign(lambda: (callsign_started.set() or True))
    assert callsign_started.wait(1)
    assert service.coordinator.gate.owner == "callsign"

    service.pause_listening()
    service.callsign_finished()
    finish_warm.set()
    assert service.shutdown(timeout_s=1)
