"""Checkpoint 7 production FT8 transmit-session bridge.

This module connects one already-authorized hardware-independent QSO request to
the separately bounded physical FT8 executor. It never selects a station and it
never exposes a general-purpose PTT capability.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC

from rolling_thunder.ft8.domain import FT8_PERIOD_SECONDS, FT8QsoContext
from rolling_thunder.ft8.encoder import FT8Encoder, FT8Waveform, message_from_transmit_request
from rolling_thunder.ft8.hardware_transmit import (
    FT8QsoHardwareTransmitAuthorization,
    FT8QsoHardwareTransmitExecutor,
    FT8QsoHardwareTransmitRequest,
)
from rolling_thunder.ft8.timing import FT8Clock
from rolling_thunder.ft8.transmit import DigitalTransmitSession, FT8TransmitRequest

FT8_QSO_REQUIRED_RADIO_MODE = "DATA"
FT8_TX_RELEASE_MARGIN_S = 0.20


class FT8QsoTransmitError(RuntimeError):
    """Fail-closed error from the Checkpoint 7 physical QSO transmit bridge."""


@dataclass(frozen=True, slots=True)
class FT8QsoSessionAuthorization:
    """Identity for one explicitly operator-authorized QSO execution."""

    authorization_id: str
    context: FT8QsoContext

    def __post_init__(self) -> None:
        if not self.authorization_id.strip():
            raise ValueError("authorization_id must not be blank")


class HardwareDigitalTransmitSession(DigitalTransmitSession):
    """Execute only logical requests belonging to one frozen QSO context."""

    def __init__(
        self,
        authorization: FT8QsoSessionAuthorization,
        encoder: FT8Encoder,
        executor: FT8QsoHardwareTransmitExecutor,
        clock: FT8Clock,
        *,
        release_margin_s: float = FT8_TX_RELEASE_MARGIN_S,
    ) -> None:
        if release_margin_s <= 0 or release_margin_s >= FT8_PERIOD_SECONDS:
            raise ValueError("release_margin_s must be within the FT8 period")
        self._authorization = authorization
        self._encoder = encoder
        self._executor = executor
        self._clock = clock
        self._release_margin_s = release_margin_s
        self._cancelled = False

    def request(self, request: FT8TransmitRequest) -> None:
        """Encode and execute exactly one already-authorized QSO message."""
        if self._cancelled:
            raise FT8QsoTransmitError("FT8 QSO transmit session is cancelled")
        if request.context != self._authorization.context:
            raise FT8QsoTransmitError("transmit request does not match authorized QSO context")

        context = request.context
        if context.radio_mode.strip().upper() != FT8_QSO_REQUIRED_RADIO_MODE:
            raise FT8QsoTransmitError(
                f"FT8 QSO transmit requires {FT8_QSO_REQUIRED_RADIO_MODE} mode"
            )

        message = message_from_transmit_request(request)
        try:
            waveform = self._encoder.encode(
                message,
                base_frequency_hz=context.target_audio_frequency_hz,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            raise FT8QsoTransmitError(f"FT8 encoder failed: {exc}") from exc

        maximum_key_down_s = self._remaining_safe_key_down(request, waveform)
        hardware_authorization = FT8QsoHardwareTransmitAuthorization(
            authorization_id=self._authorization.authorization_id,
            authorized_at_utc=context.authorized_utc,
            context=context,
        )
        hardware_request = FT8QsoHardwareTransmitRequest(
            authorization=hardware_authorization,
            waveform=waveform,
            maximum_key_down_s=maximum_key_down_s,
            expected_radio_frequency_hz=context.radio_frequency_hz,
            expected_radio_mode=FT8_QSO_REQUIRED_RADIO_MODE,
        )
        try:
            self._executor.execute_qso(hardware_request)
        except (OSError, RuntimeError, ValueError) as exc:
            raise FT8QsoTransmitError(f"FT8 physical transmit failed: {exc}") from exc

    def cancel(self) -> None:
        """Idempotently revoke this QSO's physical transmit authority."""
        if self._cancelled:
            return
        self._cancelled = True
        self._executor.cancel_qso()

    def _remaining_safe_key_down(
        self,
        request: FT8TransmitRequest,
        waveform: FT8Waveform,
    ) -> float:
        now = self._clock.now_utc().astimezone(UTC)
        if self._clock.current_period() != request.period:
            raise FT8QsoTransmitError("authorized FT8 transmit period is no longer current")

        elapsed_s = (now - request.period.start_utc).total_seconds()
        if elapsed_s < 0:
            raise FT8QsoTransmitError("system UTC is before the authorized FT8 period")

        active_end_s = _last_nonzero_sample_end_s(waveform)
        if active_end_s <= 0:
            raise FT8QsoTransmitError("FT8 waveform contains no transmit-bearing samples")
        latest_safe_start_s = FT8_PERIOD_SECONDS - active_end_s - self._release_margin_s
        if elapsed_s > latest_safe_start_s:
            raise FT8QsoTransmitError(
                "safe FT8 transmit start window has been missed "
                f"(elapsed={elapsed_s:.3f}s cutoff={latest_safe_start_s:.3f}s)"
            )

        remaining_s = FT8_PERIOD_SECONDS - elapsed_s - self._release_margin_s
        if remaining_s <= 0:
            raise FT8QsoTransmitError("no safe FT8 key-down time remains in this period")
        return remaining_s


def _last_nonzero_sample_end_s(waveform: FT8Waveform) -> float:
    """Return elapsed seconds through the final non-zero mono PCM sample.

    The encoder's 15-second reference waveform remains untouched. Runtime slot
    safety is derived from its actual RF-bearing sample extent instead of
    truncating or rewriting the validated reference PCM.
    """
    pcm = waveform.pcm_s16le
    last_nonzero_sample = -1
    for offset in range(0, len(pcm), 2):
        if pcm[offset : offset + 2] != b"\x00\x00":
            last_nonzero_sample = offset // 2
    if last_nonzero_sample < 0:
        return 0.0
    return (last_nonzero_sample + 1) / waveform.sample_rate_hz
