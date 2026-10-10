"""Conservative, recommendation-only FT8 power policy.

No CAT/PTT imports: callers must never interpret recommendations as permission
to change RF settings. Empirical input is advisory, not RF-exposure validation.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from statistics import median

from pydantic import BaseModel, ConfigDict, Field, field_validator

_DEFAULT_MAX_AUTO_WATTS = {"10m": 30, "12m": 40, "15m": 40}


class FT8PowerPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    initial_power_watts: int = Field(default=20, ge=5, le=100, multiple_of=5)
    adaptive_enabled: bool = False
    max_auto_watts_by_band: dict[str, int] = Field(
        default_factory=lambda: dict(_DEFAULT_MAX_AUTO_WATTS)
    )
    default_max_auto_watts: int = Field(default=70, ge=5, le=100, multiple_of=5)

    @field_validator("max_auto_watts_by_band")
    @classmethod
    def validate_caps(cls, caps: dict[str, int]) -> dict[str, int]:
        for band, cap in caps.items():
            if not band or not band.endswith("m"):
                raise ValueError(f"unsupported band key: {band}")
            if isinstance(cap, bool) or not 5 <= cap <= 100 or cap % 5:
                raise ValueError(f"invalid automatic ceiling for {band}")
        return caps

    def limit_for(self, band: str | None) -> int:
        # Unknown band cannot bypass the strictest configured safety ceiling.
        if band is None:
            return min(self.default_max_auto_watts, *_DEFAULT_MAX_AUTO_WATTS.values(), *self.max_auto_watts_by_band.values())
        configured = self.max_auto_watts_by_band.get(band.lower(), self.default_max_auto_watts)
        fixed_ceiling = _DEFAULT_MAX_AUTO_WATTS.get(band.lower())
        return min(configured, fixed_ceiling) if fixed_ceiling is not None else configured

    def clamp(self, band: str | None, proposed_watts: int) -> int:
        return min(max(5, proposed_watts), self.limit_for(band))


@dataclass(frozen=True)
class FT8PowerObservation:
    received_at_utc: datetime
    band: str
    receiver_callsign: str
    snr_db: int
    verified_tx_power_watts: int | None = None


@dataclass(frozen=True)
class FT8PowerAdvice:
    watts: int
    evidence_receivers: int
    explanation: str
    advisory_only: bool = True


def recommend_power(
    policy: FT8PowerPolicy,
    *,
    band: str | None,
    at_utc: datetime,
    reports: tuple[FT8PowerObservation, ...] = (),
    manual_override_active: bool = False,
) -> FT8PowerAdvice:
    """Evidence must be same UTC day, band, and have verified TX power.

    Return only an advisory. Missing/weak evidence reverts to 20 W; do not
    increase solely because few stations are hearing the signal.
    """
    if at_utc.tzinfo is None or at_utc.utcoffset() is None:
        raise ValueError("at_utc must have a timezone")
    baseline = policy.clamp(band, policy.initial_power_watts)
    if manual_override_active:
        return FT8PowerAdvice(baseline, 0, "Manual radio control active: advisory suspended")
    if not policy.adaptive_enabled or band is None:
        return FT8PowerAdvice(baseline, 0, "Adaptive advisor disabled or band unknown")
    today = at_utc.astimezone(UTC).date()
    current: dict[str, FT8PowerObservation] = {}
    for report in reports:
        if report.received_at_utc.tzinfo is None:
            continue
        if report.band.lower() != band.lower() or report.received_at_utc.astimezone(UTC).date() != today:
            continue
        if report.received_at_utc > at_utc or report.verified_tx_power_watts is None:
            continue
        if report.verified_tx_power_watts != baseline:
            # Comparing SNR across different powers without adjustment is misleading.
            continue
        key = report.receiver_callsign.strip().upper()
        if not key:
            continue
        if key not in current or current[key].received_at_utc < report.received_at_utc:
            current[key] = report
    if len(current) < 3:
        return FT8PowerAdvice(baseline, len(current), "Insufficient independent current-day observations")
    typical_snr = median(r.snr_db for r in current.values())
    if typical_snr >= 7:
        return FT8PowerAdvice(policy.clamp(band, baseline - 5), len(current),
                              "Strong same-day reports: consider a 5 W reduction")
    # No automatic increase from weak observations without target/path context.
    return FT8PowerAdvice(baseline, len(current), "Hold baseline; reception margin uncertain")
