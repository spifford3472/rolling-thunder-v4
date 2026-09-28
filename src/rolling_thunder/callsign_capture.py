"""Application state for deterministic mock callsign capture."""

from dataclasses import dataclass
from threading import Lock
from typing import Final

from rolling_thunder.phonetic_callsign import parse_phonetic_callsign

_DEFAULT_TRANSCRIPTS: Final[tuple[tuple[str, ...], ...]] = (
    ("KILO", "INDIA", "FIVE", "VICTOR", "NOVEMBER", "BRAVO"),
    ("GOLF", "BRAVO", "NINER", "ZERO", "MIKE", "GOLF", "YANKEE"),
    (
        "KILO",
        "INDIA",
        "FIVE",
        "VICTOR",
        "NOVEMBER",
        "BRAVO",
        "SLASH",
        "VICTOR",
        "ECHO",
        "SIX",
    ),
    ("KILO", "INDIA", "FIVE", "UNKNOWN", "NOVEMBER", "BRAVO"),
)


@dataclass(frozen=True)
class CallsignCaptureState:
    """UI-facing callsign capture state independent of speech hardware."""

    pending_callsign: str = ""
    voice_state: str = "READY"
    commit_state: str = "DISABLED"
    last_result: str = "—"


class MockTranscriptController:
    """Cycle deterministic transcript fixtures through the callsign parser."""

    def __init__(
        self,
        transcripts: tuple[tuple[str, ...], ...] = _DEFAULT_TRANSCRIPTS,
    ) -> None:
        if not transcripts:
            raise ValueError("At least one mock transcript is required.")
        self._transcripts = transcripts
        self._next_index = 0
        self._lock = Lock()
        self._state = CallsignCaptureState()

    @property
    def state(self) -> CallsignCaptureState:
        """Return the latest immutable capture state."""
        with self._lock:
            return self._state

    def start_capture(self) -> bool:
        """Advance one deterministic fixture through the shared capture command."""
        self.capture_next()
        return True

    def capture_next(self) -> CallsignCaptureState:
        """Parse the next mock transcript and expose a committable result when valid."""
        with self._lock:
            transcript = self._transcripts[self._next_index]
            self._next_index = (self._next_index + 1) % len(self._transcripts)
        result = parse_phonetic_callsign(transcript)

        with self._lock:
            if result.is_valid and result.callsign is not None:
                self._state = CallsignCaptureState(
                    pending_callsign=result.callsign,
                    voice_state="READY",
                    commit_state="READY",
                    last_result=f"HEARD {result.callsign}",
                )
            else:
                self._state = CallsignCaptureState(
                    voice_state="FAILED",
                    commit_state="DISABLED",
                    last_result="VOICE ERROR",
                )
            return self._state

    def preload_callsign(self, callsign: str) -> bool:
        """Preload one selected spot callsign without preventing later voice replacement."""
        normalized = callsign.strip().upper()
        if not normalized:
            return False
        with self._lock:
            if self._state.commit_state == "COMMITTING":
                return False
            self._state = CallsignCaptureState(
                pending_callsign=normalized,
                voice_state="READY",
                commit_state="READY",
                last_result=f"SELECTED {normalized}",
            )
            return True

    def discard(self) -> CallsignCaptureState:
        """Clear the pending result without logging anything."""
        with self._lock:
            if self._state.commit_state == "COMMITTING":
                return self._state
            self._state = CallsignCaptureState(last_result="DISCARDED")
            return self._state

    def commit_started(self, callsign: str) -> CallsignCaptureState:
        """Preserve a matching pending callsign while durable storage runs."""
        with self._lock:
            if self._state.pending_callsign != callsign:
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
                voice_state="READY",
                commit_state="DISABLED",
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
