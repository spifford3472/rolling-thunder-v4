"""Narrow fake-only FT8 transmit-session boundary for Checkpoint 2."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from rolling_thunder.ft8.domain import FT8Period, FT8QsoContext


class FT8TransmitKind(StrEnum):
    """Authorized logical message types; no waveform or PTT semantics."""

    CALL = "call"
    REPORT = "report"
    R_REPORT = "r_report"
    SEVENTY_THREE = "73"


@dataclass(frozen=True, slots=True)
class FT8TransmitRequest:
    """One already-authorized logical FT8 transmit request for one exact slot."""

    context: FT8QsoContext
    kind: FT8TransmitKind
    period: FT8Period
    attempt: int

    def __post_init__(self) -> None:
        if self.attempt < 1:
            raise ValueError("attempt must be at least 1")
        if self.period.parity is not self.context.tx_parity:
            raise ValueError("transmit request period must match authorized TX parity")


class DigitalTransmitSession(Protocol):
    """Narrow capability used only after one QSO has been explicitly authorized."""

    def request(self, request: FT8TransmitRequest) -> None:
        """Record/execute exactly one already-authorized logical request."""
        ...

    def cancel(self) -> None:
        """Cancel future activity for the authorized session."""
        ...


class RecordingDigitalTransmitSession:
    """Hardware-free recording fake used by Checkpoint 2 tests."""

    def __init__(self) -> None:
        self.requests: list[FT8TransmitRequest] = []
        self.cancel_count = 0
        self._cancelled = False

    def request(self, request: FT8TransmitRequest) -> None:
        if self._cancelled:
            raise RuntimeError("recording FT8 transmit session is cancelled")
        self.requests.append(request)

    def cancel(self) -> None:
        if self._cancelled:
            return
        self._cancelled = True
        self.cancel_count += 1
