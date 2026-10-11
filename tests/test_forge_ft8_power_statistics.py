"""Offline-only independent, held-out control-vs-lower-watt study."""
from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_DNS, uuid5

from rolling_thunder.forge_ft8_power_statistics import (
    QualifiedTrialObservation,
    TrialArm,
    TrialOutcome,
    evaluate_trial_holdout,
)

START = datetime(2026, 8, 1, tzinfo=UTC)
END = START + timedelta(days=40)


def observation(index: int, arm: TrialArm, **changes: object) -> QualifiedTrialObservation:
    choice = START + timedelta(days=index % 35, minutes=index)
    values = {
        "attempt_uuid": uuid5(NAMESPACE_DNS, f"attempt-{index}"),
        "qso_group_id": f"qso-{index}",
        "callsign_group_sha256": format(index + 1, "064x"),
        "operating_segment": "40m:EM79->EL98",
        "choice_at_utc": choice,
        "forecast_generated_at_utc": choice - timedelta(hours=2),
        "forecast_available_at_utc": choice - timedelta(hours=1),
        "outcome_at_utc": choice + timedelta(minutes=2),
        "forecast_input_sha256": format(index + 20001, "064x"),
        "independent_forecast_family_sha256": format(index + 40001, "064x"),
        "payload_sha256": "a" * 64,
        "assignment_sha256": "b" * 64,
        "model_version": "v1",
        "protocol_version": "registered-v1",
        "arm": arm,
        "assigned_watts": 20 if arm is TrialArm.CONTROL else 15,
        "power_readback_watts": 20 if arm is TrialArm.CONTROL else 15,
        "outcome": TrialOutcome.COMPLETED,
        "field_observed": True,
        "assigned_before_choice": True,
        "selection_probability": 0.05,
    }
    values.update(changes)
    return QualifiedTrialObservation.model_validate(values)


def evaluate(items: tuple[QualifiedTrialObservation, ...]):
    return evaluate_trial_holdout(
        items, protocol_version="registered-v1", model_version="v1",
        holdout_start_utc=START, holdout_end_utc=END,
    )


def test_sufficient_balanced_randomized_data_can_establish_noninferiority() -> None:
    items = tuple(observation(i, TrialArm.CONTROL if i % 2 == 0 else TrialArm.LOWER) for i in range(800))
    result = evaluate(items)
    assert result.control_total == result.lower_total == 400
    assert result.noninferiority_demonstrated
    assert result.lower_minus_control_lower_bound is not None
    assert result.lower_minus_control_lower_bound > -0.05
    assert not result.may_transmit and not result.apply_allowed


def test_lower_power_failure_blocks_even_when_counts_high() -> None:
    items = tuple(
        observation(i, TrialArm.CONTROL if i % 2 == 0 else TrialArm.LOWER,
                    outcome=TrialOutcome.NO_ANSWER if i % 2 and i % 4 == 1 else TrialOutcome.COMPLETED)
        for i in range(800)
    )
    result = evaluate(items)
    assert not result.noninferiority_demonstrated
    assert "noninferiority_not_established" in result.reasons


def test_provenance_censoring_and_power_mismatch_excluded() -> None:
    items = (
        observation(1, TrialArm.LOWER, field_observed=False),
        observation(2, TrialArm.CONTROL, retrospectively_generated=True),
        observation(3, TrialArm.LOWER, outcome=TrialOutcome.CENSORED_BUSY),
        observation(4, TrialArm.CONTROL, power_readback_watts=None),
        observation(5, TrialArm.LOWER, assigned_before_choice=False),
    )
    result = evaluate(items)
    assert result.control_total == result.lower_total == 0
    assert result.censored_count == 1
    assert result.excluded_count == 4
    assert not result.noninferiority_demonstrated


def test_duplicate_attempt_and_qso_are_not_independent() -> None:
    first = observation(10, TrialArm.CONTROL)
    items = (
        first, first, observation(11, TrialArm.LOWER, qso_group_id="qso-10"),
        observation(12, TrialArm.LOWER)
    )
    result = evaluate(items)
    assert result.control_total == 1
    assert result.lower_total == 1
    assert result.excluded_count == 2
