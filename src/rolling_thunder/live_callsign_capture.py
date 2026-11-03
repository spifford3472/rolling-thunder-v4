"""Background push-to-listen callsign capture state and cancellation lifecycle."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from threading import Event, Lock, Thread

from rolling_thunder.callsign_capture import CallsignCaptureState
from rolling_thunder.phonetic_callsign import parse_phonetic_callsign
from rolling_thunder.speech_recognition import (
    SpeechRecognitionCancelled,
    SpeechRecognitionError,
    SpeechRecognizer,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class LiveCaptureStatus:
    """Observable live-capture status for UI polling."""

    state: CallsignCaptureState
    capturing: bool


class LiveCallsignCaptureController:
    """Run one cancellable microphone capture without blocking the UI thread."""

    def __init__(
        self,
        recognizer: SpeechRecognizer,
        *,
        on_finished: Callable[[], None] | None = None,
    ) -> None:
        self._recognizer = recognizer
        self._on_finished = on_finished
        self._lock = Lock()
        self._state = CallsignCaptureState()
        self._capturing = False
        self._stop_event: Event | None = None
        self._worker: Thread | None = None

    @property
    def status(self) -> LiveCaptureStatus:
        """Return a consistent immutable snapshot for presentation polling."""
        with self._lock:
            return LiveCaptureStatus(state=self._state, capturing=self._capturing)

    @property
    def state(self) -> CallsignCaptureState:
        """Return the latest capture presentation state."""
        return self.status.state

    def start_capture(self) -> bool:
        """Start one bounded capture; return false if a capture/commit is active."""
        with self._lock:
            if self._capturing or self._state.commit_state == "COMMITTING":
                return False
            stop_event = Event()
            self._stop_event = stop_event
            self._capturing = True
            self._state = CallsignCaptureState(
                voice_state="LISTENING",
                commit_state="DISABLED",
                last_result="LISTENING",
            )
            worker = Thread(
                target=self._capture_worker,
                args=(stop_event,),
                daemon=True,
                name="callsign-capture",
            )
            self._worker = worker
            try:
                worker.start()
            except RuntimeError:
                self._capturing = False
                self._stop_event = None
                self._worker = None
                self._state = CallsignCaptureState(
                    voice_state="FAILED",
                    commit_state="DISABLED",
                    last_result="VOICE ERROR",
                )
                return False
        return True

    def cancel_capture(self) -> bool:
        """Request immediate cooperative cancellation and let the worker reap audio."""
        with self._lock:
            stop_event = self._stop_event
            if not self._capturing or stop_event is None:
                return False
            stop_event.set()
            return True

    def shutdown(self, *, timeout_s: float = 3.0) -> bool:
        """Cancel and join the capture worker from an application cleanup thread."""
        with self._lock:
            worker = self._worker
            stop_event = self._stop_event
            if stop_event is not None:
                stop_event.set()
        if worker is not None and worker.is_alive():
            worker.join(timeout=max(0.0, timeout_s))
            return not worker.is_alive()
        return True

    def _capture_worker(self, stop_event: Event) -> None:
        new_state = CallsignCaptureState(
            voice_state="FAILED",
            commit_state="DISABLED",
            last_result="VOICE ERROR",
        )
        try:
            tokens = self._recognizer.capture_tokens(stop_event)
            if stop_event.is_set():
                new_state = CallsignCaptureState(
                    voice_state="FAILED",
                    commit_state="DISABLED",
                    last_result="CANCELLED",
                )
            else:
                result = parse_phonetic_callsign(tokens)
                if result.is_valid and result.callsign is not None:
                    new_state = CallsignCaptureState(
                        pending_callsign=result.callsign,
                        voice_state="READY",
                        commit_state="READY",
                        last_result=f"HEARD {result.callsign}",
                    )
                elif not tokens:
                    new_state = CallsignCaptureState(
                        voice_state="FAILED",
                        commit_state="DISABLED",
                        last_result="NO SPEECH",
                    )
                else:
                    new_state = CallsignCaptureState(
                        voice_state="FAILED",
                        commit_state="DISABLED",
                        last_result="VOICE ERROR",
                    )
        except SpeechRecognitionCancelled:
            new_state = CallsignCaptureState(
                voice_state="FAILED",
                commit_state="DISABLED",
                last_result="CANCELLED",
            )
        except SpeechRecognitionError:
            new_state = CallsignCaptureState(
                voice_state="FAILED",
                commit_state="DISABLED",
                last_result="MIC ERROR",
            )
        except Exception:
            _LOGGER.exception("Unexpected callsign recognition failure")
            new_state = CallsignCaptureState(
                voice_state="FAILED",
                commit_state="DISABLED",
                last_result="VOICE ERROR",
            )
        finally:
            with self._lock:
                self._state = new_state
                self._capturing = False
                self._stop_event = None
                self._worker = None
            if self._on_finished is not None:
                try:
                    self._on_finished()
                except Exception:
                    _LOGGER.exception("Callsign completion callback failed")

    def preload_callsign(self, callsign: str) -> bool:
        """Preload one selected spot callsign unless capture or Commit owns state."""
        normalized = callsign.strip().upper()
        if not normalized:
            return False
        with self._lock:
            if self._capturing or self._state.commit_state == "COMMITTING":
                return False
            self._state = CallsignCaptureState(
                pending_callsign=normalized,
                voice_state="READY",
                commit_state="READY",
                last_result=f"SELECTED {normalized}",
            )
            return True

    def discard(self) -> CallsignCaptureState:
        """Discard a completed pending callsign; active work continues safely."""
        with self._lock:
            if self._capturing or self._state.commit_state == "COMMITTING":
                return self._state
            self._state = CallsignCaptureState(last_result="DISCARDED")
            return self._state

    def commit_started(self, callsign: str) -> CallsignCaptureState:
        """Preserve a matching pending callsign while durable storage runs."""
        with self._lock:
            if self._capturing or self._state.pending_callsign != callsign:
                return self._state
            self._state = CallsignCaptureState(
                pending_callsign=callsign,
                voice_state="READY",
                commit_state="COMMITTING",
                last_result="COMMITTING",
            )
            return self._state

    def commit_succeeded(self, callsign: str) -> CallsignCaptureState:
        """Clear a matching pending callsign after durable storage succeeds."""
        with self._lock:
            if self._state.pending_callsign != callsign:
                return self._state
            self._state = CallsignCaptureState(last_result=f"COMMITTED {callsign}")
            return self._state

    def commit_failed(self, message: str) -> CallsignCaptureState:
        """Preserve pending callsign and restore Commit after a write failure."""
        del message
        with self._lock:
            if not self._state.pending_callsign:
                return self._state
            self._state = CallsignCaptureState(
                pending_callsign=self._state.pending_callsign,
                voice_state="READY",
                commit_state="READY",
                last_result="LOG ERROR",
            )
            return self._state
