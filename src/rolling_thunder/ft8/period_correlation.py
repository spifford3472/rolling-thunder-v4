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


@dataclass(frozen=True)
class FT8PeriodAttribution:
    transmission: FT8TransmitPeriodTelemetry | None
    reason: str


def attribute_reception(
    reception: FT8ReceptionObservation,
    transmissions: tuple[FT8TransmitPeriodTelemetry, ...],
    *,
    tolerance_seconds: int = 3,
) -> FT8PeriodAttribution:
    """Attribute only a unique overlapping period; otherwise preserve uncertainty.

    Requires a dial-frequency-aligned reception observation, not an FT8 audio
    offset or the absolute signal frequency. Duplicated/ambiguous windows do
    not become training evidence.
    """
    if reception.observed_at_utc.tzinfo is None:
        raise ValueError("reception timestamps require timezone")
    if not 0 <= tolerance_seconds <= 10:
        raise ValueError("tolerance_seconds must be between 0 and 10")
    candidates = []
    margin = timedelta(seconds=tolerance_seconds)
    for record in transmissions:
        if not record.transmitted or record.started_at_utc.tzinfo is None:
            continue
        if record.frequency_hz != reception.dial_frequency_hz:
            continue
        if record.started_at_utc - margin <= reception.observed_at_utc <= record.ended_at_utc + margin:
            candidates.append(record)
    if len(candidates) != 1:
        return FT8PeriodAttribution(None, "ambiguous" if candidates else "no_matching_period")
    record = candidates[0]
    if not record.power_readback_verified:
        return FT8PeriodAttribution(None, "power_unverified")
    return FT8PeriodAttribution(record, "unique_period_verified_setting")
