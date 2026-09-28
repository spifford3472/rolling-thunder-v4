"""Background push-to-listen callsign capture state."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock, Thread

from rolling_thunder.callsign_capture import CallsignCaptureState
from rolling_thunder.phonetic_callsign import parse_phonetic_callsign
from rolling_thunder.speech_recognition import SpeechRecognitionError, SpeechRecognizer


@dataclass(frozen=True)
class LiveCaptureStatus:
    """Observable live-capture status for UI polling."""

    state: CallsignCaptureState
    capturing: bool


class LiveCallsignCaptureController:
    """Run one microphone capture at a time without blocking the UI thread."""

    def __init__(self, recognizer: SpeechRecognizer) -> None:
        self._recognizer = recognizer
        self._lock = Lock()
        self._state = CallsignCaptureState()
        self._capturing = False

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
        """Start one daemon capture worker, returning false when already active."""
        with self._lock:
            if self._capturing or self._state.commit_state == "COMMITTING":
                return False
            self._capturing = True
            self._state = CallsignCaptureState(
                voice_state="LISTENING",
                commit_state="DISABLED",
                last_result="LISTENING",
            )

        Thread(target=self._capture_worker, daemon=True).start()
        return True

    def _capture_worker(self) -> None:
        try:
            tokens = self._recognizer.capture_tokens()
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
        except SpeechRecognitionError:
            new_state = CallsignCaptureState(
                voice_state="FAILED",
                commit_state="DISABLED",
                last_result="MIC ERROR",
            )

        with self._lock:
            self._state = new_state
            self._capturing = False

    def preload_callsign(self, callsign: str) -> bool:
        """Preload one selected spot callsign unless capture or Commit owns the state."""
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
            self._state = CallsignCaptureState(
                last_result=f"COMMITTED {callsign}",
            )
            return self._state

    def commit_failed(self, message: str) -> CallsignCaptureState:
        """Preserve the pending callsign and restore Commit after a write failure."""
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
