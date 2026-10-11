"""Offline scientific evaluation and non-actuating C5 power advisories.

The module is deliberately Forge-only and provider-free.  It imports no Pi,
radio, CAT, PTT, UI, logging or live-CQ code and cannot apply its output.
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from enum import StrEnum
from json import dumps, loads
from pathlib import Path
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from rolling_thunder.domain import DomainModel
from rolling_thunder.forge_ft8_power_advisor_config import (
    FT8PowerAdvisorPolicy,
    PowerAdvisorMode,
)

EVIDENCE_SCHEMA_VERSION = 1
EVALUATION_SCHEMA_VERSION = 1
ADVISORY_SCHEMA_VERSION = 1
CURRENT_OPERATIONAL_BASELINE_WATTS = 20

AA4NP_SOURCE_UUID = UUID("938620bb-b4ff-40b2-9493-081b56bb038c")
AA4NP_SOURCE_SHA256 = "9de70a6c8d131500cefa580465bfe1033a87f558e3c655fac511443320288cab"
AA4NP_RETROSPECTIVE_UUID = UUID("1aa647cd-ea95-43db-821f-67b16e87e2b1")
AA4NP_RETROSPECTIVE_SHA256 = "74264c1f26ed164257f0cfe836771a6b0d0cffccba35185735677de57fc5d877"
SYNTHETIC_EXCLUSION_UUIDS = frozenset(
    {
        UUID("9ad2f0c2-ed0e-4ba7-8b03-732d8aa8c339"),
        UUID("1d99bba6-0f38-4069-a706-77f9a90d4a8c"),
    }
)
AUDITED_IMMUTABLE_EVIDENCE = {
    AA4NP_SOURCE_UUID: AA4NP_SOURCE_SHA256,
    AA4NP_RETROSPECTIVE_UUID: AA4NP_RETROSPECTIVE_SHA256,
}


class EvidenceAvailability(StrEnum):
    PROSPECTIVE_PRE_CHOICE = "prospective_pre_choice"
    LATE = "late"
    BACKFILL = "backfill"
    RETROSPECTIVE = "retrospective"


class AttemptOutcome(StrEnum):
    COMPLETED = "completed"
    NO_ANSWER = "no_answer"
    BUSY_TARGET = "busy_target"
    ABORTED = "aborted"
    EQUIPMENT_FAULT = "equipment_fault"
    TIMING_FAULT = "timing_fault"
    UNKNOWN = "unknown"


class ComparisonReason(StrEnum):
    COMPARABLE = "comparable"
    NOT_COMPARABLE = "not_comparable"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC)


def _canonical(value: Any) -> str:
    return dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


class ForecastEvidence(DomainModel):
    """One immutable forecast input available (or not) for one choice."""

    schema_version: Literal[1] = 1
    forecast_id: UUID
    forecast_input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    independent_forecast_input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    generated_at_utc: datetime
    available_at_utc: datetime
    forecast_for_utc: datetime
    choice_at_utc: datetime
    availability: EvidenceAvailability
    provenance: Literal["field_observed", "synthetic", "unknown"]
    relation: Literal["pre_choice", "post_attempt", "retrospective"]
    training_eligible: bool = False
    model_version: str = Field(min_length=1, max_length=120)
    service_version: str = Field(min_length=1, max_length=120)
    origin_grid: str = Field(min_length=4, max_length=6)
    target_grid: str = Field(min_length=4, max_length=6)
    origin_grid_precision: Literal[4, 6]
    target_grid_precision: Literal[4, 6]
    origin_uncertainty: str = Field(min_length=1, max_length=200)
    target_uncertainty: str = Field(min_length=1, max_length=200)
    modeled_band_m: int = Field(gt=0)
    modeled_frequency_mhz: float = Field(gt=0)
    actual_dial_frequency_hz: int = Field(gt=0)
    modeled_snr_db_hz: float | None = None
    reliability_fraction: float | None = Field(default=None, ge=0, le=1)
    ssn: float = Field(ge=0)
    ssn_observed_at_utc: datetime
    ssn_captured_at_utc: datetime

    @field_validator(
        "generated_at_utc",
        "available_at_utc",
        "forecast_for_utc",
        "choice_at_utc",
        "ssn_observed_at_utc",
        "ssn_captured_at_utc",
    )
    @classmethod
    def aware_utc(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def strict_asof(self) -> Self:
        if self.generated_at_utc > self.available_at_utc:
            raise ValueError("forecast cannot be available before it is generated")
        if self.ssn_observed_at_utc > self.generated_at_utc:
            raise ValueError("future SSN data cannot be used by a forecast")
        if self.ssn_captured_at_utc > self.generated_at_utc:
            raise ValueError("SSN captured after generation is not an as-of input")
        if self.origin_grid_precision != len(self.origin_grid) or self.target_grid_precision != len(
            self.target_grid
        ):
            raise ValueError("grid precision must match the explicit grid")
        is_prospective = (
            self.availability is EvidenceAvailability.PROSPECTIVE_PRE_CHOICE
            and self.relation == "pre_choice"
            and self.available_at_utc <= self.choice_at_utc
        )
        if self.training_eligible and (not is_prospective or self.provenance != "field_observed"):
            raise ValueError(
                "training evidence must be audited, prospective and available by choice"
            )
        if self.availability is EvidenceAvailability.PROSPECTIVE_PRE_CHOICE and not is_prospective:
            raise ValueError("prospective evidence must be pre-choice and available by choice")
        return self

    @property
    def canonical_sha256(self) -> str:
        return _sha(self.model_dump(mode="json"))


class AttemptEvidence(DomainModel):
    schema_version: Literal[1] = 1
    attempt_uuid: UUID
    immutable_payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    choice_at_utc: datetime
    outcome_at_utc: datetime
    source_available_at_utc: datetime
    callsign_group_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    qso_group_id: str = Field(min_length=1, max_length=120)
    operating_segment: str = Field(min_length=1, max_length=120)
    provenance: Literal["field_observed", "synthetic", "unknown"]
    availability: EvidenceAvailability
    outcome: AttemptOutcome
    transmitted: bool
    start_power_watts: int | None = Field(default=None, ge=5, le=100)
    decoder_snr_db: float | None = None
    simulated: bool = False

    @field_validator("choice_at_utc", "outcome_at_utc", "source_available_at_utc")
    @classmethod
    def aware_utc(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def temporal_and_provenance_contract(self) -> Self:
        if self.outcome_at_utc < self.choice_at_utc:
            raise ValueError("outcome cannot precede choice")
        if self.simulated and self.provenance != "synthetic":
            raise ValueError("simulated attempts must be synthetic")
        if self.attempt_uuid in SYNTHETIC_EXCLUSION_UUIDS and self.provenance != "synthetic":
            raise ValueError("documented synthetic UUID cannot be reclassified")
        expected_sha = AUDITED_IMMUTABLE_EVIDENCE.get(self.attempt_uuid)
        if expected_sha is not None and self.immutable_payload_sha256 != expected_sha:
            raise ValueError("audited evidence UUID has an unexpected immutable source hash")
        return self

    @property
    def independently_comparable(self) -> bool:
        return (
            self.provenance == "field_observed"
            and self.availability is EvidenceAvailability.PROSPECTIVE_PRE_CHOICE
            and self.transmitted
            and not self.simulated
            and self.outcome in {AttemptOutcome.COMPLETED, AttemptOutcome.NO_ANSWER}
        )


class EvidencePair(DomainModel):
    schema_version: Literal[1] = 1
    pair_id: UUID
    attempt: AttemptEvidence
    forecast: ForecastEvidence | None
    reason: ComparisonReason
    reason_codes: tuple[str, ...]

    @model_validator(mode="after")
    def validate_pairing(self) -> Self:
        if self.reason is ComparisonReason.COMPARABLE:
            if self.forecast is None or not self.attempt.independently_comparable:
                raise ValueError("comparable pair requires real independent attempt and forecast")
            if not self.forecast.training_eligible:
                raise ValueError("comparable forecast must pass strict prospective eligibility")
            if self.forecast.choice_at_utc != self.attempt.choice_at_utc:
                raise ValueError("attempt and forecast must share the frozen choice timestamp")
        return self


def pair_evidence(
    *, pair_id: UUID, attempt: AttemptEvidence, forecast: ForecastEvidence | None
) -> EvidencePair:
    """Apply the strict C5 as-of join and return a reason-coded pair."""
    reasons: list[str] = []
    if attempt.provenance != "field_observed":
        reasons.append("attempt_provenance_not_field_observed")
    if attempt.simulated or attempt.attempt_uuid in SYNTHETIC_EXCLUSION_UUIDS:
        reasons.append("synthetic_or_simulated_attempt")
    if not attempt.transmitted:
        reasons.append("attempt_not_transmitted")
    if attempt.outcome in {AttemptOutcome.BUSY_TARGET, AttemptOutcome.UNKNOWN}:
        reasons.append("outcome_censored")
    elif attempt.outcome not in {AttemptOutcome.COMPLETED, AttemptOutcome.NO_ANSWER}:
        reasons.append("outcome_not_comparable")
    if forecast is None:
        reasons.append("forecast_missing")
    else:
        if forecast.provenance != "field_observed":
            reasons.append("forecast_provenance_not_field_observed")
        if forecast.availability is not EvidenceAvailability.PROSPECTIVE_PRE_CHOICE:
            reasons.append("forecast_not_prospective")
        if forecast.relation != "pre_choice":
            reasons.append("forecast_not_pre_choice")
        if forecast.available_at_utc > attempt.choice_at_utc:
            reasons.append("forecast_available_after_choice")
        if forecast.choice_at_utc != attempt.choice_at_utc:
            reasons.append("choice_timestamp_mismatch")
        if not forecast.training_eligible:
            reasons.append("forecast_training_ineligible")
    return EvidencePair(
        pair_id=pair_id,
        attempt=attempt,
        forecast=forecast,
        reason=(ComparisonReason.COMPARABLE if not reasons else ComparisonReason.NOT_COMPARABLE),
        reason_codes=tuple(reasons),
    )


class CandidateDefinition(DomainModel):
    schema_version: Literal[1] = 1
    candidate_id: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9._:-]+$")
    candidate_version: str = Field(min_length=1, max_length=120)
    feature_specification_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    ranking_only: bool = True
    emits_probability: bool = False

    @property
    def canonical_sha256(self) -> str:
        return _sha(self.model_dump(mode="json"))


class CandidateRegistry(DomainModel):
    schema_version: Literal[1] = 1
    registry_version: str = Field(min_length=1, max_length=120)
    candidates: tuple[CandidateDefinition, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_candidates(self) -> Self:
        identities = {(item.candidate_id, item.candidate_version) for item in self.candidates}
        if len(identities) != len(self.candidates):
            raise ValueError("candidate registry contains duplicate identity")
        return self

    @property
    def canonical_sha256(self) -> str:
        return _sha(self.model_dump(mode="json"))


class EvaluationSpecification(DomainModel):
    schema_version: Literal[1] = 1
    specification_version: str = Field(min_length=1, max_length=120)
    generated_at_utc: datetime
    holdout_start_utc: datetime
    holdout_end_utc: datetime
    minimum_holdout_days: int = Field(default=30, ge=1)
    minimum_holdout_attempts: int = Field(default=200, ge=1)

    @field_validator("generated_at_utc", "holdout_start_utc", "holdout_end_utc")
    @classmethod
    def aware_utc(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def chronological(self) -> Self:
        if self.holdout_end_utc <= self.holdout_start_utc:
            raise ValueError("holdout end must follow start")
        if self.generated_at_utc < self.holdout_end_utc:
            raise ValueError("evaluation cannot be generated before holdout ends")
        return self

    @property
    def canonical_sha256(self) -> str:
        return _sha(self.model_dump(mode="json"))


class EvaluationResult(DomainModel):
    schema_version: Literal[1] = 1
    specification_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    registry_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason: ComparisonReason
    reason_codes: tuple[str, ...]
    independent_attempts: int
    independent_forecast_inputs: int
    censored_busy_or_unknown: int
    missing_or_noncomparable: int
    holdout_days: int
    holdout_attempts: int
    segment_attempt_counts: dict[str, int]
    source_drift_detected: bool
    coverage_fraction: float | None = Field(default=None, ge=0, le=1)
    empirical_success_probability: None = None
    minimum_power_watts: None = None
    simulated: bool = False

    @property
    def canonical_sha256(self) -> str:
        return _sha(self.model_dump(mode="json"))


def evaluate_offline(
    specification: EvaluationSpecification,
    registry: CandidateRegistry,
    pairs: Sequence[EvidencePair],
) -> EvaluationResult:
    """Produce descriptive, leakage-resistant counts without invented inference."""
    pair_payloads = [pair.model_dump(mode="json") for pair in pairs]
    input_sha = _sha(pair_payloads)
    seen_attempts: set[UUID] = set()
    seen_qso_groups: set[str] = set()
    forecast_inputs: set[str] = set()
    eligible: list[EvidencePair] = []
    censored = missing = 0
    train_groups: set[str] = set()
    for pair in sorted(pairs, key=lambda item: item.attempt.choice_at_utc):
        attempt = pair.attempt
        if attempt.attempt_uuid in seen_attempts or attempt.qso_group_id in seen_qso_groups:
            continue
        seen_attempts.add(attempt.attempt_uuid)
        seen_qso_groups.add(attempt.qso_group_id)
        if attempt.choice_at_utc < specification.holdout_start_utc:
            train_groups.add(attempt.callsign_group_sha256)
            continue
        if not (
            specification.holdout_start_utc <= attempt.choice_at_utc < specification.holdout_end_utc
        ):
            continue
        if attempt.outcome in {AttemptOutcome.BUSY_TARGET, AttemptOutcome.UNKNOWN}:
            censored += 1
            continue
        if pair.reason is not ComparisonReason.COMPARABLE or pair.forecast is None:
            missing += 1
            continue
        if attempt.callsign_group_sha256 in train_groups:
            missing += 1
            continue
        eligible.append(pair)
        forecast_inputs.add(pair.forecast.independent_forecast_input_sha256)
    segment_counts = Counter(pair.attempt.operating_segment for pair in eligible)
    holdout_days = max(
        0, (specification.holdout_end_utc.date() - specification.holdout_start_utc.date()).days
    )
    reasons: list[str] = []
    if holdout_days < specification.minimum_holdout_days:
        reasons.append("forward_holdout_days_below_minimum")
    if len(eligible) < specification.minimum_holdout_attempts:
        reasons.append("forward_holdout_attempts_below_minimum")
    provenance_versions = {
        (pair.forecast.model_version, pair.forecast.service_version)
        for pair in eligible
        if pair.forecast is not None
    }
    drift = len(provenance_versions) > 1
    if drift:
        reasons.append("source_or_model_version_drift")
    reason = ComparisonReason.COMPARABLE if not reasons else ComparisonReason.INSUFFICIENT_EVIDENCE
    denominator = len(eligible) + censored + missing
    return EvaluationResult(
        specification_sha256=specification.canonical_sha256,
        registry_sha256=registry.canonical_sha256,
        input_sha256=input_sha,
        reason=reason,
        reason_codes=tuple(reasons),
        independent_attempts=len(eligible),
        independent_forecast_inputs=len(forecast_inputs),
        censored_busy_or_unknown=censored,
        missing_or_noncomparable=missing,
        holdout_days=holdout_days,
        holdout_attempts=len(eligible),
        segment_attempt_counts=dict(sorted(segment_counts.items())),
        source_drift_detected=drift,
        coverage_fraction=None if denominator == 0 else len(eligible) / denominator,
        simulated=any(pair.attempt.simulated for pair in pairs),
    )


class ShadowPowerAdvisory(DomainModel):
    schema_version: Literal[1] = 1
    advisory_id: UUID
    generated_at_utc: datetime
    expires_at_utc: datetime
    choice_at_utc: datetime
    shadow_only: Literal[True] = True
    apply_allowed: Literal[False] = False
    may_transmit: Literal[False] = False
    current_operational_baseline_watts: Literal[20] = 20
    suggested_start_watts: int | None = Field(default=None, ge=5, le=100)
    empirical_success_probability: float | None = Field(default=None, ge=0, le=1)
    candidate_ids: tuple[str, ...] = Field(min_length=1)
    model_version: str
    service_version: str
    policy_digest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_digest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evaluation_digest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    operating_segment: str
    forecast_age_seconds: int | None = Field(default=None, ge=0)
    independent_attempt_count: int = Field(ge=0)
    independent_forecast_input_count: int = Field(ge=0)
    missing_count: int = Field(ge=0)
    reason_codes: tuple[str, ...]
    modeled_circuit_suitability: float | None = Field(default=None, ge=0, le=1)
    ranking_suitability: float | None = Field(default=None, ge=0, le=1)
    training_eligible: bool = False
    probability_calibration_approved: bool = False
    experimental_recommendation_approved: bool = False
    operator_power_cap_watts: int = Field(ge=5, le=100)

    @field_validator("generated_at_utc", "expires_at_utc", "choice_at_utc")
    @classmethod
    def aware_utc(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def no_actuation_or_unapproved_power(self) -> Self:
        if self.expires_at_utc <= self.generated_at_utc:
            raise ValueError("advisory expiry must follow generation")
        if self.suggested_start_watts is not None:
            if not self.experimental_recommendation_approved:
                raise ValueError("suggested power requires scientific experimental approval")
            if self.suggested_start_watts > self.operator_power_cap_watts:
                raise ValueError("operator power cap is an absolute ceiling")
        if (
            self.empirical_success_probability is not None
            and not self.probability_calibration_approved
        ):
            raise ValueError("empirical probability requires approved calibration")
        return self

    @property
    def canonical_sha256(self) -> str:
        return _sha(self.model_dump(mode="json"))


class ReadinessState(StrEnum):
    OFF = "OFF"
    COLLECTING = "INSUFFICIENT_EVIDENCE/COLLECTING"
    SHADOW_READY = "SHADOW_READY"
    ELIGIBLE_FOR_FUTURE_ACTUATION = "ELIGIBLE_FOR_FUTURE_ACTUATION"
    DEGRADED = "DEGRADED/SUSPENDED"


class ReadinessEvidence(DomainModel):
    evaluated_at_utc: datetime
    independent_forecast_cells: int = Field(ge=0)
    real_independent_transmitted_attempts: int = Field(ge=0)
    attempts_per_operating_segment: dict[str, int]
    forward_holdout_days: int = Field(ge=0)
    forward_holdout_attempts: int = Field(ge=0)
    calibration_error_percentage_points: float | None = Field(default=None, ge=0, le=100)
    heldout_noninferior_vs_20w: bool | None
    fresh_prospective_forecast: bool
    forecast_age_seconds: int | None = Field(default=None, ge=0)
    valid_asof_provenance: bool
    observed_model_version: str | None
    forge_reachable: bool
    hardware_checks_passed: bool
    statistical_checks_passed: bool
    segment_checks_passed: bool
    latency_seconds: float | None = Field(default=None, ge=0)
    source_drift_detected: bool

    @field_validator("evaluated_at_utc")
    @classmethod
    def aware_utc(cls, value: datetime) -> datetime:
        return _utc(value)


class ReadinessTransition(DomainModel):
    sequence: int = Field(ge=1)
    occurred_at_utc: datetime
    previous_state: ReadinessState
    new_state: ReadinessState
    reason_codes: tuple[str, ...]
    policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("occurred_at_utc")
    @classmethod
    def aware_utc(cls, value: datetime) -> datetime:
        return _utc(value)


class ReadinessAuditRepository:
    """Append-only transition audit; changed replay at a sequence fails closed."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS ft8_advisor_readiness_transition_v1(
                sequence INTEGER PRIMARY KEY, canonical_sha256 TEXT NOT NULL,
                payload_json TEXT NOT NULL)"""
            )

    def append(self, transition: ReadinessTransition) -> bool:
        payload = _canonical(transition.model_dump(mode="json"))
        digest = hashlib.sha256(payload.encode()).hexdigest()
        with self._connect() as db:
            row = db.execute(
                "SELECT canonical_sha256 FROM ft8_advisor_readiness_transition_v1 WHERE sequence=?",
                (transition.sequence,),
            ).fetchone()
            if row is not None:
                if row[0] != digest:
                    raise ValueError(
                        "readiness transition sequence replay changed immutable content"
                    )
                return False
            db.execute(
                "INSERT INTO ft8_advisor_readiness_transition_v1 VALUES (?,?,?)",
                (transition.sequence, digest, payload),
            )
        return True

    def transitions(self) -> tuple[ReadinessTransition, ...]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT payload_json FROM ft8_advisor_readiness_transition_v1 ORDER BY sequence"
            ).fetchall()
        return tuple(ReadinessTransition.model_validate(loads(row[0])) for row in rows)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=5)
        db.execute("PRAGMA busy_timeout=5000")
        return db


class ReadinessMachine:
    """Deterministic readiness-only state machine with qualification hysteresis."""

    def __init__(self, audit_repository: ReadinessAuditRepository | None = None) -> None:
        self._audit_repository = audit_repository
        stored = () if audit_repository is None else audit_repository.transitions()
        self.state = stored[-1].new_state if stored else ReadinessState.OFF
        self._qualified_streak = (
            100
            if self.state
            in {ReadinessState.SHADOW_READY, ReadinessState.ELIGIBLE_FOR_FUTURE_ACTUATION}
            else 0
        )
        if self._qualified_streak == 0:
            for item in reversed(stored):
                if item.reason_codes != ("qualification_hysteresis",):
                    break
                self._qualified_streak += 1
        self._audit: list[ReadinessTransition] = list(stored)

    @property
    def audit_log(self) -> tuple[ReadinessTransition, ...]:
        return tuple(self._audit)

    def evaluate(
        self, policy: FT8PowerAdvisorPolicy, evidence: ReadinessEvidence
    ) -> ReadinessTransition:
        policy_sha = _sha(policy.model_dump(mode="json"))
        evidence_sha = _sha(evidence.model_dump(mode="json"))
        reasons = self._disqualifications(policy, evidence)
        if policy.mode is PowerAdvisorMode.OFF:
            new_state = ReadinessState.OFF
            reasons = ["configuration_off"]
            self._qualified_streak = 0
        else:
            insufficient = self._insufficient(policy, evidence)
            pending_metrics = {
                "calibration_error_missing",
                "heldout_noninferiority_not_established",
            }
            if reasons and (not insufficient or set(reasons) - pending_metrics):
                new_state = ReadinessState.DEGRADED
                self._qualified_streak = 0
            elif insufficient:
                new_state = ReadinessState.COLLECTING
                reasons = insufficient + reasons
                self._qualified_streak = 0
            else:
                self._qualified_streak += 1
                if self._qualified_streak < policy.qualification_hysteresis_evaluations:
                    new_state = ReadinessState.COLLECTING
                    reasons = ["qualification_hysteresis"]
                elif policy.mode is PowerAdvisorMode.SHADOW:
                    new_state = ReadinessState.SHADOW_READY
                    reasons = ["shadow_thresholds_satisfied"]
                else:
                    new_state = ReadinessState.ELIGIBLE_FOR_FUTURE_ACTUATION
                    reasons = ["readiness_only_no_phase_c5_actuation"]
        transition = ReadinessTransition(
            sequence=len(self._audit) + 1,
            occurred_at_utc=evidence.evaluated_at_utc,
            previous_state=self.state,
            new_state=new_state,
            reason_codes=tuple(reasons),
            policy_sha256=policy_sha,
            evidence_sha256=evidence_sha,
        )
        if self._audit_repository is not None:
            self._audit_repository.append(transition)
        self.state = new_state
        self._audit.append(transition)
        return transition

    @staticmethod
    def _disqualifications(policy: FT8PowerAdvisorPolicy, item: ReadinessEvidence) -> list[str]:
        reasons: list[str] = []
        checks = {
            "forge_unreachable": not item.forge_reachable,
            "hardware_check_failed": not item.hardware_checks_passed,
            "statistical_check_failed": not item.statistical_checks_passed,
            "segment_check_failed": not item.segment_checks_passed,
            "forecast_not_fresh_prospective": policy.require_fresh_prospective_forecast
            and not item.fresh_prospective_forecast,
            "forecast_missing_or_stale": policy.require_fresh_prospective_forecast
            and (
                item.forecast_age_seconds is None
                or item.forecast_age_seconds > policy.maximum_forecast_age_seconds
            ),
            "invalid_asof_provenance": policy.require_valid_asof_provenance
            and not item.valid_asof_provenance,
            "model_version_mismatch": item.observed_model_version != policy.pinned_model_version,
            "source_drift_detected": item.source_drift_detected,
            "latency_missing_or_excessive": item.latency_seconds is None
            or item.latency_seconds > policy.maximum_forge_latency_seconds,
        }
        reasons.extend(name for name, failed in checks.items() if failed)
        if item.calibration_error_percentage_points is None:
            reasons.append("calibration_error_missing")
        elif (
            item.calibration_error_percentage_points
            > policy.maximum_calibration_error_percentage_points
        ):
            reasons.append("calibration_error_exceeded")
        if (
            policy.require_heldout_noninferiority_vs_20w
            and item.heldout_noninferior_vs_20w is not True
        ):
            reasons.append("heldout_noninferiority_not_established")
        return reasons

    @staticmethod
    def _insufficient(policy: FT8PowerAdvisorPolicy, item: ReadinessEvidence) -> list[str]:
        reasons: list[str] = []
        if item.independent_forecast_cells < policy.minimum_independent_forecast_cells:
            reasons.append("independent_forecast_cells_below_threshold")
        if item.real_independent_transmitted_attempts < policy.minimum_real_transmitted_attempts:
            reasons.append("real_transmitted_attempts_below_threshold")
        if (
            not item.attempts_per_operating_segment
            or min(item.attempts_per_operating_segment.values())
            < policy.minimum_attempts_per_operating_segment
        ):
            reasons.append("operating_segment_below_threshold")
        if item.forward_holdout_days < policy.minimum_forward_holdout_days:
            reasons.append("forward_holdout_days_below_threshold")
        if item.forward_holdout_attempts < policy.minimum_forward_holdout_attempts:
            reasons.append("forward_holdout_attempts_below_threshold")
        return reasons


class EvaluationArtifactRepository:
    """Additive immutable hash store for candidate/spec/result audit artifacts."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS ft8_advisor_schema_v1(version INTEGER PRIMARY KEY);
                INSERT OR IGNORE INTO ft8_advisor_schema_v1(version) VALUES (1);
                CREATE TABLE IF NOT EXISTS ft8_advisor_artifact_v1(
                  artifact_kind TEXT NOT NULL, artifact_id TEXT NOT NULL,
                  canonical_sha256 TEXT NOT NULL, payload_json TEXT NOT NULL,
                  PRIMARY KEY(artifact_kind,artifact_id));
                """
            )

    def store(
        self,
        kind: Literal["candidate_registry", "evaluation_specification", "evaluation_result"],
        artifact_id: str,
        payload: Mapping[str, Any],
    ) -> bool:
        encoded = _canonical(payload)
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        with self._connect() as db:
            existing = db.execute(
                "SELECT canonical_sha256 FROM ft8_advisor_artifact_v1 WHERE artifact_kind=? AND artifact_id=?",
                (kind, artifact_id),
            ).fetchone()
            if existing is not None:
                if existing[0] != digest:
                    raise ValueError("artifact identity replay changed immutable content")
                return False
            db.execute(
                "INSERT INTO ft8_advisor_artifact_v1 VALUES (?,?,?,?)",
                (kind, artifact_id, digest, encoded),
            )
        return True

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=5)
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=5000")
        return db
