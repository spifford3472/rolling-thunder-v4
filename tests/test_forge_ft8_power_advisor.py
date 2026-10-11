"""Offline-only C5 scientific evaluation, shadow advice and readiness tests."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from rolling_thunder.forge_ft8_power_advisor import (
    AA4NP_RETROSPECTIVE_SHA256,
    AA4NP_RETROSPECTIVE_UUID,
    AA4NP_SOURCE_SHA256,
    AA4NP_SOURCE_UUID,
    CURRENT_OPERATIONAL_BASELINE_WATTS,
    SYNTHETIC_EXCLUSION_UUIDS,
    AttemptEvidence,
    AttemptOutcome,
    CandidateDefinition,
    CandidateRegistry,
    ComparisonReason,
    EvaluationArtifactRepository,
    EvaluationSpecification,
    EvidenceAvailability,
    ForecastEvidence,
    ReadinessAuditRepository,
    ReadinessEvidence,
    ReadinessMachine,
    ReadinessState,
    ShadowPowerAdvisory,
    evaluate_offline,
    pair_evidence,
)
from rolling_thunder.forge_ft8_power_advisor_config import (
    AtomicPowerAdvisorPolicy,
    ForgeFT8PowerAdvisorConfigurationError,
    FT8PowerAdvisorPolicy,
    PowerAdvisorMode,
    load_ft8_power_advisor_policy,
)

CHOICE = datetime(2026, 10, 11, 11, tzinfo=UTC)
SHA_A = "a" * 64
SHA_B = "b" * 64


def _attempt(**changes: Any) -> AttemptEvidence:
    choice = changes.get("choice_at_utc", CHOICE)
    values: dict[str, Any] = {
        "attempt_uuid": uuid4(),
        "immutable_payload_sha256": SHA_A,
        "choice_at_utc": choice,
        "outcome_at_utc": choice + timedelta(minutes=3),
        "source_available_at_utc": choice + timedelta(minutes=3),
        "callsign_group_sha256": SHA_B,
        "qso_group_id": str(uuid4()),
        "operating_segment": "40m:grid4:11utc",
        "provenance": "field_observed",
        "availability": EvidenceAvailability.PROSPECTIVE_PRE_CHOICE,
        "outcome": AttemptOutcome.COMPLETED,
        "transmitted": True,
        "start_power_watts": 20,
        "decoder_snr_db": -12.0,
    }
    values.update(changes)
    return AttemptEvidence.model_validate(values)


def _forecast(**changes: Any) -> ForecastEvidence:
    choice = changes.get("choice_at_utc", CHOICE)
    values: dict[str, Any] = {
        "forecast_id": uuid4(),
        "forecast_input_sha256": "c" * 64,
        "independent_forecast_input_sha256": "d" * 64,
        "generated_at_utc": choice - timedelta(minutes=10),
        "available_at_utc": choice - timedelta(minutes=9),
        "forecast_for_utc": choice,
        "choice_at_utc": choice,
        "availability": EvidenceAvailability.PROSPECTIVE_PRE_CHOICE,
        "provenance": "field_observed",
        "relation": "pre_choice",
        "training_eligible": True,
        "model_version": "model-1",
        "service_version": "service-1",
        "origin_grid": "EM79xm",
        "target_grid": "EL98",
        "origin_grid_precision": 6,
        "target_grid_precision": 4,
        "origin_uncertainty": "grid6 cell center assumption",
        "target_uncertainty": "grid4 cell center; coarse",
        "modeled_band_m": 40,
        "modeled_frequency_mhz": 7.2,
        "actual_dial_frequency_hz": 7_074_000,
        "modeled_snr_db_hz": 35.0,
        "reliability_fraction": 0.5,
        "ssn": 100.0,
        "ssn_observed_at_utc": choice - timedelta(days=1),
        "ssn_captured_at_utc": choice - timedelta(hours=1),
    }
    values.update(changes)
    return ForecastEvidence.model_validate(values)


def _policy(**changes: Any) -> FT8PowerAdvisorPolicy:
    values: dict[str, Any] = {"pinned_model_version": "model-1"}
    values.update(changes)
    return FT8PowerAdvisorPolicy.model_validate(values)


def _readiness(**changes: Any) -> ReadinessEvidence:
    values: dict[str, Any] = {
        "evaluated_at_utc": CHOICE,
        "independent_forecast_cells": 20_000,
        "real_independent_transmitted_attempts": 2_000,
        "attempts_per_operating_segment": {"40m:grid4": 100, "20m:grid6": 100},
        "forward_holdout_days": 30,
        "forward_holdout_attempts": 200,
        "calibration_error_percentage_points": 9.9,
        "heldout_noninferior_vs_20w": True,
        "fresh_prospective_forecast": True,
        "forecast_age_seconds": 60,
        "valid_asof_provenance": True,
        "observed_model_version": "model-1",
        "forge_reachable": True,
        "hardware_checks_passed": True,
        "statistical_checks_passed": True,
        "segment_checks_passed": True,
        "latency_seconds": 1.0,
        "source_drift_detected": False,
    }
    values.update(changes)
    return ReadinessEvidence.model_validate(values)


def test_strict_asof_utc_provenance_and_scientific_units() -> None:
    forecast = _forecast()
    assert forecast.modeled_frequency_mhz == 7.2
    assert forecast.actual_dial_frequency_hz == 7_074_000
    assert forecast.modeled_snr_db_hz == 35.0
    assert _attempt().decoder_snr_db == -12.0
    with pytest.raises(ValidationError, match="timezone-aware"):
        _forecast(choice_at_utc=CHOICE.replace(tzinfo=None))
    with pytest.raises(ValidationError, match="future SSN"):
        _forecast(ssn_observed_at_utc=CHOICE)
    with pytest.raises(ValidationError, match="grid precision"):
        _forecast(target_grid_precision=6)
    with pytest.raises(ValidationError, match="available by choice"):
        _forecast(available_at_utc=CHOICE + timedelta(seconds=1))


def test_pairing_excludes_late_backfill_unknown_synthetic_and_busy() -> None:
    good = pair_evidence(pair_id=uuid4(), attempt=_attempt(), forecast=_forecast())
    assert good.reason is ComparisonReason.COMPARABLE
    late = _forecast(
        availability=EvidenceAvailability.LATE,
        relation="post_attempt",
        training_eligible=False,
        available_at_utc=CHOICE + timedelta(minutes=1),
    )
    excluded = pair_evidence(pair_id=uuid4(), attempt=_attempt(), forecast=late)
    assert excluded.reason is ComparisonReason.NOT_COMPARABLE
    assert "forecast_not_prospective" in excluded.reason_codes
    busy = pair_evidence(
        pair_id=uuid4(), attempt=_attempt(outcome=AttemptOutcome.BUSY_TARGET), forecast=_forecast()
    )
    assert "outcome_censored" in busy.reason_codes
    synthetic_uuid = next(iter(SYNTHETIC_EXCLUSION_UUIDS))
    synthetic = _attempt(attempt_uuid=synthetic_uuid, provenance="synthetic", simulated=True)
    assert not synthetic.independently_comparable
    with pytest.raises(ValidationError, match="cannot be reclassified"):
        _attempt(attempt_uuid=synthetic_uuid)


def test_audited_source_and_retrospective_hashes_are_immutable() -> None:
    source = _attempt(attempt_uuid=AA4NP_SOURCE_UUID, immutable_payload_sha256=AA4NP_SOURCE_SHA256)
    retrospective = _attempt(
        attempt_uuid=AA4NP_RETROSPECTIVE_UUID,
        immutable_payload_sha256=AA4NP_RETROSPECTIVE_SHA256,
        availability=EvidenceAvailability.RETROSPECTIVE,
    )
    assert source.provenance == "field_observed"
    assert retrospective.provenance == "field_observed"
    assert retrospective.availability is EvidenceAvailability.RETROSPECTIVE
    with pytest.raises(ValidationError, match="unexpected immutable source hash"):
        _attempt(attempt_uuid=AA4NP_SOURCE_UUID)


def test_evaluation_deduplicates_attempt_qso_and_monthly_forecast_inputs() -> None:
    spec = EvaluationSpecification(
        specification_version="eval-1",
        generated_at_utc=CHOICE + timedelta(days=31),
        holdout_start_utc=CHOICE,
        holdout_end_utc=CHOICE + timedelta(days=30),
        minimum_holdout_days=30,
        minimum_holdout_attempts=1,
    )
    registry = CandidateRegistry(
        registry_version="registry-1",
        candidates=(
            CandidateDefinition(
                candidate_id="baseline-20w",
                candidate_version="1",
                feature_specification_sha256="e" * 64,
            ),
        ),
    )
    attempt = _attempt(choice_at_utc=CHOICE + timedelta(days=1))
    forecast = _forecast(choice_at_utc=attempt.choice_at_utc)
    pair = pair_evidence(pair_id=uuid4(), attempt=attempt, forecast=forecast)
    duplicate_uuid = pair.model_copy(update={"pair_id": uuid4()})
    duplicate_qso = pair.model_copy(
        update={"pair_id": uuid4(), "attempt": attempt.model_copy(update={"attempt_uuid": uuid4()})}
    )
    separate_attempt_same_monthly_input = pair.model_copy(
        update={
            "pair_id": uuid4(),
            "attempt": attempt.model_copy(
                update={
                    "attempt_uuid": uuid4(),
                    "qso_group_id": str(uuid4()),
                    "callsign_group_sha256": "f" * 64,
                }
            ),
        }
    )
    result = evaluate_offline(
        spec, registry, [pair, duplicate_uuid, duplicate_qso, separate_attempt_same_monthly_input]
    )
    assert result.independent_attempts == 2
    assert result.independent_forecast_inputs == 1
    assert result.empirical_success_probability is None
    assert result.minimum_power_watts is None
    assert result.reason is ComparisonReason.COMPARABLE


def test_grouped_forward_holdout_excludes_callsign_seen_in_training() -> None:
    spec = EvaluationSpecification(
        specification_version="eval-1",
        generated_at_utc=CHOICE + timedelta(days=31),
        holdout_start_utc=CHOICE,
        holdout_end_utc=CHOICE + timedelta(days=30),
        minimum_holdout_days=30,
        minimum_holdout_attempts=1,
    )
    registry = CandidateRegistry(
        registry_version="registry-1",
        candidates=(
            CandidateDefinition(
                candidate_id="candidate",
                candidate_version="1",
                feature_specification_sha256="e" * 64,
            ),
        ),
    )
    train = _attempt(choice_at_utc=CHOICE - timedelta(days=1))
    holdout = _attempt(
        choice_at_utc=CHOICE + timedelta(days=1),
        callsign_group_sha256=train.callsign_group_sha256,
    )
    result = evaluate_offline(
        spec,
        registry,
        [
            pair_evidence(
                pair_id=uuid4(),
                attempt=train,
                forecast=_forecast(choice_at_utc=train.choice_at_utc),
            ),
            pair_evidence(
                pair_id=uuid4(),
                attempt=holdout,
                forecast=_forecast(choice_at_utc=holdout.choice_at_utc),
            ),
        ],
    )
    assert result.independent_attempts == 0
    assert result.reason is ComparisonReason.INSUFFICIENT_EVIDENCE


def test_shadow_contract_cannot_actuate_or_invent_probability_or_power() -> None:
    base: dict[str, Any] = {
        "advisory_id": uuid4(),
        "generated_at_utc": CHOICE,
        "expires_at_utc": CHOICE + timedelta(minutes=5),
        "choice_at_utc": CHOICE,
        "candidate_ids": ("baseline-20w",),
        "model_version": "model-1",
        "service_version": "service-1",
        "policy_digest_sha256": SHA_A,
        "evidence_digest_sha256": SHA_B,
        "evaluation_digest_sha256": "c" * 64,
        "operating_segment": "40m:grid4",
        "forecast_age_seconds": 60,
        "independent_attempt_count": 2000,
        "independent_forecast_input_count": 20000,
        "missing_count": 0,
        "reason_codes": (),
        "operator_power_cap_watts": 30,
    }
    advisory = ShadowPowerAdvisory.model_validate(base)
    assert advisory.shadow_only is True
    assert advisory.apply_allowed is False
    assert advisory.may_transmit is False
    assert advisory.current_operational_baseline_watts == CURRENT_OPERATIONAL_BASELINE_WATTS == 20
    assert advisory.suggested_start_watts is None
    assert advisory.empirical_success_probability is None
    with pytest.raises(ValidationError, match="scientific experimental approval"):
        ShadowPowerAdvisory.model_validate({**base, "suggested_start_watts": 25})
    with pytest.raises(ValidationError, match="approved calibration"):
        ShadowPowerAdvisory.model_validate({**base, "empirical_success_probability": 0.6})
    with pytest.raises(ValidationError, match="absolute ceiling"):
        ShadowPowerAdvisory.model_validate(
            {**base, "suggested_start_watts": 35, "experimental_recommendation_approved": True}
        )


def test_policy_yaml_atomic_reload_off_thresholds_hysteresis_and_fallback(tmp_path: Path) -> None:
    config_path = tmp_path / "advisor.yaml"
    config_path.write_text("mode: shadow\npinned_model_version: model-1\n", encoding="utf-8")
    policy = load_ft8_power_advisor_policy(config_path)
    assert policy.fallback_start_watts == 20
    holder = AtomicPowerAdvisorPolicy(policy)
    config_path.write_text("mode: shadow\npinned_model_version: ''\n", encoding="utf-8")
    with pytest.raises(ForgeFT8PowerAdvisorConfigurationError):
        holder.reload(config_path)
    assert holder.snapshot() == policy

    machine = ReadinessMachine()
    off = machine.evaluate(_policy(), _readiness())
    assert off.new_state is ReadinessState.OFF
    shadow = _policy(mode=PowerAdvisorMode.SHADOW)
    first = machine.evaluate(shadow, _readiness())
    second = machine.evaluate(shadow, _readiness(evaluated_at_utc=CHOICE + timedelta(seconds=1)))
    assert first.new_state is ReadinessState.COLLECTING
    assert second.new_state is ReadinessState.SHADOW_READY
    raised = shadow.model_copy(update={"minimum_real_transmitted_attempts": 2_001})
    assert machine.evaluate(raised, _readiness()).new_state is ReadinessState.COLLECTING


def test_readiness_armed_is_readiness_only_and_disqualifies_immediately() -> None:
    machine = ReadinessMachine()
    policy = _policy(mode=PowerAdvisorMode.ARMED_WHEN_READY)
    machine.evaluate(policy, _readiness())
    ready = machine.evaluate(policy, _readiness(evaluated_at_utc=CHOICE + timedelta(seconds=1)))
    assert ready.new_state is ReadinessState.ELIGIBLE_FOR_FUTURE_ACTUATION
    assert "readiness_only_no_phase_c5_actuation" in ready.reason_codes
    degraded = machine.evaluate(
        policy,
        _readiness(evaluated_at_utc=CHOICE + timedelta(seconds=2), forge_reachable=False),
    )
    assert degraded.new_state is ReadinessState.DEGRADED
    assert "forge_unreachable" in degraded.reason_codes
    assert [item.sequence for item in machine.audit_log] == [1, 2, 3]


def test_readiness_transitions_are_durable_and_restart_safe(tmp_path: Path) -> None:
    audit = ReadinessAuditRepository(tmp_path / "readiness.sqlite")
    policy = _policy(mode=PowerAdvisorMode.SHADOW)
    first_machine = ReadinessMachine(audit)
    first_machine.evaluate(policy, _readiness())
    restarted = ReadinessMachine(audit)
    assert restarted.state is ReadinessState.COLLECTING
    transition = restarted.evaluate(
        policy, _readiness(evaluated_at_utc=CHOICE + timedelta(seconds=1))
    )
    assert transition.sequence == 2
    assert transition.new_state is ReadinessState.SHADOW_READY
    assert [item.sequence for item in audit.transitions()] == [1, 2]


def test_missing_stale_version_drift_segment_latency_and_calibration_fail_closed() -> None:
    policy = _policy(mode=PowerAdvisorMode.SHADOW)
    cases = (
        ({"fresh_prospective_forecast": False}, "forecast_not_fresh_prospective"),
        ({"forecast_age_seconds": 21_601}, "forecast_missing_or_stale"),
        ({"valid_asof_provenance": False}, "invalid_asof_provenance"),
        ({"observed_model_version": "model-2"}, "model_version_mismatch"),
        ({"source_drift_detected": True}, "source_drift_detected"),
        ({"segment_checks_passed": False}, "segment_check_failed"),
        ({"latency_seconds": 6.0}, "latency_missing_or_excessive"),
        ({"calibration_error_percentage_points": None}, "calibration_error_missing"),
        ({"calibration_error_percentage_points": 10.1}, "calibration_error_exceeded"),
        ({"heldout_noninferior_vs_20w": None}, "heldout_noninferiority_not_established"),
    )
    for changes, reason in cases:
        transition = ReadinessMachine().evaluate(policy, _readiness(**changes))
        assert transition.new_state is ReadinessState.DEGRADED
        assert reason in transition.reason_codes


def test_artifact_repository_is_additive_immutable_and_preserves_legacy(tmp_path: Path) -> None:
    path = tmp_path / "advisor.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE legacy(value TEXT NOT NULL)")
        db.execute("INSERT INTO legacy VALUES ('preserved')")
    repository = EvaluationArtifactRepository(path)
    payload = {"schema_version": 1, "registry_version": "one"}
    assert repository.store("candidate_registry", "registry-1", payload) is True
    assert repository.store("candidate_registry", "registry-1", payload) is False
    with pytest.raises(ValueError, match="changed immutable"):
        repository.store("candidate_registry", "registry-1", {**payload, "registry_version": "two"})
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT value FROM legacy").fetchone()[0] == "preserved"
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_collecting_when_counts_low_and_calibration_unavailable() -> None:
    policy = _policy(mode=PowerAdvisorMode.ARMED_WHEN_READY)
    evidence = _readiness(
        independent_forecast_cells=0,
        real_independent_transmitted_attempts=1,
        calibration_error_percentage_points=None,
        heldout_noninferior_vs_20w=None,
    )
    transition = ReadinessMachine().evaluate(policy, evidence)
    assert transition.new_state is ReadinessState.COLLECTING
    assert "independent_forecast_cells_below_threshold" in transition.reason_codes
    assert "real_transmitted_attempts_below_threshold" in transition.reason_codes
    assert "calibration_error_missing" in transition.reason_codes
    assert "heldout_noninferiority_not_established" in transition.reason_codes

    unreachable = _readiness(
        independent_forecast_cells=0,
        real_independent_transmitted_attempts=1,
        calibration_error_percentage_points=None,
        heldout_noninferior_vs_20w=None,
        forge_reachable=False,
    )
    degraded = ReadinessMachine().evaluate(policy, unreachable)
    assert degraded.new_state is ReadinessState.DEGRADED
    assert "forge_unreachable" in degraded.reason_codes
