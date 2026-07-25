"""Application state for deterministic mock callsign capture."""

from dataclasses import dataclass
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
        self._state = CallsignCaptureState()

    @property
    def state(self) -> CallsignCaptureState:
        """Return the latest immutable capture state."""
        return self._state

    def capture_next(self) -> CallsignCaptureState:
        """Parse the next mock transcript and expose a committable result when valid."""
        transcript = self._transcripts[self._next_index]
        self._next_index = (self._next_index + 1) % len(self._transcripts)
        result = parse_phonetic_callsign(transcript)

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

    def discard(self) -> CallsignCaptureState:
        """Clear the pending result without logging anything."""
        self._state = CallsignCaptureState(last_result="DISCARDED")
        return self._state
