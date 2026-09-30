"""Checkpoint 6 boundary for explicit, supervised FT8 hardware tests.

The physical executor contract is intentionally distinct from
`DigitalTransmitSession`, which remains the hardware-independent sink used by
`FT8QsoController`. Nothing in this module grants the QSO controller, UI,
voice, network, or spot activity transmit authority.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock, Timer
from typing import Protocol

from rolling_thunder.domain import RadioConnectionState, RadioState
from rolling_thunder.ft8.audio_output import FT8AudioOutput
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
        if not math.isfinite(self.maximum_key_down_s) or self.maximum_key_down_s <= 0:
            raise ValueError("maximum_key_down_s must be finite and positive")
        if self.maximum_key_down_s > 20.0:
            raise ValueError("maximum_key_down_s must not exceed 20 seconds")
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


class FT8TestPtt(Protocol):
    """Narrow PTT capability used only by the CP6 owner-test executor."""

    def key(self) -> None:
        """Assert the selected physical PTT mechanism."""
        ...

    def release(self) -> None:
        """Return the radio to receive."""
        ...

    def cancel(self) -> None:
        """Cancel any active keying."""
        ...

    def close(self) -> None:
        """Release and close the capability."""
        ...


class FT8TestRadio(Protocol):
    """Minimum concrete-radio surface needed by the CP6 owner test."""

    def refresh_state(self) -> RadioState:
        """Read the current physical frequency and mode."""
        ...

    def create_cp6_cat_ptt_capability(self) -> FT8TestPtt:
        """Return the already-validated CP6 CAT PTT capability."""
        ...


class WatchdogTimer(Protocol):
    """Cancelable watchdog timer boundary used for deterministic tests."""

    def start(self) -> None:
        """Start the watchdog."""
        ...

    def cancel(self) -> None:
        """Cancel the watchdog."""
        ...


WatchdogFactory = Callable[[float, Callable[[], None]], WatchdogTimer]


def _threading_watchdog(delay_s: float, callback: Callable[[], None]) -> WatchdogTimer:
    timer = Timer(delay_s, callback)
    timer.daemon = True
    return timer


class BoundedFT8HardwareTransmitExecutor:
    """Supervised CP6 executor combining verified CAT PTT and left-only audio."""

    def __init__(
        self,
        radio: FT8TestRadio,
        audio_output: FT8AudioOutput,
        *,
        watchdog_factory: WatchdogFactory = _threading_watchdog,
    ) -> None:
        self._radio = radio
        self._audio_output = audio_output
        self._ptt = radio.create_cp6_cat_ptt_capability()
        self._watchdog_factory = watchdog_factory
        self._lock = Lock()
        self._active = False
        self._closed = False

    def execute_test(self, request: FT8HardwareTestRequest) -> None:
        with self._lock:
            if self._closed:
                raise RuntimeError("FT8 hardware test executor is closed")
            if self._active:
                raise RuntimeError("FT8 hardware test is already active")
            self._active = True

        watchdog: WatchdogTimer | None = None
        try:
            self._verify_radio(request)
            self._ptt.key()
            watchdog = self._watchdog_factory(
                request.maximum_key_down_s,
                self._ptt.release,
            )
            watchdog.start()
            self._audio_output.play(request.waveform)
        finally:
            if watchdog is not None:
                watchdog.cancel()
            try:
                self._ptt.release()
            finally:
                with self._lock:
                    self._active = False

    def cancel_test(self) -> None:
        """Force receive even when no test is currently active."""
        self._ptt.cancel()

    def close(self) -> None:
        """Force receive and permanently close the owner-test executor."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._ptt.close()

    def _verify_radio(self, request: FT8HardwareTestRequest) -> None:
        state = self._radio.refresh_state()
        if state.connection_state is not RadioConnectionState.CONNECTED:
            raise RuntimeError("FT8 hardware test requires a connected radio")
        if state.transmitting:
            raise RuntimeError("FT8 hardware test requires the radio to be in receive")
        if state.frequency is None or state.frequency.hz != request.expected_radio_frequency_hz:
            actual = None if state.frequency is None else state.frequency.hz
            raise RuntimeError(
                "FT8 hardware test frequency mismatch: "
                f"expected {request.expected_radio_frequency_hz} Hz, got {actual}"
            )
        expected_mode = request.expected_radio_mode.strip().upper()
        actual_mode = None if state.mode is None else state.mode.value
        if actual_mode != expected_mode:
            raise RuntimeError(
                "FT8 hardware test mode mismatch: "
                f"expected {expected_mode}, got {actual_mode}"
            )


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
