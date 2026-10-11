"""Pure VOACAP historical comparisons; no provider I/O or live transmit control.

Only compare forecasts that were issued before the valid time and used
identical path/model/equipment assumptions. Never treat hindcasts as live data.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

_LOCAL = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class ForecastPoint:
    """Normalized, immutable forecast row for longitudinal comparisons."""

    issued_at_utc: datetime
    valid_at_utc: datetime
    model_version: str
    path_identity: str
    equipment_identity: str
    band: str
    reliability: float | None
    predicted_snr_db: float | None

    def __post_init__(self) -> None:
        for time in (self.issued_at_utc, self.valid_at_utc):
            if time.tzinfo is None or time.utcoffset() is None:
                raise ValueError("forecast timestamps must be timezone-aware")
        if self.reliability is not None and not 0 <= self.reliability <= 1:
            raise ValueError("reliability must be a normalized fraction")


@dataclass(frozen=True)
class ForecastDelta:
    status: str
    snr_change_db: float | None = None
    reliability_change: float | None = None


def compare_previous_local_day(today: ForecastPoint, history: list[ForecastPoint]) -> ForecastDelta:
    """Compare same NY wall-clock hour yesterday, excluding ambiguous DST hours."""
    if today.issued_at_utc >= today.valid_at_utc:
        return ForecastDelta("not_prior_forecast")
    current_local = today.valid_at_utc.astimezone(_LOCAL)
    previous_date = current_local.date() - timedelta(days=1)
    eligible: list[ForecastPoint] = []
    for prior in history:
        if prior.issued_at_utc >= prior.valid_at_utc:
            continue
        if (prior.model_version, prior.path_identity, prior.equipment_identity, prior.band) != (
            today.model_version, today.path_identity, today.equipment_identity, today.band
        ):
            continue
        old_local = prior.valid_at_utc.astimezone(_LOCAL)
        if old_local.date() == previous_date and old_local.hour == current_local.hour:
            eligible.append(prior)
    if not eligible:
        return ForecastDelta("no_comparable_yesterday")
    if len(eligible) != 1:
        return ForecastDelta("ambiguous_dst_or_multiple_forecasts")
    prior = eligible[0]
    if today.predicted_snr_db is None or prior.predicted_snr_db is None:
        snr_delta = None
    else:
        snr_delta = today.predicted_snr_db - prior.predicted_snr_db
    if today.reliability is None or prior.reliability is None:
        reliability_delta = None
    else:
        reliability_delta = today.reliability - prior.reliability
    if snr_delta is None and reliability_delta is None:
        return ForecastDelta("missing_metric")
    return ForecastDelta("comparable", snr_delta, reliability_delta)
