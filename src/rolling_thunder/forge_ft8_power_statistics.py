"""Conservative, offline holdout statistics for a pre-registered FT8 power trial.

No provider calls, radio control, model fitting, or invented observations.
This computes an intentionally conservative Wilson/Newcombe confidence
bound on the difference in reciprocal-exchange rates (test minus control).
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from rolling_thunder.domain import DomainModel


class TrialOutcome(StrEnum):
    COMPLETED = "completed"
    NO_ANSWER = "no_answer"
    CENSORED_BUSY = "censored_busy"
    ABORTED = "aborted"
    EQUIPMENT_FAULT = "equipment_fault"


class TrialArm(StrEnum):
    CONTROL = "baseline_20w"
    LOWER = "bounded_lower_power"


class QualifiedTrialObservation(DomainModel):
    schema_version: Literal[1] = 1
    attempt_uuid: UUID
    qso_group_id: str = Field(min_length=1, max_length=120)
    callsign_group_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    operating_segment: str = Field(min_length=1, max_length=120)
    choice_at_utc: datetime
    forecast_generated_at_utc: datetime
    forecast_available_at_utc: datetime
    outcome_at_utc: datetime
    forecast_input_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    independent_forecast_family_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    payload_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    assignment_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    model_version: str = Field(min_length=1, max_length=120)
    protocol_version: str = Field(min_length=1, max_length=120)
    arm: TrialArm
    assigned_watts: int = Field(ge=5, le=20)
    power_readback_watts: int | None = Field(default=None, ge=5, le=100)
    outcome: TrialOutcome
    field_observed: bool
    retrospectively_generated: bool = False
    simulated: bool = False
    assigned_before_choice: bool
    selection_probability: float = Field(gt=0, le=1)

    @field_validator(
        "choice_at_utc",
        "forecast_generated_at_utc",
        "forecast_available_at_utc",
        "outcome_at_utc",
    )
    @classmethod
    def normalize_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("prospective trial timestamps must be timezone aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_order_and_power(self) -> Self:
        if self.forecast_generated_at_utc > self.forecast_available_at_utc:
            raise ValueError("forecast available before generated")
        if self.outcome_at_utc < self.choice_at_utc:
            raise ValueError("outcome before operator selection")
        if self.arm is TrialArm.CONTROL and self.assigned_watts != 20:
            raise ValueError("20W control assignment mismatch")
        if self.arm is TrialArm.LOWER and self.assigned_watts >= 20:
            raise ValueError("lower-power arm must be below 20W")
        return self

    @property
    def valid_prospective_source(self) -> bool:
        return (
            self.field_observed
            and not self.simulated
            and not self.retrospectively_generated
            and self.assigned_before_choice
            and self.forecast_available_at_utc <= self.choice_at_utc
        )


class TrialEvaluation(DomainModel):
    schema_version: Literal[1] = 1
    protocol_version: str
    model_version: str
    holdout_start_utc: datetime
    holdout_end_utc: datetime
    control_total: int = Field(ge=0)
    control_completed: int = Field(ge=0)
    lower_total: int = Field(ge=0)
    lower_completed: int = Field(ge=0)
    censored_count: int = Field(ge=0)
    excluded_count: int = Field(ge=0)
    independent_forecast_families: int = Field(ge=0)
    eligible_segments: dict[str, int]
    lower_minus_control_lower_bound: float | None = None
    pre_registered_margin: float
    noninferiority_demonstrated: bool
    reasons: tuple[str, ...]
    shadow_only: Literal[True] = True
    may_transmit: Literal[False] = False
    apply_allowed: Literal[False] = False


def _wilson(successes: int, total: int, *, z: float = 2.241402727604947) -> tuple[float, float]:
    """Conservative two-sided 97.5% per-arm Wilson interval.

    Combining test lower and control upper via Bonferroni yields
    at least 95% joint coverage; no asymptotic normal difference shortcut.
    """
    if total <= 0:
        return (0.0, 1.0)
    p = successes / total
    z2 = z * z
    center = (p + z2 / (2 * total)) / (1 + z2 / total)
    half = z * math.sqrt((p * (1 - p) + z2 / (4 * total)) / total) / (1 + z2 / total)
    return max(0.0, center - half), min(1.0, center + half)


def evaluate_trial_holdout(
    observations: tuple[QualifiedTrialObservation, ...],
    *,
    protocol_version: str,
    model_version: str,
    holdout_start_utc: datetime,
    holdout_end_utc: datetime,
    minimum_per_arm: int = 100,
    minimum_per_segment: int = 100,
    noninferiority_margin: float = 0.05,
) -> TrialEvaluation:
    """Evaluate only prospectively collected real, independent heldout groups.

    Missingness and censored rows are kept in denominators for coverage audit,
    but busy/fault/aborted are NOT silently counted as propagation failures.
    No training or model selection is performed on holdout rows.
    """
    if (
        holdout_start_utc.tzinfo is None or holdout_end_utc.tzinfo is None
        or holdout_start_utc >= holdout_end_utc
    ):
        raise ValueError("holdout requires ordered aware UTC times")
    if not (0 < noninferiority_margin < 0.5):
        raise ValueError("pre-registered noninferiority margin invalid")
    if minimum_per_arm <= 0 or minimum_per_segment <= 0:
        raise ValueError("positive per-arm and segment minima required")
    seen_attempts: set[UUID] = set()
    seen_qso: set[str] = set()
    seen_call_prior: set[str] = {
        observation.callsign_group_sha256
        for observation in observations
        if observation.choice_at_utc < holdout_start_utc
    }
    segments: dict[str, int] = defaultdict(int)
    family: set[str] = set()
    success = {TrialArm.CONTROL: 0, TrialArm.LOWER: 0}
    total = {TrialArm.CONTROL: 0, TrialArm.LOWER: 0}
    censored = 0
    excluded = 0
    for observation in sorted(observations, key=lambda item: (item.choice_at_utc, str(item.attempt_uuid))):
        if observation.attempt_uuid in seen_attempts or observation.qso_group_id in seen_qso:
            excluded += 1
            continue
        seen_attempts.add(observation.attempt_uuid)
        seen_qso.add(observation.qso_group_id)
        if not (holdout_start_utc <= observation.choice_at_utc < holdout_end_utc):
            continue
        if (
            not observation.valid_prospective_source
            or observation.protocol_version != protocol_version
            or observation.model_version != model_version
            or observation.callsign_group_sha256 in seen_call_prior
            or observation.power_readback_watts != observation.assigned_watts
        ):
            excluded += 1
            continue
        if observation.outcome in {
            TrialOutcome.CENSORED_BUSY, TrialOutcome.ABORTED, TrialOutcome.EQUIPMENT_FAULT,
        }:
            censored += 1
            continue
        total[observation.arm] += 1
        success[observation.arm] += int(observation.outcome is TrialOutcome.COMPLETED)
        segments[observation.operating_segment] += 1
        family.add(observation.independent_forecast_family_sha256)
    reasons: list[str] = []
    if total[TrialArm.CONTROL] < minimum_per_arm:
        reasons.append("insufficient_control_arm")
    if total[TrialArm.LOWER] < minimum_per_arm:
        reasons.append("insufficient_lower_arm")
    if not segments or min(segments.values()) < minimum_per_segment:
        reasons.append("operating_segment_not_qualified")
    difference_lower: float | None = None
    if total[TrialArm.CONTROL] and total[TrialArm.LOWER]:
        lower_test, _ = _wilson(success[TrialArm.LOWER], total[TrialArm.LOWER])
        _, upper_control = _wilson(success[TrialArm.CONTROL], total[TrialArm.CONTROL])
        difference_lower = lower_test - upper_control
        if difference_lower < -noninferiority_margin:
            reasons.append("noninferiority_not_established")
    else:
        reasons.append("no_pairwise_arm_comparison")
    return TrialEvaluation(
        protocol_version=protocol_version,
        model_version=model_version,
        holdout_start_utc=holdout_start_utc,
        holdout_end_utc=holdout_end_utc,
        control_total=total[TrialArm.CONTROL],
        control_completed=success[TrialArm.CONTROL],
        lower_total=total[TrialArm.LOWER],
        lower_completed=success[TrialArm.LOWER],
        censored_count=censored,
        excluded_count=excluded,
        independent_forecast_families=len(family),
        eligible_segments=dict(sorted(segments.items())),
        lower_minus_control_lower_bound=difference_lower,
        pre_registered_margin=noninferiority_margin,
        noninferiority_demonstrated=not reasons,
        reasons=tuple(reasons),
    )
