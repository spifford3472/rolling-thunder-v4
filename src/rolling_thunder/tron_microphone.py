"""Cancellable offline Tron microphone worker and bounded UI event queue."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from queue import Empty, Full, Queue
from threading import Event, Lock, Thread
from time import monotonic
from typing import Literal, Protocol

from rolling_thunder.audio_capture import AudioCaptureCancelled, AudioCaptureError, capture_alsa_pcm
from rolling_thunder.callsign_capture import CallsignCaptureState
from rolling_thunder.speech_recognition import (
    SpeechRecognitionError,
    VoskModelProvider,
    VoskRecognizer,
    _downmix_s16le_to_mono,
)
from rolling_thunder.tron_capture_coordinator import TronCaptureCoordinator
from rolling_thunder.tron_commands import TronIntent
from rolling_thunder.tron_recognition import recognize_tron_pcm

_LOGGER = logging.getLogger(__name__)
TronEventKind = Literal["intent", "audio_error", "recognition_error"]


@dataclass(frozen=True, slots=True)
class TronWorkerEvent:
    """Immutable worker publication consumed by Tk on its owning thread."""

    generation: int
    kind: TronEventKind
    intent: TronIntent | None = None
    message: str = ""
    created_at_monotonic: float = 0.0


class BoundedTronEventQueue:
    """Thread-safe bounded worker queue; producers never wait for the UI."""

    def __init__(self, maxsize: int = 16) -> None:
        if maxsize < 1:
            raise ValueError("maxsize must be at least one")
        self._queue: Queue[TronWorkerEvent] = Queue(maxsize=maxsize)
        self._dropped = 0
        self._lock = Lock()

    @property
    def dropped_count(self) -> int:
        with self._lock:
            return self._dropped

    def publish(self, event: TronWorkerEvent) -> bool:
        """Publish without blocking; discard the oldest item on saturation."""
        try:
            self._queue.put_nowait(event)
            return True
        except Full:
            try:
                self._queue.get_nowait()
            except Empty:
                pass
            with self._lock:
                self._dropped += 1
            try:
                self._queue.put_nowait(event)
                return True
            except Full:
                with self._lock:
                    self._dropped += 1
                return False

    def drain(self, limit: int = 8) -> tuple[TronWorkerEvent, ...]:
        """Return at most ``limit`` pending publications."""
        if limit < 1:
            return ()
        result: list[TronWorkerEvent] = []
        for _ in range(limit):
            try:
                result.append(self._queue.get_nowait())
            except Empty:
                break
        return tuple(result)


class TronMicrophoneService:
    """Own the opt-in loop that captures bounded audio and recognizes commands."""

    def __init__(
        self,
        *,
        audio_device: str,
        model_provider: VoskModelProvider,
        sample_rate: int = 16_000,
        channels: int = 1,
        duration_s: int = 5,
        queue_size: int = 16,
        retry_delay_s: float = 1.5,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if not audio_device.strip():
            raise ValueError("Tron audio_device must not be blank")
        if sample_rate != 16_000:
            raise ValueError("Tron microphone input must use 16 kHz audio")
        if channels not in {1, 2} or duration_s < 1 or duration_s > 10:
            raise ValueError("Tron capture supports 1-2 channels and 1-10 seconds")
        if retry_delay_s <= 0:
            raise ValueError("Tron retry delay must be positive")
        self._audio_device = audio_device
        self._model_provider = model_provider
        self._sample_rate = sample_rate
        self._channels = channels
        self._duration_s = duration_s
        self._retry_delay_s = retry_delay_s
        self._clock = clock
        self.events = BoundedTronEventQueue(queue_size)
        self._lock = Lock()
        self._generation = 0
        self._desired_listening = False
        self._shutdown = False
        self._last_error_at = 0.0
        self._model_ready = Event()
        self._prepare_thread: Thread | None = None
        self._prepare_error: str | None = None
        self._callsign_wait_started: float | None = None
        self._callsign_wait_reported = False
        self.coordinator = TronCaptureCoordinator(
            on_callsign_finished=self._resume_after_callsign
        )

    @property
    def generation(self) -> int:
        with self._lock:
            return self._generation

    @property
    def listening_requested(self) -> bool:
        with self._lock:
            return self._desired_listening and not self._shutdown

    @property
    def model_ready(self) -> bool:
        with self._lock:
            return self._model_ready.is_set() and self._prepare_error is None

    def prepare(self) -> bool:
        """Warm the shared Vosk model off the UI thread, at most once at a time."""
        with self._lock:
            if self._shutdown:
                return False
            if self._prepare_thread is not None and self._prepare_thread.is_alive():
                return True
            if self._model_ready.is_set() and self._prepare_error is None:
                return True
            self._model_ready.clear()
            self._prepare_error = None
            worker = Thread(
                target=self._prepare_model,
                daemon=True,
                name="tron-model-prepare",
            )
            self._prepare_thread = worker
            try:
                worker.start()
            except RuntimeError as error:
                self._prepare_error = str(error)
                self._model_ready.set()
                return False
        return True

    def start_listening(self) -> bool:
        """Enable live listening and start at most one background worker."""
        with self._lock:
            if self._shutdown:
                return False
            self._desired_listening = True
            generation = self._generation
        if not self.prepare():
            return False
        return self._start_worker(generation)

    def pause_listening(self) -> None:
        """Stop accepting commands without waiting for the recording process."""
        with self._lock:
            self._desired_listening = False
            self._generation += 1
        self.coordinator.request_stop_tron()

    def request_callsign(self, start_capture: Callable[[], bool]) -> bool:
        """Preempt Tron immediately and retain callsign priority until completion."""
        with self._lock:
            if self._shutdown:
                return False
            self._generation += 1
        accepted = self.coordinator.request_callsign(start_capture)
        with self._lock:
            if accepted and self.coordinator.callsign_waiting_for_tron:
                self._callsign_wait_started = self._clock()
                self._callsign_wait_reported = False
            else:
                self._callsign_wait_started = None
                self._callsign_wait_reported = False
        return accepted

    def callsign_preemption_stalled(self, timeout_s: float = 2.0) -> bool:
        """Return true once if Tron has not yielded the device within the bound."""
        with self._lock:
            started = self._callsign_wait_started
            if (
                started is None
                or self._callsign_wait_reported
                or not self.coordinator.callsign_waiting_for_tron
                or self._clock() - started < timeout_s
            ):
                return False
            self._callsign_wait_reported = True
            return True

    def callsign_finished(self) -> None:
        """Compatibility hook for capture adapters without a completion callback."""
        self.coordinator.callsign_finished()

    def shutdown(self, *, timeout_s: float = 3.0) -> bool:
        """Stop future listening and join the audio worker from a background thread."""
        with self._lock:
            self._shutdown = True
            self._desired_listening = False
            self._generation += 1
            prepare_thread = self._prepare_thread
        worker_stopped = self.coordinator.shutdown(timeout_s=timeout_s)
        if prepare_thread is not None and prepare_thread.is_alive():
            prepare_thread.join(timeout=max(0.0, timeout_s))
            return worker_stopped and not prepare_thread.is_alive()
        return worker_stopped

    def drain_events(self, limit: int = 8) -> tuple[TronWorkerEvent, ...]:
        """Drain a bounded number of publications for the Tk main loop."""
        return self.events.drain(limit)

    def dispatch_pending_events(
        self,
        handler: Callable[[TronWorkerEvent], None],
        *,
        limit: int = 8,
    ) -> int:
        """Dispatch only current-generation events on the caller's thread.

        The Tk refresh loop calls this method. The service deliberately does
        not create a dispatcher thread or touch UI objects itself.
        """
        dispatched = 0
        for event in self.drain_events(limit):
            if event.generation != self.generation:
                continue
            handler(event)
            dispatched += 1
        return dispatched

    def _start_worker(self, generation: int) -> bool:
        return self.coordinator.start_tron(
            lambda stop_event: self._listen(stop_event, generation)
        )

    def _resume_after_callsign(self) -> None:
        with self._lock:
            if self._shutdown or not self._desired_listening:
                return
            generation = self._generation
        self._start_worker(generation)

    def _prepare_model(self) -> None:
        generation = self.generation
        try:
            self._model_provider.warm(self._sample_rate)
        except Exception as error:  # noqa: BLE001 - contain native Vosk failures
            with self._lock:
                self._prepare_error = str(error)[:240]
            self._publish_error(generation, "recognition_error", str(error))
        finally:
            self._model_ready.set()

    def _listen(self, stop_event: Event, generation: int) -> None:
        while not stop_event.is_set() and not self._model_ready.wait(0.05):
            pass
        if stop_event.is_set():
            return
        with self._lock:
            prepare_error = self._prepare_error
        if prepare_error is not None:
            self._publish_error(generation, "recognition_error", prepare_error)
            return
        while not stop_event.is_set():
            try:
                multichannel_pcm = capture_alsa_pcm(
                    audio_device=self._audio_device,
                    duration_s=self._duration_s,
                    sample_rate=self._sample_rate,
                    channels=self._channels,
                    stop_event=stop_event,
                )
                mono_pcm = _downmix_s16le_to_mono(multichannel_pcm, self._channels)
                intent = recognize_tron_pcm(
                    mono_pcm,
                    recognizer_factory=lambda grammar: self._create_recognizer(grammar),
                    max_audio_bytes=self._duration_s * self._sample_rate * 2,
                    stop_event=stop_event,
                    on_error=lambda message: self._publish_error(
                        generation, "recognition_error", message
                    ),
                )
                if intent is not None and not stop_event.is_set():
                    self.events.publish(
                        TronWorkerEvent(
                            generation=generation,
                            kind="intent",
                            intent=intent,
                            created_at_monotonic=self._clock(),
                        )
                    )
                stop_event.wait(0.1)
            except AudioCaptureCancelled:
                return
            except (AudioCaptureError, SpeechRecognitionError, OSError, ValueError) as error:
                if stop_event.is_set():
                    return
                self._publish_error(generation, "audio_error", str(error))
                stop_event.wait(self._retry_delay_s)
            except Exception as error:
                _LOGGER.exception("Unexpected Tron microphone failure")
                if stop_event.is_set():
                    return
                self._publish_error(generation, "recognition_error", str(error))
                stop_event.wait(self._retry_delay_s)

    def _create_recognizer(self, grammar: tuple[str, ...]) -> VoskRecognizer:
        return self._model_provider.create_recognizer(self._sample_rate, grammar)

    def _publish_error(self, generation: int, kind: TronEventKind, message: str) -> None:
        now = self._clock()
        if now - self._last_error_at < self._retry_delay_s:
            return
        self._last_error_at = now
        self.events.publish(
            TronWorkerEvent(
                generation=generation,
                kind=kind,
                message=message[:240],
                created_at_monotonic=now,
            )
        )

class CallsignCaptureAdapter(Protocol):
    """Existing callsign workflows accepted by the priority adapter."""

    @property
    def state(self) -> CallsignCaptureState: ...
    def start_capture(self) -> bool: ...
    def preload_callsign(self, callsign: str) -> bool: ...
    def discard(self) -> CallsignCaptureState: ...
    def commit_started(self, callsign: str) -> CallsignCaptureState: ...
    def commit_succeeded(self, callsign: str) -> CallsignCaptureState: ...
    def commit_failed(self, message: str) -> CallsignCaptureState: ...


class PriorityCallsignCapture:
    """Preserve the callsign controller API while reserving audio first."""

    def __init__(
        self,
        capture: CallsignCaptureAdapter,
        microphone: TronMicrophoneService,
    ) -> None:
        self._capture = capture
        self._microphone = microphone

    @property
    def state(self) -> CallsignCaptureState:
        return self._capture.state

    def start_capture(self) -> bool:
        return self._microphone.request_callsign(self._capture.start_capture)

    def preload_callsign(self, callsign: str) -> bool:
        return self._capture.preload_callsign(callsign)

    def discard(self) -> CallsignCaptureState:
        return self._capture.discard()

    def commit_started(self, callsign: str) -> CallsignCaptureState:
        return self._capture.commit_started(callsign)

    def commit_succeeded(self, callsign: str) -> CallsignCaptureState:
        return self._capture.commit_succeeded(callsign)

    def commit_failed(self, message: str) -> CallsignCaptureState:
        return self._capture.commit_failed(message)
