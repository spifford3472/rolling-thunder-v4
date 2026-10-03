"""Tests for UTC-day FT8 attempt history used by CQ presentation."""

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import UUID

from rolling_thunder.ft8.attempt_history import (
    FT8AttemptHistoryService,
    FT8AttemptVisualState,
)
from rolling_thunder.ft8.performance import FT8AttemptOutcome, FT8PerformanceAttempt
from rolling_thunder.ft8.performance_outbox import FT8PerformanceOutboxRepository


def _attempt(
    *,
    attempt_id: str,
    callsign: str = "K1ABC",
    band: str = "40m",
    outcome: FT8AttemptOutcome,
    started_at: datetime,
) -> FT8PerformanceAttempt:
    return FT8PerformanceAttempt(
        attempt_id=UUID(attempt_id),
        callsign=callsign,
        outcome=outcome,
        success=outcome is FT8AttemptOutcome.COMPLETED,
        terminal_state=outcome.value,
        terminal_reason=(
            None if outcome is FT8AttemptOutcome.COMPLETED else outcome.value
        ),
        started_at_utc=started_at,
        ended_at_utc=started_at + timedelta(seconds=30),
        utc_date=started_at.date(),
        band=band,
        dial_frequency_hz=7_074_000,
        local_grid="EM79xm",
        remote_grid="FN31",
        audio_frequency_hz=1500,
    )


def test_failed_and_aborted_states_are_keyed_by_callsign_band_and_date(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 10, 3, 3, 0, tzinfo=UTC)
    repository = FT8PerformanceOutboxRepository(tmp_path / "contacts.db")
    failed = _attempt(
        attempt_id="00000000-0000-0000-0000-000000000801",
        outcome=FT8AttemptOutcome.RETRY_EXHAUSTED,
        started_at=now,
    )
    aborted = _attempt(
        attempt_id="00000000-0000-0000-0000-000000000802",
        callsign="K2XYZ",
        outcome=FT8AttemptOutcome.ABORTED,
        started_at=now,
    )
    repository.add_idempotent(failed)
    repository.add_idempotent(aborted)

    history = FT8AttemptHistoryService(repository, clock=lambda: now)

    assert history.state_for("k1abc", "40m") is FT8AttemptVisualState.FAILED
    assert history.state_for("K2XYZ", "40m") is FT8AttemptVisualState.ABORTED
    assert history.state_for("K1ABC", "20m") is None


def test_latest_same_day_attempt_state_wins_and_success_clears_marker(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 10, 3, 3, 0, tzinfo=UTC)
    repository = FT8PerformanceOutboxRepository(tmp_path / "contacts.db")
    history = FT8AttemptHistoryService(repository, clock=lambda: now)

    failed = _attempt(
        attempt_id="00000000-0000-0000-0000-000000000811",
        outcome=FT8AttemptOutcome.ERROR,
        started_at=now,
    )
    aborted = _attempt(
        attempt_id="00000000-0000-0000-0000-000000000812",
        outcome=FT8AttemptOutcome.ABORTED,
        started_at=now + timedelta(minutes=1),
    )
    completed = _attempt(
        attempt_id="00000000-0000-0000-0000-000000000813",
        outcome=FT8AttemptOutcome.COMPLETED,
        started_at=now + timedelta(minutes=2),
    )

    for attempt in (failed, aborted, completed):
        repository.add_idempotent(attempt)
        history.record(attempt)

    assert history.state_for("K1ABC", "40m") is None


def test_history_resets_at_next_utc_date(tmp_path: Path) -> None:
    current = {"now": datetime(2026, 10, 3, 23, 59, tzinfo=UTC)}
    repository = FT8PerformanceOutboxRepository(tmp_path / "contacts.db")
    attempt = _attempt(
        attempt_id="00000000-0000-0000-0000-000000000821",
        outcome=FT8AttemptOutcome.RETRY_EXHAUSTED,
        started_at=current["now"],
    )
    repository.add_idempotent(attempt)
    history = FT8AttemptHistoryService(
        repository,
        clock=lambda: current["now"],
    )

    assert history.state_for("K1ABC", "40m") is FT8AttemptVisualState.FAILED

    current["now"] = datetime(2026, 10, 4, 0, 0, tzinfo=UTC)

    assert history.state_for("K1ABC", "40m") is None


def test_non_cq_eligibility_is_not_created_by_attempt_history(tmp_path: Path) -> None:
    now = datetime(2026, 10, 3, 3, 0, tzinfo=UTC)
    repository = FT8PerformanceOutboxRepository(tmp_path / "contacts.db")
    attempt = _attempt(
        attempt_id="00000000-0000-0000-0000-000000000831",
        outcome=FT8AttemptOutcome.ERROR,
        started_at=now,
    )
    repository.add_idempotent(attempt)

    history = FT8AttemptHistoryService(repository, clock=lambda: now)

    # The history service can decorate an eligible CQ but intentionally exposes
    # no API that inserts a callsign into CQ activity.
    assert history.state_for("K1ABC", "40m") is FT8AttemptVisualState.FAILED
