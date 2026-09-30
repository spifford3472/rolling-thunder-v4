"""Hardware-free Checkpoint 6 boundary for explicit FT8 hardware tests.

This module defines no serial, CAT, audio-device, PTT, worker, or RF adapter.
The physical executor contract is intentionally distinct from
`DigitalTransmitSession`, which remains the hardware-independent sink used by
`FT8QsoController`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from rolling_thunder.ft8.encoder import FT8_SAMPLE_RATE_HZ, FT8Waveform


@dataclass(frozen=True, slots=True)
class FT8HardwareTestAuthorization:
    """One explicit owner authorization for a supervised hardware test."""

    authorization_id: str
    approved_at_utc: datetime

    def __post_init__(self) -> None:
        if not self.authorization_id.strip():
            raise ValueError("authorization_id must not be blank")
        if self.approved_at_utc.tzinfo is None or self.approved_at_utc.utcoffset() is None:
            raise ValueError("approved_at_utc must be timezone-aware")
        object.__setattr__(self, "approved_at_utc", self.approved_at_utc.astimezone(UTC))


@dataclass(frozen=True, slots=True)
class FT8HardwareTestRequest:
    """One bounded, already-prepared, explicitly authorized hardware test."""

    authorization: FT8HardwareTestAuthorization
    waveform: FT8Waveform
    maximum_key_down_s: float
    expected_radio_frequency_hz: int
    expected_radio_mode: str

    def __post_init__(self) -> None:
        if self.maximum_key_down_s <= 0:
            raise ValueError("maximum_key_down_s must be positive")
        if self.expected_radio_frequency_hz <= 0:
            raise ValueError("expected_radio_frequency_hz must be positive")
        if not self.expected_radio_mode.strip():
            raise ValueError("expected_radio_mode must not be blank")
        if self.waveform.sample_rate_hz != FT8_SAMPLE_RATE_HZ:
            raise ValueError("hardware-test waveform must use the FT8 12000 Hz sample rate")
        if not self.waveform.pcm_s16le:
            raise ValueError("hardware-test waveform PCM must not be empty")


class FT8HardwareTransmitExecutor(Protocol):
    """Separate owner-test capability; never the QSO controller session port."""

    def execute_test(self, request: FT8HardwareTestRequest) -> None:
        """Execute one already-authorized supervised hardware test."""
        ...

    def cancel_test(self) -> None:
        """Cancel the active owner test if one exists."""
        ...

    def close(self) -> None:
        """Release executor resources without creating another test."""
        ...


class RecordingFT8HardwareTransmitExecutor:
    """Hardware-free fake for Checkpoint 6 architecture and application tests."""

    def __init__(self) -> None:
        self.requests: list[FT8HardwareTestRequest] = []
        self.cancel_count = 0
        self.close_count = 0

    def execute_test(self, request: FT8HardwareTestRequest) -> None:
        self.requests.append(request)

    def cancel_test(self) -> None:
        self.cancel_count += 1

    def close(self) -> None:
        self.close_count += 1
