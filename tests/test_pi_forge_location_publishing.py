"""Tests for bounded background Pi-to-Forge location scheduling."""

from __future__ import annotations

from concurrent.futures import Executor, Future
from typing import Any

from rolling_thunder.pi_forge_location_publisher import (
    PiForgeLocationPublisherState,
    PiForgeLocationPublishingService,
    PiForgeLocationPublishStatus,
)
from rolling_thunder.radio_polling import PollCallback


class ManualScheduledPoll:
    def __init__(self, callback: PollCallback) -> None:
        self.callback = callback
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True

    def fire(self) -> None:
        if not self.cancelled:
            self.callback()


class ManualScheduler:
    def __init__(self) -> None:
        self.interval_s: float | None = None
        self.poll: ManualScheduledPoll | None = None

    def schedule_repeating(
        self,
        interval_s: float,
        callback: PollCallback,
    ) -> ManualScheduledPoll:
        self.interval_s = interval_s
        self.poll = ManualScheduledPoll(callback)
        return self.poll


class DeferredExecutor(Executor):
    def __init__(self) -> None:
        self.jobs: list[tuple[Future[Any], Any, tuple[Any, ...], dict[str, Any]]] = []
        self.shutdown_called = False
        self.cancel_futures = False

    def submit(self, fn: Any, /, *args: Any, **kwargs: Any) -> Future[Any]:
        future: Future[Any] = Future()
        self.jobs.append((future, fn, args, kwargs))
        return future

    def shutdown(self, wait: bool = True, *, cancel_futures: bool = False) -> None:
        self.shutdown_called = True
        self.cancel_futures = cancel_futures
        if cancel_futures:
            for future, _fn, _args, _kwargs in self.jobs:
                future.cancel()

    def run_next(self) -> None:
        future, fn, args, kwargs = self.jobs.pop(0)
        if future.set_running_or_notify_cancel():
            try:
                result = fn(*args, **kwargs)
            except Exception as error:  # noqa: BLE001 - mirror Executor semantics
                future.set_exception(error)
            else:
                future.set_result(result)


class FakePublisher:
    def __init__(self, statuses: list[PiForgeLocationPublishStatus]) -> None:
        self.statuses = statuses
        self.calls = 0
        self.state = PiForgeLocationPublisherState()

    def get_state(self) -> PiForgeLocationPublisherState:
        return self.state

    def publish_latest(self) -> PiForgeLocationPublisherState:
        self.calls += 1
        status = self.statuses.pop(0)
        self.state = PiForgeLocationPublisherState(status=status)
        return self.state


def test_start_queues_first_opportunity_without_inline_io() -> None:
    publisher = FakePublisher([PiForgeLocationPublishStatus.PUBLISHED])
    scheduler = ManualScheduler()
    executor = DeferredExecutor()
    monotonic_value = 100.0
    service = PiForgeLocationPublishingService(
        publisher,  # type: ignore[arg-type]
        scheduler,
        executor_factory=lambda: executor,
        monotonic_clock=lambda: monotonic_value,
    )

    service.start()

    assert publisher.calls == 0
    assert len(executor.jobs) == 1
    assert service.is_publishing is True
    assert scheduler.interval_s == 30.0

    executor.run_next()

    assert publisher.calls == 1
    assert service.latest_state.status is PiForgeLocationPublishStatus.PUBLISHED
    assert service.is_publishing is False
    service.stop()


def test_scheduler_never_queues_overlapping_requests() -> None:
    publisher = FakePublisher([PiForgeLocationPublishStatus.PUBLISHED])
    scheduler = ManualScheduler()
    executor = DeferredExecutor()
    now = [100.0]
    service = PiForgeLocationPublishingService(
        publisher,  # type: ignore[arg-type]
        scheduler,
        executor_factory=lambda: executor,
        monotonic_clock=lambda: now[0],
    )

    service.start()
    assert scheduler.poll is not None
    scheduler.poll.fire()
    scheduler.poll.fire()

    assert len(executor.jobs) == 1
    assert publisher.calls == 0

    executor.run_next()
    assert publisher.calls == 1
    service.stop()


def test_success_waits_ten_minutes_before_next_publish() -> None:
    publisher = FakePublisher(
        [
            PiForgeLocationPublishStatus.PUBLISHED,
            PiForgeLocationPublishStatus.PUBLISHED,
        ]
    )
    scheduler = ManualScheduler()
    executor = DeferredExecutor()
    now = [100.0]
    service = PiForgeLocationPublishingService(
        publisher,  # type: ignore[arg-type]
        scheduler,
        executor_factory=lambda: executor,
        monotonic_clock=lambda: now[0],
        publish_interval_s=600.0,
    )

    service.start()
    executor.run_next()
    assert scheduler.poll is not None

    now[0] = 699.9
    scheduler.poll.fire()
    assert executor.jobs == []

    now[0] = 700.0
    scheduler.poll.fire()
    assert len(executor.jobs) == 1
    executor.run_next()
    assert publisher.calls == 2
    service.stop()


def test_failure_retries_after_one_minute_and_skip_after_thirty_seconds() -> None:
    publisher = FakePublisher(
        [
            PiForgeLocationPublishStatus.FAILED,
            PiForgeLocationPublishStatus.SKIPPED,
            PiForgeLocationPublishStatus.PUBLISHED,
        ]
    )
    scheduler = ManualScheduler()
    executor = DeferredExecutor()
    now = [100.0]
    service = PiForgeLocationPublishingService(
        publisher,  # type: ignore[arg-type]
        scheduler,
        executor_factory=lambda: executor,
        monotonic_clock=lambda: now[0],
        retry_interval_s=60.0,
        unusable_retry_interval_s=30.0,
    )

    service.start()
    executor.run_next()
    assert scheduler.poll is not None

    now[0] = 159.9
    scheduler.poll.fire()
    assert executor.jobs == []

    now[0] = 160.0
    scheduler.poll.fire()
    executor.run_next()
    assert publisher.calls == 2

    now[0] = 189.9
    scheduler.poll.fire()
    assert executor.jobs == []

    now[0] = 190.0
    scheduler.poll.fire()
    executor.run_next()
    assert publisher.calls == 3
    service.stop()


def test_stop_cancels_schedule_and_owned_worker() -> None:
    publisher = FakePublisher([PiForgeLocationPublishStatus.PUBLISHED])
    scheduler = ManualScheduler()
    executor = DeferredExecutor()
    service = PiForgeLocationPublishingService(
        publisher,  # type: ignore[arg-type]
        scheduler,
        executor_factory=lambda: executor,
    )

    service.start()
    assert scheduler.poll is not None
    scheduled = scheduler.poll

    service.stop()

    assert scheduled.cancelled is True
    assert executor.shutdown_called is True
    assert executor.cancel_futures is True
    assert service.is_running is False
    assert service.is_publishing is False
