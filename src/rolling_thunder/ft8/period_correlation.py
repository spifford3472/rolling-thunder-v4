"""Conservative time/frequency attribution of PSK receptions to actual FT8 periods."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from rolling_thunder.ft8.hardware_transmit import FT8TransmitPeriodTelemetry


@dataclass(frozen=True)
class FT8ReceptionObservation:
    observed_at_utc: datetime
    dial_frequency_hz: int
    receiver_callsign: str
    audio_offset_hz: int | None = None
    frequency_is_rf: bool = False


@dataclass(frozen=True)
class FT8PeriodAttribution:
    transmission: FT8TransmitPeriodTelemetry | None
    reason: str


def attribute_reception(
    reception: FT8ReceptionObservation,
    transmissions: tuple[FT8TransmitPeriodTelemetry, ...],
    *,
    tolerance_seconds: int = 3,
    rf_tolerance_hz: int = 10,
) -> FT8PeriodAttribution:
    """Attribute only a unique overlapping period; otherwise preserve uncertainty.

    Dial observations match dial exactly. RF observations match a persisted
    transmit-side waveform offset with bounded frequency tolerance. Unknown
    offsets and ambiguous windows are not training evidence.
    """
    if reception.observed_at_utc.tzinfo is None:
        raise ValueError("reception timestamps require timezone")
    if not 0 <= tolerance_seconds <= 10:
        raise ValueError("tolerance_seconds must be between 0 and 10")
    if not 0 <= rf_tolerance_hz <= 100:
        raise ValueError("rf_tolerance_hz must be between 0 and 100")
    if type(reception.dial_frequency_hz) is not int or reception.dial_frequency_hz <= 0:
        return FT8PeriodAttribution(None, "invalid_reception_frequency")
    if reception.frequency_is_rf and reception.audio_offset_hz is not None:
        return FT8PeriodAttribution(None, "receiver_offset_not_trusted")
    candidates = []
    margin = timedelta(seconds=tolerance_seconds)
    for record in transmissions:
        if not record.transmitted or record.started_at_utc.tzinfo is None:
            continue
        if reception.frequency_is_rf:
            offset = record.transmit_audio_offset_hz
            if offset is None or not 200 <= offset <= 3500:
                continue
            if abs(record.frequency_hz + offset - reception.dial_frequency_hz) > rf_tolerance_hz:
                continue
        elif record.frequency_hz != reception.dial_frequency_hz:
            continue
        if record.started_at_utc - margin <= reception.observed_at_utc <= record.ended_at_utc + margin:
            candidates.append(record)
    if len(candidates) != 1:
        if candidates:
            return FT8PeriodAttribution(None, "ambiguous")
        if reception.frequency_is_rf and any(
            record.transmit_audio_offset_hz is None for record in transmissions
        ):
            return FT8PeriodAttribution(None, "missing_transmit_audio_offset")
        return FT8PeriodAttribution(None, "no_matching_period")
    record = candidates[0]
    if not record.power_readback_verified:
        return FT8PeriodAttribution(None, "power_unverified")
    return FT8PeriodAttribution(record, "unique_period_verified_setting")
