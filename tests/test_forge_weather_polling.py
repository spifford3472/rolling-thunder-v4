"""Tests for non-overlapping background Forge weather refresh lifecycle."""

from collections.abc import Callable
from concurrent.futures import Executor, Future
from typing import Any, cast

from rolling_thunder.forge_weather import ForgeWeatherService, ForgeWeatherState
from rolling_thunder.forge_weather_polling import ForgeWeatherPollingService
from rolling_thunder.radio_polling import PollCallback


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


class FakeWeatherService:
    def __init__(self) -> None:
        self.state = ForgeWeatherState(revision=0)
        self.refreshes = 0

    def get_state(self) -> ForgeWeatherState:
        return self.state

    def refresh_if_needed(self) -> ForgeWeatherState:
        self.refreshes += 1
        return self.state


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
                result = fn(*args, **kwargs)
            except BaseException as error:
                future.set_exception(error)
                raise
            else:
                future.set_result(result)
                return result

        self.tasks.append(run)
        return future

    def shutdown(self, wait: bool = True, *, cancel_futures: bool = False) -> None:
        self.shutdown_calls.append((wait, cancel_futures))
        if cancel_futures:
            self.tasks.clear()

    def run_next(self) -> None:
        task = self.tasks.pop(0)
        task()


def test_start_queues_background_refresh_and_prevents_overlap() -> None:
    scheduler = ManualScheduler()
    executor = DeferredExecutor()
    service = FakeWeatherService()
    polling = ForgeWeatherPollingService(
        cast(ForgeWeatherService, service),
        scheduler,
        check_interval_s=60.0,
        refresh_on_start=True,
        executor_factory=lambda: cast(Executor, executor),
    )

    polling.start()

    assert polling.is_running is True
    assert polling.is_refreshing is True
    assert scheduler.interval_s == 60.0
    assert len(executor.tasks) == 1
    assert service.refreshes == 0

    assert scheduler.poll is not None
    scheduler.poll.callback()
    assert len(executor.tasks) == 1

    executor.run_next()
    assert polling.is_refreshing is False
    assert polling.refresh_count == 1
    assert service.refreshes == 1

    scheduler.poll.callback()
    assert len(executor.tasks) == 1


def test_stop_cancels_scheduler_and_owned_executor() -> None:
    scheduler = ManualScheduler()
    executor = DeferredExecutor()
    polling = ForgeWeatherPollingService(
        cast(ForgeWeatherService, FakeWeatherService()),
        scheduler,
        refresh_on_start=False,
        executor_factory=lambda: cast(Executor, executor),
    )

    polling.start()
    polling.stop()

    assert polling.is_running is False
    assert polling.is_refreshing is False
    assert scheduler.poll is not None
    assert scheduler.poll.cancelled is True
    assert executor.shutdown_calls == [(True, True)]
