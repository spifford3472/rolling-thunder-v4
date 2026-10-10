"""Pure, offline FT8 CQ ranking advice. Never controls the radio or starts QSOs.

Evidence is supplied by a caller: no external data fetch occurs here.
Scores are relative priorities, NOT probabilities of completing a QSO.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from math import log1p

from rolling_thunder.ft8.distance import maidenhead_distance_km

MODEL_VERSION = 1
_EVIDENCE_MAX_AGE_SECONDS = 1800


@dataclass(frozen=True)
class ReachabilityEvidence:
    """Directional, independently derived prior for *our TX reaching the target*.

    quality is a calibrated-or-expert-estimated 0..1 score, not a QSO probability.
    Sample count and age temper influence. Do not populate with reversed-direction
    PSK reports without an explicit inference method.
    """
    quality: float
    observed_at_utc: datetime
    independent_receivers: int

    def __post_init__(self) -> None:
        if not 0 <= self.quality <= 1:
            raise ValueError("quality must lie between 0 and 1")
        if self.independent_receivers < 0:
            raise ValueError("independent_receivers must be nonnegative")
        if self.observed_at_utc.utcoffset() is None:
            raise ValueError("observed_at_utc must be timezone-aware")


@dataclass(frozen=True)
class CQCandidate:
    callsign: str
    grid: str | None
    snr_db: int | None
    reachability: ReachabilityEvidence | None = None


@dataclass(frozen=True)
class RankedCQ:
    callsign: str
    score: float
    distance_km: float | None
    confidence: str
    reason: str
    model_version: int = MODEL_VERSION


def score_cq(
    candidate: CQCandidate,
    *,
    local_grid: str | None,
    now_utc: datetime,
) -> RankedCQ:
    """Rank DX opportunity balanced with cautious, age-weighted evidence.

    A high RX SNR alone is *not* proof of the reciprocal TX path. On missing
    metadata, give a neutral opportunity rather than assuming band closure.
    """
    if now_utc.utcoffset() is None:
        raise ValueError("now_utc must be timezone-aware")
    distance: float | None = None
    if local_grid and candidate.grid:
        try:
            distance = maidenhead_distance_km(local_grid, candidate.grid)
        except ValueError:
            pass
    # Saturating DX value keeps very long, unreliable paths from dominating.
    dx = min(1.0, log1p(distance / 800.0) / log1p(16000.0 / 800.0)) if distance is not None else 0.35
    # RX SNR is weakly informative about ability to decode the station locally.
    rx = 0.5 if candidate.snr_db is None else max(0.0, min(1.0, (candidate.snr_db + 24) / 44))
    signal = 0.5 + 0.15 * (rx - 0.5)

    evidence = candidate.reachability
    fresh = False
    if evidence is not None:
        age = (now_utc.astimezone(UTC) - evidence.observed_at_utc.astimezone(UTC)).total_seconds()
        fresh = 0 <= age <= _EVIDENCE_MAX_AGE_SECONDS and evidence.independent_receivers > 0
    if fresh and evidence is not None:
        age_weight = 1 - age / (_EVIDENCE_MAX_AGE_SECONDS * 2)
        coverage = min(1.0, evidence.independent_receivers / 4)
        reach = 0.5 + (evidence.quality - 0.5) * coverage * age_weight
    else:
        reach = 0.5

    # DX preference only applies to plausible reachability, with neutral
    # baseline for unknown conditions. This is an ordinal priority score.
    score = 100 * (0.48 * dx + 0.42 * reach + 0.10 * signal)
    confidence = (
        "high" if fresh and evidence is not None and evidence.independent_receivers >= 4 and distance is not None
        else "medium" if (fresh and distance is not None) or (distance is not None and candidate.snr_db is not None)
        else "low"
    )
    reason = (
        "recent directional reception evidence"
        if fresh else "reachability unverified; neutral prior"
    )
    if distance is None:
        reason += "; distance unavailable"
    return RankedCQ(candidate.callsign, round(score, 3), distance, confidence, reason)


def rank_cqs(
    candidates: tuple[CQCandidate, ...],
    *,
    local_grid: str | None,
    now_utc: datetime,
) -> tuple[RankedCQ, ...]:
    """Stable input-order ties; doesn't mutate upstream CQ selection state."""
    ranked = [score_cq(item, local_grid=local_grid, now_utc=now_utc) for item in candidates]
    return tuple(sorted(ranked, key=lambda item: -item.score))
