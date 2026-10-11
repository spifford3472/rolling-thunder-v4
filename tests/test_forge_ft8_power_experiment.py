from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from rolling_thunder.forge_ft8_power_experiment import (
    ExperimentArm,
    PowerTrialPolicy,
    make_trial_assignment,
)

NOW = datetime(2026, 10, 11, tzinfo=UTC)


def policy(**changes: object) -> PowerTrialPolicy:
    values = {
        "experiment_version": "pilot-v1",
        "enabled": True,
        "enrolled_percentage": 10,
        "operator_cap_watts": 20,
        "independent_operator_rf_approval": True,
        "approved_client_indicator": True,
        "approved_abort_and_power_restore": True,
        "valid_prospective_choice_time": True,
        "approved_statistical_protocol": True,
        "driving_experiment_authorized": True,
    }
    values.update(changes)
    return PowerTrialPolicy.model_validate(values)


def test_trial_off_by_default_even_with_many_samples() -> None:
    p = PowerTrialPolicy(experiment_version="pilot-v1")
    for _ in range(15):
        assignment = make_trial_assignment(
            policy=p, attempt_uuid=uuid4(), choice_at_utc=NOW,
            assigned_at_utc=NOW, secret=b"X" * 32,
        )
        assert assignment.arm is ExperimentArm.NOT_ENROLLED
        assert assignment.assignment_power_watts is None
        assert assignment.may_transmit is False
        assert assignment.apply_allowed is False


def test_randomized_stratified_lower_and_baseline_without_actuation() -> None:
    p = policy(enrolled_percentage=10)
    results = [
        make_trial_assignment(
            policy=p, attempt_uuid=uuid4(), choice_at_utc=NOW,
            assigned_at_utc=NOW, secret=b"Y" * 32,
        ) for _ in range(500)
    ]
    enrolled = [r for r in results if r.arm is not ExperimentArm.NOT_ENROLLED]
    assert 20 < len(enrolled) < 90
    assert {r.arm for r in enrolled} == {
        ExperimentArm.BASELINE_20W, ExperimentArm.BOUNDED_LOWER_POWER,
    }
    assert all(r.ui_banner and "FT8 POWER TEST" in r.ui_banner for r in enrolled)
    assert all(not r.apply_allowed and not r.may_transmit for r in results)


def test_assignment_is_reproducible_and_missing_safety_fails_closed() -> None:
    attempt_id = uuid4()
    kwargs = {"attempt_uuid": attempt_id, "choice_at_utc": NOW, "assigned_at_utc": NOW}
    first = make_trial_assignment(policy=policy(), secret=b"K" * 32, **kwargs)
    assert first == make_trial_assignment(policy=policy(), secret=b"K" * 32, **kwargs)
    blocked = make_trial_assignment(
        policy=policy(approved_abort_and_power_restore=False), secret=b"K" * 32, **kwargs
    )
    assert blocked.arm is ExperimentArm.NOT_ENROLLED
    with pytest.raises(ValidationError, match="precede"):
        make_trial_assignment(
            policy=policy(), secret=b"K" * 32, attempt_uuid=attempt_id,
            choice_at_utc=NOW, assigned_at_utc=NOW + timedelta(seconds=1)
        )


def test_power_cap_and_validation() -> None:
    assert not policy(operator_cap_watts=15).activation_allowed
    with pytest.raises(ValidationError):
        policy(lower_power_watts=20)
