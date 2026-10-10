"""Future FT8 pre-QSO propagation sources: inert, typed input contracts.

No provider, transmission, or weighting logic is wired to these types yet.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum


class ForecastSource(StrEnum):
    VOACAP = "voacap"
    SPACE_WEATHER = "space_weather"


class ForecastState(StrEnum):
    UNAVAILABLE = "unavailable"
    STALE = "stale"
    AVAILABLE = "available"


@dataclass(frozen=True)
class PropagationForecast:
    """Optional snapshot metadata; no asserted calibrated reachability.

    A provider can expose a forecast after provenance, validity window,
    location, band, and direction are verified. Never treat missing data
    as evidence of path failure.
    """
    source: ForecastSource
    state: ForecastState = ForecastState.UNAVAILABLE
    observed_at_utc: datetime | None = None
    valid_until_utc: datetime | None = None
    source_version: str | None = None

    def __post_init__(self) -> None:
        for timestamp in (self.observed_at_utc, self.valid_until_utc):
            if timestamp is not None and timestamp.utcoffset() is None:
                raise ValueError("forecast timestamps must be timezone-aware")
        if self.state is ForecastState.AVAILABLE and (
            self.observed_at_utc is None or self.valid_until_utc is None
        ):
            raise ValueError("available forecast requires a validity window")
        if (
            self.observed_at_utc is not None
            and self.valid_until_utc is not None
            and self.valid_until_utc < self.observed_at_utc
        ):
            raise ValueError("forecast valid_until precedes observation")

    def usable_at(self, at_utc: datetime) -> bool:
        """Validity metadata only; not permission to affect CQ scoring."""
        if at_utc.utcoffset() is None:
            raise ValueError("at_utc must be timezone-aware")
        return (
            self.state is ForecastState.AVAILABLE
            and self.observed_at_utc is not None
            and self.valid_until_utc is not None
            and self.observed_at_utc.astimezone(UTC) <= at_utc.astimezone(UTC)
            <= self.valid_until_utc.astimezone(UTC)
        )


@dataclass(frozen=True)
class FuturePropagationInputs:
    """Explicit optional extension slot; both sources default to unavailable."""

    voacap: PropagationForecast = PropagationForecast(ForecastSource.VOACAP)
    space_weather: PropagationForecast = PropagationForecast(ForecastSource.SPACE_WEATHER)

    def __post_init__(self) -> None:
        if self.voacap.source is not ForecastSource.VOACAP:
            raise ValueError("voacap slot requires VOACAP source")
        if self.space_weather.source is not ForecastSource.SPACE_WEATHER:
            raise ValueError("space_weather slot requires space-weather source")
