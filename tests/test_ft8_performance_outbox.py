"""Tests for the restart-safe local FT8 performance outbox."""

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import UUID

_DEFAULT_ATTEMPT_ID = UUID("00000000-0000-0000-0000-000000000201")

import pytest

from rolling_thunder.ft8.performance import FT8AttemptOutcome, FT8PerformanceAttempt
from rolling_thunder.ft8.performance_outbox import (
    FT8PerformanceConflictError,
    FT8PerformanceOutboxRepository,
    FT8PerformanceSyncState,
)


def _attempt(
    *,
    attempt_id: UUID = _DEFAULT_ATTEMPT_ID,
    callsign: str = "K1ABC",
) -> FT8PerformanceAttempt:
    started = datetime(2026, 10, 2, 20, 0, tzinfo=UTC)
    return FT8PerformanceAttempt(
        attempt_id=attempt_id,
        callsign=callsign,
        outcome=FT8AttemptOutcome.ABORTED,
        success=False,
        terminal_state="aborted",
        terminal_reason="operator abort",
        started_at_utc=started,
        ended_at_utc=started + timedelta(seconds=45),
        utc_date=date(2026, 10, 2),
        band="20m",
        dial_frequency_hz=14_074_000,
        local_grid="EM79xm",
        remote_grid="FN31pr",
        distance_km=1000.0,
        audio_frequency_hz=1500,
        attempt_count=2,
        last_qso_state="aborted",
    )


def test_outbox_add_is_durable_and_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "contacts.db"
    repository = FT8PerformanceOutboxRepository(path)
    attempt = _attempt()

    repository.add_idempotent(attempt)
    repository.add_idempotent(attempt)

    restarted = FT8PerformanceOutboxRepository(path)
    ready = restarted.list_ready(datetime(2026, 10, 2, 21, 0, tzinfo=UTC))

    assert ready == [attempt]
    assert restarted.state_for(attempt.attempt_id) is FT8PerformanceSyncState.PENDING


def test_same_attempt_id_with_changed_payload_is_rejected(tmp_path: Path) -> None:
    repository = FT8PerformanceOutboxRepository(tmp_path / "contacts.db")
    original = _attempt()
    repository.add_idempotent(original)

    with pytest.raises(FT8PerformanceConflictError):
        repository.add_idempotent(_attempt(callsign="K2XYZ"))


def test_synchronized_attempt_is_not_listed_ready(tmp_path: Path) -> None:
    repository = FT8PerformanceOutboxRepository(tmp_path / "contacts.db")
    attempt = _attempt()
    repository.add_idempotent(attempt)

    repository.mark_synchronized(attempt.attempt_id)

    assert repository.state_for(attempt.attempt_id) is FT8PerformanceSyncState.SYNCHRONIZED
    assert repository.list_ready(datetime(2026, 10, 2, 21, 0, tzinfo=UTC)) == []


def test_failure_uses_exponential_retry_without_duplicate_payload(tmp_path: Path) -> None:
    repository = FT8PerformanceOutboxRepository(tmp_path / "contacts.db")
    attempt = _attempt()
    now = datetime(2026, 10, 2, 20, 0, tzinfo=UTC)
    repository.add_idempotent(attempt)

    repository.record_failure(attempt.attempt_id, "Forge offline", now=now)

    assert repository.state_for(attempt.attempt_id) is FT8PerformanceSyncState.FAILED
    assert repository.list_ready(now + timedelta(seconds=4)) == []
    assert repository.list_ready(now + timedelta(seconds=5)) == [attempt]

    repository.record_failure(
        attempt.attempt_id,
        "Forge still offline",
        now=now + timedelta(seconds=5),
    )
    assert repository.list_ready(now + timedelta(seconds=14)) == []
    assert repository.list_ready(now + timedelta(seconds=15)) == [attempt]
