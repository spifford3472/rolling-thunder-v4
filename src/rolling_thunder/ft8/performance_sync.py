"""Background delivery of local FT8 performance telemetry to Forge."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from threading import Lock
from typing import Protocol

from pydantic import Field

from rolling_thunder.domain import DomainModel
from rolling_thunder.ft8.performance import FT8PerformanceAttempt, FT8PerformanceUploadResult
from rolling_thunder.ft8.performance_outbox import FT8PerformanceOutboxRepository
from rolling_thunder.home_platform import HomePlatformError
from rolling_thunder.radio_polling import PollScheduler, ScheduledPoll

Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


class FT8PerformanceClient(Protocol):
    """Network boundary needed by the telemetry sync worker."""

    def upload_ft8_performance(
        self,
        attempt: FT8PerformanceAttempt,
    ) -> FT8PerformanceUploadResult:
        ...


class FT8PerformanceSyncResult(DomainModel):
    attempted: int = Field(ge=0)
    synchronized: int = Field(ge=0)
    failed: int = Field(ge=0)
    running: bool = False
    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error: str | None = Field(default=None, max_length=1000)
    consecutive_failed_runs: int = Field(default=0, ge=0)


class FT8PerformanceSyncService:
    """Synchronize terminal attempt records without blocking QSO execution."""

    def __init__(
        self,
        repository: FT8PerformanceOutboxRepository,
        client: FT8PerformanceClient,
        scheduler: PollScheduler,
        *,
        interval_s: float = 30.0,
        batch_size: int = 25,
        retry_initial_delay_s: float = 5.0,
        retry_max_delay_s: float = 300.0,
        clock: Clock = _utc_now,
    ) -> None:
        if interval_s <= 0:
            raise ValueError("FT8 performance synchronization interval must be positive")
        if batch_size <= 0:
            raise ValueError("FT8 performance synchronization batch size must be positive")
        if retry_initial_delay_s <= 0 or retry_max_delay_s <= 0:
            raise ValueError("FT8 performance retry delays must be positive")
        if retry_max_delay_s < retry_initial_delay_s:
            raise ValueError("FT8 performance maximum retry delay is below initial delay")

        self._repository = repository
        self._client = client
        self._scheduler = scheduler
        self._interval_s = interval_s
        self._batch_size = batch_size
        self._retry_initial_delay_s = retry_initial_delay_s
        self._retry_max_delay_s = retry_max_delay_s
        self._clock = clock
        self._scheduled_poll: ScheduledPoll | None = None
        self._sync_lock = Lock()
        self._latest_result = FT8PerformanceSyncResult(
            attempted=0,
            synchronized=0,
            failed=0,
        )

    @property
    def latest_result(self) -> FT8PerformanceSyncResult:
        return self._latest_result

    @property
    def is_running(self) -> bool:
        return self._scheduled_poll is not None

    def start(self) -> FT8PerformanceSyncResult:
        if self.is_running:
            raise RuntimeError("FT8 performance synchronization is already running")
        self._scheduled_poll = self._scheduler.schedule_repeating(
            self._interval_s,
            self._synchronize_once,
        )
        self._latest_result = self._latest_result.model_copy(update={"running": True})
        return self._latest_result

    def stop(self) -> FT8PerformanceSyncResult:
        poll = self._scheduled_poll
        self._scheduled_poll = None
        if poll is not None:
            poll.cancel()
        self._latest_result = self._latest_result.model_copy(update={"running": False})
        return self._latest_result

    def synchronize_due_now(self) -> FT8PerformanceSyncResult:
        if not self._sync_lock.acquire(blocking=False):
            return self._latest_result
        try:
            return self._run_once()
        finally:
            self._sync_lock.release()

    def _synchronize_once(self) -> None:
        if self.is_running:
            try:
                self.synchronize_due_now()
            except Exception as error:  # noqa: BLE001 - scheduler must remain alive
                # A repeating ThreadScheduledPoll exits when its callback raises.  Keep
                # analytics failures isolated from contact logging and make the degraded
                # worker visible instead of silently killing its scheduler thread.
                self._record_run_failure(error)

    def _run_once(self) -> FT8PerformanceSyncResult:
        now = self._timestamp()
        try:
            attempts = self._repository.list_ready(now, limit=self._batch_size)
        except Exception as error:  # noqa: BLE001 - publish repository health failure
            return self._record_run_failure(error, attempted_at=now)
        attempted = 0
        synchronized = 0
        failed = 0
        last_error: str | None = None

        for attempt in attempts:
            attempted += 1
            try:
                self._client.upload_ft8_performance(attempt)
            except HomePlatformError as error:
                failed += 1
                last_error = self._error_text(error)
                try:
                    self._repository.record_failure(
                        attempt.attempt_id,
                        last_error,
                        now=self._timestamp(),
                        initial_delay_s=self._retry_initial_delay_s,
                        maximum_delay_s=self._retry_max_delay_s,
                    )
                except Exception as persistence_error:  # noqa: BLE001 - keep batch alive
                    last_error = self._error_text(persistence_error)
                continue

            try:
                self._repository.mark_synchronized(attempt.attempt_id)
            except Exception as error:  # noqa: BLE001 - keep later attempts eligible
                failed += 1
                last_error = self._error_text(error)
            else:
                synchronized += 1

        self._latest_result = FT8PerformanceSyncResult(
            attempted=attempted,
            synchronized=synchronized,
            failed=failed,
            running=self.is_running,
            last_attempt_at=now,
            last_success_at=(
                self._timestamp()
                if synchronized > 0
                else self._latest_result.last_success_at
            ),
            last_error=last_error,
            consecutive_failed_runs=(
                self._latest_result.consecutive_failed_runs + 1
                if failed > 0 and synchronized == 0
                else 0
            ),
        )
        return self._latest_result

    def _record_run_failure(
        self,
        error: Exception,
        *,
        attempted_at: datetime | None = None,
    ) -> FT8PerformanceSyncResult:
        self._latest_result = FT8PerformanceSyncResult(
            attempted=0,
            synchronized=0,
            failed=1,
            running=self.is_running,
            last_attempt_at=attempted_at or self._timestamp(),
            last_success_at=self._latest_result.last_success_at,
            last_error=self._error_text(error),
            consecutive_failed_runs=self._latest_result.consecutive_failed_runs + 1,
        )
        return self._latest_result

    @staticmethod
    def _error_text(error: Exception) -> str:
        return (str(error).strip() or error.__class__.__name__)[:1000]

    def _timestamp(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("FT8 performance synchronization clock must be timezone-aware")
        return value.astimezone(UTC)
