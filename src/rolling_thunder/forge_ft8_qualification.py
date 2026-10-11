"""Immutable, explainable C5 power qualification certificate (not an RF command)."""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from rolling_thunder.domain import DomainModel


class QualificationCertificate(DomainModel):
    schema_version: Literal[1] = 1
    candidate_model_version: str = Field(min_length=1, max_length=120)
    protocol_version: str = Field(min_length=1, max_length=120)
    policy_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    code_sha256: str = Field(pattern=r"^[a-f0-9]{40}$")
    input_dataset_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    evaluation_result_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    generated_at_utc: datetime
    evidence_first_choice_utc: datetime
    evidence_last_choice_utc: datetime
    holdout_start_utc: datetime
    holdout_end_utc: datetime
    independent_forecast_inputs: int = Field(ge=0)
    independent_real_transmitted_attempts: int = Field(ge=0)
    qualified_holdout_attempts: int = Field(ge=0)
    holdout_days: int = Field(ge=0)
    control_attempts: int = Field(ge=0)
    experimental_attempts: int = Field(ge=0)
    censored_attempts: int = Field(ge=0)
    excluded_attempts: int = Field(ge=0)
    per_segment_counts: dict[str, int]
    calibration_error_percentage_points: float | None = Field(default=None, ge=0, le=100)
    noninferiority_margin_percentage_points: float | None = Field(default=None, ge=0, le=100)
    noninferiority_confidence_bound_percentage_points: float | None = None
    noninferiority_established: bool = False
    independent_protocol_approved: bool = False
    prospective_asof_validated: bool = False
    provenance_validated: bool = False
    heldout_groups_disjoint: bool = False
    source_and_model_stable: bool = False
    power_readback_validated: bool = False
    calibrated_model_validated: bool = False
    result: Literal["insufficient_evidence", "scientifically_qualified", "suspended"]
    reason_codes: tuple[str, ...]
    shadow_only: Literal[True] = True
    apply_allowed: Literal[False] = False
    may_transmit: Literal[False] = False

    @field_validator(
        "generated_at_utc",
        "evidence_first_choice_utc",
        "evidence_last_choice_utc",
        "holdout_start_utc",
        "holdout_end_utc",
    )
    @classmethod
    def normalize_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("qualification timestamps must be timezone aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_certificate(self) -> QualificationCertificate:
        if self.evidence_last_choice_utc < self.evidence_first_choice_utc:
            raise ValueError("evidence UTC range reversed")
        if not self.holdout_start_utc < self.holdout_end_utc <= self.generated_at_utc:
            raise ValueError("holdout must be completed before qualification")
        if self.result == "scientifically_qualified":
            validated = all((
                self.independent_protocol_approved,
                self.prospective_asof_validated,
                self.provenance_validated,
                self.heldout_groups_disjoint,
                self.source_and_model_stable,
                self.power_readback_validated,
                self.calibrated_model_validated,
                self.noninferiority_established,
                self.calibration_error_percentage_points is not None,
                self.noninferiority_margin_percentage_points is not None,
                self.noninferiority_confidence_bound_percentage_points is not None,
                self.independent_forecast_inputs >= 20_000,
                self.independent_real_transmitted_attempts >= 2_000,
                self.holdout_days >= 30,
                self.qualified_holdout_attempts >= 200,
                self.control_attempts > 0,
                self.experimental_attempts > 0,
                bool(self.per_segment_counts),
            ))
            if not validated:
                raise ValueError("a qualification certificate requires verified prospective proof")
            if (
                self.noninferiority_confidence_bound_percentage_points is not None
                and self.noninferiority_margin_percentage_points is not None
                and self.noninferiority_confidence_bound_percentage_points
                < -self.noninferiority_margin_percentage_points
            ):
                raise ValueError("heldout noninferiority confidence bound fails")
        return self

    @property
    def canonical_sha256(self) -> str:
        return hashlib.sha256(
            json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    @property
    def explanation(self) -> str:
        return (
            f"{self.result}: model {self.candidate_model_version}; "
            f"{self.independent_real_transmitted_attempts} independent real attempts; "
            f"{self.independent_forecast_inputs} forecast inputs; "
            f"{self.qualified_holdout_attempts} heldout attempts / {self.holdout_days} days; "
            f"{self.control_attempts} control / {self.experimental_attempts} test; "
            f"reasons={','.join(self.reason_codes) or 'none'}; "
            f"certificate_sha256={self.canonical_sha256}"
        )
