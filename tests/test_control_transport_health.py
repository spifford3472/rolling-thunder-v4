"""Hostile timing and lifecycle tests for the inert controller health policy."""

from dataclasses import FrozenInstanceError

import pytest

from rolling_thunder.control_transport_health import (
    ControlTransportHealthPolicy,
)
from rolling_thunder.control_transport_health import (
    TransportHealthState as State,
)


def begin(policy: ControlTransportHealthPolicy, now: float = 0) -> int:
    policy.start(now)
    token = policy.attempt_if_due(now)
    assert token is not None
    return token


def test_retry_schedule_is_exact_capped_and_single_issue() -> None:
    policy = ControlTransportHealthPolicy()
    token = begin(policy)
    now = 0.0
    for delay in (0.5, 1, 2, 4, 8, 8, 8):
        policy.failed(token, now, "device absent")
        before = policy.snapshot
        assert before.generation is None
        assert before.next_retry_at == now + delay
        policy.failed(token, now, "duplicate failure")
        assert policy.snapshot == before
        assert policy.attempt_if_due(now + delay - 0.001) is None
        now += delay
        new_token = policy.attempt_if_due(now)
        assert new_token is not None and new_token > token
        token = new_token
        assert policy.attempt_if_due(now) is None
    assert policy.snapshot.attempt_count == 8


def test_open_attempt_and_unvalidated_heartbeat_are_not_healthy() -> None:
    policy = ControlTransportHealthPolicy()
    token = begin(policy)
    policy.heartbeat(token, 1)
    assert policy.snapshot.state is State.SYNCHRONIZING
    assert policy.snapshot.last_valid_health_at is None
    policy.validated_session(token + 1, 1)
    assert policy.snapshot.state is State.SYNCHRONIZING
    policy.validated_session(token, 2)
    assert policy.snapshot.state is State.HEALTHY


@pytest.mark.parametrize("method", ["heartbeat", "validated_session"])
def test_late_health_cannot_revive_expired_session(method: str) -> None:
    policy = ControlTransportHealthPolicy()
    token = begin(policy)
    policy.validated_session(token, 0)
    getattr(policy, method)(token, 3)
    assert policy.snapshot.state is State.STALE
    assert policy.snapshot.generation is None
    assert policy.snapshot.next_retry_at == 3.5
    new_token = policy.attempt_if_due(3.5)
    assert new_token is not None and new_token != token
    policy.validated_session(token, 3.5)
    policy.heartbeat(token, 3.5)
    assert policy.snapshot.state is State.SYNCHRONIZING


def test_unfinished_handshake_expires_without_dispatch_or_retry_issuance() -> None:
    policy = ControlTransportHealthPolicy()
    begin(policy)
    policy.advance(3)
    assert policy.snapshot.state is State.STALE
    assert policy.snapshot.attempt_count == 1
    assert policy.attempt_if_due(3.49) is None
    assert policy.attempt_if_due(3.5) is not None


def test_stop_restart_invalidates_old_results_and_start_is_idempotent() -> None:
    policy = ControlTransportHealthPolicy()
    first = begin(policy)
    policy.start(0)
    assert policy.attempt_if_due(0) is None
    policy.stop(0)
    policy.stop(0)
    policy.validated_session(first, 0)
    policy.heartbeat(first, 0)
    policy.failed(first, 0, "obsolete")
    assert policy.snapshot.state is State.STOPPED
    assert policy.attempt_if_due(100) is None
    second = begin(policy, 100)
    assert second > first
    before = policy.snapshot
    policy.validated_session(first, 100)
    policy.failed(first, 100, "obsolete")
    policy.heartbeat(first, 100)
    policy.validated_session(True, 100)
    assert policy.snapshot == before
    policy.validated_session(second, 100)
    assert policy.snapshot.state is State.HEALTHY


def test_short_churn_keeps_backoff_stable_health_resets_it() -> None:
    policy = ControlTransportHealthPolicy()
    token = begin(policy)
    now = 0.0
    for delay in (0.5, 1, 2, 4, 8, 8):
        policy.validated_session(token, now)
        policy.failed(token, now + 1, "short connection")
        now += 1 + delay
        next_token = policy.attempt_if_due(now)
        assert next_token is not None
        token = next_token
    policy.validated_session(token, now)
    for elapsed in (2, 4, 6, 8, 10):
        policy.heartbeat(token, now + elapsed)
    policy.failed(token, now + 11, "after stable health")
    assert policy.snapshot.next_retry_at == now + 11.5


def test_gap_does_not_count_as_stable_health() -> None:
    policy = ControlTransportHealthPolicy()
    first = begin(policy)
    policy.failed(first, 0, "initial failure")
    second = policy.attempt_if_due(0.5)
    assert second is not None
    policy.validated_session(second, 0.5)
    policy.advance(20)
    assert policy.snapshot.state is State.STALE
    assert policy.snapshot.next_retry_at == 21


@pytest.mark.parametrize("method", ["start", "stop", "advance", "attempt_if_due", "validated_session", "heartbeat", "failed"])
@pytest.mark.parametrize("bad_time", [float("nan"), float("inf"), -float("inf"), -1.0, 1.0, True])
def test_invalid_time_does_not_mutate_any_lifecycle_operation(method: str, bad_time: float) -> None:
    policy = ControlTransportHealthPolicy()
    token = begin(policy, 2)
    before = policy.snapshot
    def call(now: float) -> None:
        if method == "failed":
            policy.failed(token, now, "bad clock")
        elif method in ("heartbeat", "validated_session"):
            getattr(policy, method)(token, now)
        else:
            getattr(policy, method)(now)
    with pytest.raises(ValueError):
        call(bad_time)
    assert policy.snapshot == before
    with pytest.raises(ValueError):
        policy.advance(1)
    policy.advance(2)
    assert policy.snapshot == before


@pytest.mark.parametrize("field", ["stale_after_s", "stable_after_s"])
@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf"), -float("inf"), True])
def test_invalid_intervals_rejected(field: str, value: float) -> None:
    with pytest.raises(ValueError):
        ControlTransportHealthPolicy(**{field: value})


def test_snapshots_are_detached_immutable_and_error_is_bounded() -> None:
    policy = ControlTransportHealthPolicy()
    initial = policy.snapshot
    token = begin(policy)
    policy.failed(token, 0, "x" * 1000)
    assert initial.state is State.STOPPED
    assert policy.snapshot.last_error == "x" * 256
    with pytest.raises(FrozenInstanceError):
        initial.attempt_count = 99  # type: ignore[misc]
