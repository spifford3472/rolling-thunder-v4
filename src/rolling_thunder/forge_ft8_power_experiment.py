"""Versioned, non-actuating experimental-power assignment and audit contracts.

A randomized trial is NOT evidence of calibrated wattage until prospectively
enrolled, completed, and assessed with frozen denominators and holdouts.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from rolling_thunder.domain import DomainModel


class ExperimentArm(StrEnum):
    NOT_ENROLLED = "not_enrolled"
    BASELINE_20W = "baseline_20w"
    BOUNDED_LOWER_POWER = "bounded_lower_power"


class PowerTrialPolicy(DomainModel):
    schema_version: Literal[1] = 1
    enabled: bool = False
    experiment_version: str = Field(min_length=1, max_length=120)
    enrolled_percentage: int = Field(default=0, ge=0, le=10)
    lower_power_watts: int = Field(default=15, ge=5, le=20, multiple_of=5)
    baseline_power_watts: Literal[20] = 20
    operator_cap_watts: int = Field(default=20, ge=5, le=100)
    independent_operator_rf_approval: bool = False
    approved_client_indicator: bool = False
    approved_abort_and_power_restore: bool = False
    valid_prospective_choice_time: bool = False
    approved_statistical_protocol: bool = False
    driving_experiment_authorized: bool = False

    @model_validator(mode="after")
    def validate_safety(self) -> PowerTrialPolicy:
        if self.lower_power_watts >= self.baseline_power_watts:
            raise ValueError("experimental low-power arm must be below 20 W")
        return self

    @property
    def activation_allowed(self) -> bool:
        return all((
            self.enabled, self.independent_operator_rf_approval,
            self.approved_client_indicator, self.approved_abort_and_power_restore,
            self.valid_prospective_choice_time, self.approved_statistical_protocol,
            self.driving_experiment_authorized,
            self.operator_cap_watts >= self.baseline_power_watts,
        ))


class FrozenTrialAssignment(DomainModel):
    schema_version: Literal[1] = 1
    attempt_uuid: UUID
    experiment_version: str
    assigned_at_utc: datetime
    choice_at_utc: datetime
    policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    arm: ExperimentArm
    assignment_power_watts: int | None
    ui_banner: str | None
    shadow_only: Literal[True] = True
    apply_allowed: Literal[False] = False
    may_transmit: Literal[False] = False
    reason_codes: tuple[str, ...]

    @field_validator("assigned_at_utc", "choice_at_utc")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("trial times must be timezone aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def enforce_non_actuation(self) -> FrozenTrialAssignment:
        if self.arm is ExperimentArm.NOT_ENROLLED:
            if self.assignment_power_watts is not None or self.ui_banner is not None:
                raise ValueError("ineligible trial cannot suggest a wattage or banner")
        elif self.ui_banner is None or "FT8 POWER TEST" not in self.ui_banner:
            raise ValueError("experimental assignment must explicitly identify itself")
        if self.assigned_at_utc > self.choice_at_utc:
            raise ValueError("trial assignment must precede or coincide with frozen selection")
        return self


def make_trial_assignment(
    *,
    policy: PowerTrialPolicy,
    attempt_uuid: UUID,
    choice_at_utc: datetime,
    assigned_at_utc: datetime,
    secret: bytes,
) -> FrozenTrialAssignment:
    """Deterministic blinded allocation per attempt, with no PTT/power authority.

    The 50/50 arm allocation occurs only *after* a bounded percentage of otherwise
    eligible real attempts is sampled; no cherry-picking by modeled success.
    The seed must be provisioned as a protected, pinned experimental identity.
    """
    digest = hashlib.sha256(
        json.dumps(policy.model_dump(mode="json"), sort_keys=True).encode()
    ).hexdigest()
    reason_codes: list[str] = []
    if not policy.activation_allowed:
        reason_codes.append("experiment_safety_approval_incomplete")
    if len(secret) < 32:
        reason_codes.append("randomization_secret_missing_or_weak")
    if assigned_at_utc > choice_at_utc:
        reason_codes.append("assignment_after_operator_choice")
    arm = ExperimentArm.NOT_ENROLLED
    watts: int | None = None
    banner: str | None = None
    if not reason_codes:
        roll = hmac.new(
            secret, (policy.experiment_version + ":" + str(attempt_uuid)).encode(),
            hashlib.sha256,
        ).digest()
        enrolled = int.from_bytes(roll[:8], "big") < (
            (1 << 64) * policy.enrolled_percentage // 100
        )
        if enrolled:
            if roll[8] & 1:
                arm = ExperimentArm.BOUNDED_LOWER_POWER
                watts = policy.lower_power_watts
            else:
                arm = ExperimentArm.BASELINE_20W
                watts = 20
            banner = f"FT8 POWER TEST — assigned {watts} W; comparison trial"
            reason_codes.append("experimental_shadow_assignment_only")
        else:
            reason_codes.append("not_selected_by_randomization")
    return FrozenTrialAssignment(
        attempt_uuid=attempt_uuid,
        experiment_version=policy.experiment_version,
        assigned_at_utc=assigned_at_utc,
        choice_at_utc=choice_at_utc,
        policy_sha256=digest,
        arm=arm,
        assignment_power_watts=watts,
        ui_banner=banner,
        reason_codes=tuple(reason_codes),
    )
