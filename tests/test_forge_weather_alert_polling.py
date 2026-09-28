"""Tests for non-overlapping background Forge weather-alert refresh lifecycle."""

from collections.abc import Callable
from concurrent.futures import Executor, Future
from typing import Any, cast

import pytest

from rolling_thunder.forge_weather_alert_polling import (
    ForgeWeatherAlertPollingService,
)
from rolling_thunder.forge_weather_alerts import (
    ForgeWeatherAlertService,
    ForgeWeatherAlertState,
)
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


class FakeAlertService:
    def __init__(self) -> None:
        self.state = ForgeWeatherAlertState(revision=0)
        self.refreshes = 0

    def get_state(self) -> ForgeWeatherAlertState:
        return self.state

    def refresh(self) -> ForgeWeatherAlertState:
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


def test_start_queues_one_refresh_and_scheduled_checks_never_overlap() -> None:
    scheduler = ManualScheduler()
    executor = DeferredExecutor()
    service = FakeAlertService()
    polling = ForgeWeatherAlertPollingService(
        cast(ForgeWeatherAlertService, service),
        scheduler,
        check_interval_s=30.0,
        refresh_on_start=True,
        executor_factory=lambda: cast(Executor, executor),
    )

    polling.start()

    assert polling.is_running is True
    assert polling.is_refreshing is True
    assert scheduler.interval_s == 30.0
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
    executor.run_next()
    assert polling.refresh_count == 2
    assert service.refreshes == 2


def test_stop_cancels_scheduler_and_owned_executor() -> None:
    scheduler = ManualScheduler()
    executor = DeferredExecutor()
    polling = ForgeWeatherAlertPollingService(
        cast(ForgeWeatherAlertService, FakeAlertService()),
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


def test_polling_rejects_intervals_faster_than_nws_guidance() -> None:
    with pytest.raises(ValueError, match="at least 30 seconds"):
        ForgeWeatherAlertPollingService(
            cast(ForgeWeatherAlertService, FakeAlertService()),
            ManualScheduler(),
            check_interval_s=29.9,
        )
