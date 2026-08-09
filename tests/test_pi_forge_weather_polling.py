"""Tests for background-only Pi Forge weather polling."""

from collections.abc import Callable
from concurrent.futures import Executor, Future
from datetime import UTC, datetime
from typing import Any, cast

from rolling_thunder.forge_weather_client import ForgeWeatherClientResult
from rolling_thunder.pi_forge_weather_polling import PiForgeWeatherPollingService
from rolling_thunder.pi_forge_weather_service import PiForgeWeatherService
from rolling_thunder.radio_polling import PollCallback

BASE_TIME = datetime(2026, 8, 9, 3, 35, tzinfo=UTC)


class EmptyClient:
    def fetch_weather(self) -> ForgeWeatherClientResult:
        raise AssertionError("refresh should not execute until deferred worker runs")


class EmptyCache:
    def load(self) -> ForgeWeatherClientResult | None:
        return None

    def replace(self, result: ForgeWeatherClientResult) -> None:
        raise AssertionError(f"unexpected cache replacement: {result}")


class ManualScheduledPoll:
    def __init__(self, callback: PollCallback) -> None:
        self.callback = callback
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


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


class DeferredExecutor:
    def __init__(self) -> None:
        self.tasks: list[Callable[[], object]] = []
        self.shutdown_calls: list[tuple[bool, bool]] = []

    def submit(
        self,
        fn: Callable[..., object],
        /,
        *args: Any,
        **kwargs: Any,
    ) -> Future[object]:
        future: Future[object] = Future()

        def run() -> object:
            try:
                value = fn(*args, **kwargs)
            except BaseException as error:
                future.set_exception(error)
                raise
            future.set_result(value)
            return value

        self.tasks.append(run)
        return future

    def shutdown(self, wait: bool = True, *, cancel_futures: bool = False) -> None:
        self.shutdown_calls.append((wait, cancel_futures))
        if cancel_futures:
            self.tasks.clear()

    def run_next(self) -> None:
        self.tasks.pop(0)()


class CountingService(PiForgeWeatherService):
    def __init__(self) -> None:
        super().__init__(EmptyClient(), EmptyCache(), now=lambda: BASE_TIME)
        self.calls = 0

    def refresh(self):  # type: ignore[no-untyped-def]
        self.calls += 1
        return self.get_state()


def test_start_schedules_15_minute_poll_without_running_io_on_caller() -> None:
    service = CountingService()
    scheduler = ManualScheduler()
    executor = DeferredExecutor()
    polling = PiForgeWeatherPollingService(
        service,
        scheduler,
        interval_s=900.0,
        refresh_on_start=True,
        executor_factory=lambda: cast(Executor, executor),
    )

    startup = polling.start()

    assert startup is service.get_state()
    assert scheduler.interval_s == 900.0
    assert service.calls == 0
    assert polling.is_refreshing is True
    assert len(executor.tasks) == 1

    executor.run_next()
    assert service.calls == 1
    assert polling.refresh_count == 1
    assert polling.is_refreshing is False


def test_repeating_callbacks_coalesce_while_worker_is_pending() -> None:
    service = CountingService()
    scheduler = ManualScheduler()
    executor = DeferredExecutor()
    polling = PiForgeWeatherPollingService(
        service,
        scheduler,
        refresh_on_start=False,
        executor_factory=lambda: cast(Executor, executor),
    )
    polling.start()
    assert scheduler.poll is not None

    scheduler.poll.callback()
    scheduler.poll.callback()
    scheduler.poll.callback()

    assert len(executor.tasks) == 1
    executor.run_next()
    assert service.calls == 1


def test_stop_cancels_scheduler_and_owned_worker() -> None:
    service = CountingService()
    scheduler = ManualScheduler()
    executor = DeferredExecutor()
    polling = PiForgeWeatherPollingService(
        service,
        scheduler,
        refresh_on_start=False,
        executor_factory=lambda: cast(Executor, executor),
    )
    polling.start()
    assert scheduler.poll is not None

    polling.stop()

    assert scheduler.poll.cancelled is True
    assert executor.shutdown_calls == [(True, True)]
    assert polling.is_running is False
