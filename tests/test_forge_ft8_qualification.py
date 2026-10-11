from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from rolling_thunder.forge_ft8_qualification import QualificationCertificate

NOW = datetime(2026, 10, 11, tzinfo=UTC)


def certificate(**changes: object) -> QualificationCertificate:
    values = {
        "candidate_model_version": "model-1",
        "protocol_version": "preregistered-1",
        "policy_sha256": "a" * 64,
        "code_sha256": "c" * 40,
        "input_dataset_sha256": "b" * 64,
        "evaluation_result_sha256": "d" * 64,
        "generated_at_utc": NOW,
        "evidence_first_choice_utc": NOW - timedelta(days=100),
        "evidence_last_choice_utc": NOW - timedelta(days=1),
        "holdout_start_utc": NOW - timedelta(days=31),
        "holdout_end_utc": NOW - timedelta(days=1),
        "independent_forecast_inputs": 100,
        "independent_real_transmitted_attempts": 12,
        "qualified_holdout_attempts": 2,
        "holdout_days": 30,
        "control_attempts": 1,
        "experimental_attempts": 1,
        "censored_attempts": 2,
        "excluded_attempts": 3,
        "per_segment_counts": {"40m": 2},
        "result": "insufficient_evidence",
        "reason_codes": ("insufficient_real_attempts",),
    }
    values.update(changes)
    return QualificationCertificate.model_validate(values)


def test_insufficient_certificate_is_immutable_explainable_and_non_actuating() -> None:
    item = certificate()
    assert item.shadow_only and not item.apply_allowed and not item.may_transmit
    assert "insufficient_evidence" in item.explanation
    assert item.canonical_sha256 == certificate().canonical_sha256


def test_fake_totals_and_quality_cannot_issue_qualified_certificate() -> None:
    with pytest.raises(ValidationError, match="requires verified prospective proof"):
        certificate(
            independent_forecast_inputs=20_000,
            independent_real_transmitted_attempts=2_000,
            qualified_holdout_attempts=200,
            result="scientifically_qualified",
        )


def test_noninferiority_confidence_bound_rejected() -> None:
    with pytest.raises(ValidationError, match="confidence bound fails"):
        certificate(
            result="scientifically_qualified",
            independent_forecast_inputs=20_000,
            independent_real_transmitted_attempts=2_000,
            qualified_holdout_attempts=200,
            independent_protocol_approved=True,
            prospective_asof_validated=True,
            provenance_validated=True,
            heldout_groups_disjoint=True,
            source_and_model_stable=True,
            power_readback_validated=True,
            calibrated_model_validated=True,
            noninferiority_established=True,
            calibration_error_percentage_points=9,
            noninferiority_margin_percentage_points=5,
            noninferiority_confidence_bound_percentage_points=-6,
        )
