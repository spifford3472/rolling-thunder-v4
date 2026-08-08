"""Tests for background-only Pi Forge shared-spot polling."""

from __future__ import annotations

from concurrent.futures import Executor, Future
from datetime import UTC, datetime
from threading import Event, get_ident
from typing import Any

from rolling_thunder.domain import Frequency, RadioMode
from rolling_thunder.forge_client import (
    ForgeRemoteProviderHealth,
    ForgeRemoteProviderStatus,
    ForgeSpotClientResult,
)
from rolling_thunder.pi_forge_spot_polling import PiForgeSpotPollingService
from rolling_thunder.pi_forge_spot_service import PiForgeSpotService
from rolling_thunder.radio_polling import PollCallback
from rolling_thunder.spot_domain import (
    DxSpotIdentity,
    SpotProvider,
    SpotRecord,
    SpotSnapshot,
)


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


class FakeCache:
    def __init__(self) -> None:
        self.value: ForgeSpotClientResult | None = None
        self.replacements = 0

    def load(self) -> ForgeSpotClientResult | None:
        return self.value

    def replace(self, result: ForgeSpotClientResult) -> None:
        self.value = result
        self.replacements += 1


class RecordingClient:
    def __init__(
        self,
        result: ForgeSpotClientResult,
        *,
        entered: Event | None = None,
        release: Event | None = None,
    ) -> None:
        self.result = result
        self.entered = entered
        self.release = release
        self.calls = 0
        self.thread_ids: list[int] = []

    def fetch_spots(self) -> ForgeSpotClientResult:
        self.calls += 1
        self.thread_ids.append(get_ident())
        if self.entered is not None:
            self.entered.set()
        if self.release is not None:
            assert self.release.wait(timeout=2.0)
        return self.result


class DeferredExecutor(Executor):
    """Executor that queues submitted work until the test explicitly runs it."""

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
            except Exception as error:  # noqa: BLE001 - mirror Executor Future semantics
                future.set_exception(error)
            else:
                future.set_result(result)


def forge_result(revision: int = 1) -> ForgeSpotClientResult:
    generated_at = datetime(2026, 8, 7, 20, 0, tzinfo=UTC)
    frequency = Frequency(hz=14_074_000)
    snapshot = SpotSnapshot.from_spots(
        generated_at=generated_at,
        spots=(
            SpotRecord(
                identity=DxSpotIdentity(callsign="K1ABC", frequency=frequency),
                callsign="K1ABC",
                frequency=frequency,
                mode=RadioMode.DATA,
                display_mode="FT8",
                spotted_at=generated_at,
            ),
        ),
    )
    return ForgeSpotClientResult(
        snapshot_revision=revision,
        snapshot=snapshot,
        providers=(
            ForgeRemoteProviderHealth(
                provider=SpotProvider.DX,
                status=ForgeRemoteProviderStatus.HEALTHY,
                active_spot_count=1,
                last_attempt_at=generated_at,
                last_success_at=generated_at,
            ),
        ),
        received_at=datetime(2026, 8, 7, 20, 0, 1, tzinfo=UTC),
    )


def test_immediate_refresh_runs_on_default_background_worker() -> None:
    entered = Event()
    client = RecordingClient(forge_result(), entered=entered)
    service = PiForgeSpotService(client, FakeCache())
    scheduler = ManualScheduler()
    polling = PiForgeSpotPollingService(
        service,
        scheduler,
        interval_s=60.0,
        refresh_on_start=True,
    )
    caller_thread = get_ident()

    startup_state = polling.start()

    assert startup_state.snapshot is None
    assert entered.wait(timeout=2.0)
    assert client.thread_ids
    assert client.thread_ids[0] != caller_thread
    polling.stop()
    assert polling.refresh_count == 1


def test_start_queues_immediate_refresh_without_running_it_inline() -> None:
    client = RecordingClient(forge_result())
    service = PiForgeSpotService(client, FakeCache())
    scheduler = ManualScheduler()
    executor = DeferredExecutor()
    polling = PiForgeSpotPollingService(
        service,
        scheduler,
        interval_s=30.0,
        refresh_on_start=True,
        executor_factory=lambda: executor,
    )

    state = polling.start()

    assert state.snapshot is None
    assert client.calls == 0
    assert len(executor.jobs) == 1
    assert polling.is_refreshing is True
    assert scheduler.interval_s == 30.0

    executor.run_next()

    assert client.calls == 1
    assert polling.latest_state.snapshot_revision == 1
    assert polling.refresh_count == 1
    assert polling.is_refreshing is False
    polling.stop()


def test_periodic_callbacks_do_not_queue_overlapping_refreshes() -> None:
    client = RecordingClient(forge_result())
    service = PiForgeSpotService(client, FakeCache())
    scheduler = ManualScheduler()
    executor = DeferredExecutor()
    polling = PiForgeSpotPollingService(
        service,
        scheduler,
        refresh_on_start=True,
        executor_factory=lambda: executor,
    )

    polling.start()
    assert scheduler.poll is not None
    assert len(executor.jobs) == 1

    scheduler.poll.fire()
    scheduler.poll.fire()

    assert len(executor.jobs) == 1
    assert client.calls == 0

    executor.run_next()
    assert polling.is_refreshing is False

    scheduler.poll.fire()
    assert len(executor.jobs) == 1
    executor.run_next()

    assert client.calls == 2
    assert polling.refresh_count == 2
    polling.stop()


def test_refresh_on_start_false_waits_for_periodic_callback() -> None:
    client = RecordingClient(forge_result())
    service = PiForgeSpotService(client, FakeCache())
    scheduler = ManualScheduler()
    executor = DeferredExecutor()
    polling = PiForgeSpotPollingService(
        service,
        scheduler,
        refresh_on_start=False,
        executor_factory=lambda: executor,
    )

    polling.start()

    assert executor.jobs == []
    assert client.calls == 0
    assert scheduler.poll is not None

    scheduler.poll.fire()
    assert len(executor.jobs) == 1
    executor.run_next()
    assert client.calls == 1
    polling.stop()


def test_stop_cancels_schedule_and_owned_worker() -> None:
    service = PiForgeSpotService(RecordingClient(forge_result()), FakeCache())
    scheduler = ManualScheduler()
    executor = DeferredExecutor()
    polling = PiForgeSpotPollingService(
        service,
        scheduler,
        executor_factory=lambda: executor,
    )

    polling.start()
    assert scheduler.poll is not None
    scheduled = scheduler.poll

    polling.stop()

    assert scheduled.cancelled is True
    assert executor.shutdown_called is True
    assert executor.cancel_futures is True
    assert polling.is_running is False
    assert polling.is_refreshing is False


def test_polling_service_can_restart_with_fresh_executor() -> None:
    service = PiForgeSpotService(RecordingClient(forge_result()), FakeCache())
    scheduler = ManualScheduler()
    executors: list[DeferredExecutor] = []

    def executor_factory() -> Executor:
        executor = DeferredExecutor()
        executors.append(executor)
        return executor

    polling = PiForgeSpotPollingService(
        service,
        scheduler,
        refresh_on_start=False,
        executor_factory=executor_factory,
    )

    polling.start()
    polling.stop()
    polling.start()

    assert len(executors) == 2
    assert executors[0].shutdown_called is True
    assert polling.is_running is True
    polling.stop()
