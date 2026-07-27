"""Deterministic ranking for immutable POTA spot snapshots."""

from dataclasses import dataclass
from datetime import UTC, datetime

from rolling_thunder.domain import RadioMode
from rolling_thunder.pota_spots import AmateurBand, PotaSpot, frequency_band


@dataclass(frozen=True)
class PotaSpotRankingCriteria:
    """Explicit ranking preferences evaluated against one reference time."""

    reference_time: datetime
    preferred_band: AmateurBand | None = None
    preferred_mode: RadioMode | None = None

    def __post_init__(self) -> None:
        if self.reference_time.tzinfo is None or self.reference_time.utcoffset() is None:
            raise ValueError("POTA ranking reference time must include timezone information.")


@dataclass(frozen=True)
class RankedPotaSpot:
    """One ranked spot with transparent ranking facts."""

    spot: PotaSpot
    source_index: int
    band_match: bool
    mode_match: bool
    age_seconds: int


def rank_pota_spots(
    spots: list[PotaSpot],
    criteria: PotaSpotRankingCriteria,
) -> tuple[RankedPotaSpot, ...]:
    """Rank spots predictably without mutating input or performing I/O."""
    reference_time = criteria.reference_time.astimezone(UTC)
    ranked = tuple(
        RankedPotaSpot(
            spot=spot,
            source_index=index,
            band_match=(
                criteria.preferred_band is not None
                and frequency_band(spot.frequency) is criteria.preferred_band
            ),
            mode_match=(
                criteria.preferred_mode is not None
                and spot.mode is criteria.preferred_mode
            ),
            age_seconds=max(
                0,
                int((reference_time - spot.spotted_at.astimezone(UTC)).total_seconds()),
            ),
        )
        for index, spot in enumerate(spots)
    )
    return tuple(
        sorted(
            ranked,
            key=lambda item: (
                not item.band_match,
                not item.mode_match,
                -item.spot.spotted_at.timestamp(),
                item.source_index,
            ),
        )
    )
