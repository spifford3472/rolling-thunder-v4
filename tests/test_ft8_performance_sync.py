"""Tests for restart-safe FT8 performance synchronization."""

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import UUID

from rolling_thunder.ft8.performance import (
    FT8AttemptOutcome,
    FT8PerformanceAttempt,
    FT8PerformanceUploadDisposition,
    FT8PerformanceUploadResult,
)
from rolling_thunder.ft8.performance_outbox import (
    FT8PerformanceOutboxRepository,
    FT8PerformanceSyncState,
)
from rolling_thunder.ft8.performance_sync import FT8PerformanceSyncService
from rolling_thunder.home_platform import HomePlatformUploadError

_ATTEMPT_ID = UUID("00000000-0000-0000-0000-000000000601")

def _attempt() -> FT8PerformanceAttempt:
    started = datetime(2026, 10, 2, 20, 0, tzinfo=UTC)
    return FT8PerformanceAttempt(
        attempt_id=_ATTEMPT_ID,
        callsign="K1ABC",
        outcome=FT8AttemptOutcome.RETRY_EXHAUSTED,
        success=False,
        terminal_state="retry_exhausted",
        terminal_reason="six attempts exhausted",
        started_at_utc=started,
        ended_at_utc=started + timedelta(minutes=2),
        utc_date=date(2026, 10, 2),
        band="20m",
        dial_frequency_hz=14_074_000,
        local_grid="EM79xm",
        remote_grid="FN31pr",
        distance_km=1000.0,
        audio_frequency_hz=1500,
        attempt_count=6,
    )

class Client:
    def __init__(self) -> None:
        self.calls: list[UUID] = []
        self.fail = False

    def upload_ft8_performance(
        self,
        attempt: FT8PerformanceAttempt,
    ) -> FT8PerformanceUploadResult:
        self.calls.append(attempt.attempt_id)
        if self.fail:
            raise HomePlatformUploadError("Forge offline")
        return FT8PerformanceUploadResult(
            attempt_id=attempt.attempt_id,
            disposition=FT8PerformanceUploadDisposition.ACCEPTED,
            received_at_utc=datetime(2026, 10, 2, 20, 5, tzinfo=UTC),
        )

class Poll:
    def cancel(self) -> None:
        return None


class Scheduler:
    def __init__(self) -> None:
        self.callback = None

    def schedule_repeating(self, interval_s: float, callback):  # type: ignore[no-untyped-def]
        del interval_s
        self.callback = callback
        return Poll()

def test_sync_success_marks_outbox_once(tmp_path: Path) -> None:
    now = datetime(2026, 10, 2, 20, 5, tzinfo=UTC)
    repository = FT8PerformanceOutboxRepository(tmp_path / "contacts.db")
    repository.add_idempotent(_attempt())
    client = Client()
    service = FT8PerformanceSyncService(
        repository,
        client,
        Scheduler(),  # type: ignore[arg-type]
        clock=lambda: now,
    )

    result = service.synchronize_due_now()

    assert result.attempted == 1
    assert result.synchronized == 1
    assert result.failed == 0
    assert client.calls == [_ATTEMPT_ID]
    assert repository.state_for(_ATTEMPT_ID) is FT8PerformanceSyncState.SYNCHRONIZED

    repeated = service.synchronize_due_now()
    assert repeated.attempted == 0
    assert client.calls == [_ATTEMPT_ID]


def test_sync_failure_leaves_retryable_outbox_without_duplicate(tmp_path: Path) -> None:
    current = {"now": datetime(2026, 10, 2, 20, 5, tzinfo=UTC)}
    repository = FT8PerformanceOutboxRepository(tmp_path / "contacts.db")
    repository.add_idempotent(_attempt())
    client = Client()
    client.fail = True
    service = FT8PerformanceSyncService(
        repository,
        client,
        Scheduler(),  # type: ignore[arg-type]
        retry_initial_delay_s=5,
        clock=lambda: current["now"],
    )

    first = service.synchronize_due_now()

    assert first.failed == 1
    assert repository.state_for(_ATTEMPT_ID) is FT8PerformanceSyncState.FAILED
    assert client.calls == [_ATTEMPT_ID]

    current["now"] += timedelta(seconds=4)
    assert service.synchronize_due_now().attempted == 0

    client.fail = False
    current["now"] += timedelta(seconds=1)
    second = service.synchronize_due_now()

    assert second.synchronized == 1
    assert client.calls == [_ATTEMPT_ID, _ATTEMPT_ID]
    assert repository.state_for(_ATTEMPT_ID) is FT8PerformanceSyncState.SYNCHRONIZED
