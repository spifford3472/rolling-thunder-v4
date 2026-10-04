"""Tests for the explicit Forge spot polling lifecycle."""

from collections.abc import Callable
from datetime import UTC, datetime

import pytest

from rolling_thunder.forge_spot_aggregation import (
    ForgeAggregationState,
    ForgeProviderHealth,
    ForgeProviderHealthStatus,
)
from rolling_thunder.forge_spot_polling import ForgeSpotPollingService
from rolling_thunder.radio_polling import PollCallback
from rolling_thunder.spot_domain import SpotProvider, SpotSnapshot

BASE_TIME = datetime(2026, 8, 5, 20, 0, tzinfo=UTC)


class ManualScheduledPoll:
    def __init__(self, callback: PollCallback) -> None:
        self.callback = callback
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


class RecordingScheduler:
    def __init__(self) -> None:
        self.intervals: list[float] = []
        self.polls: list[ManualScheduledPoll] = []

    def schedule_repeating(
        self,
        interval_s: float,
        callback: PollCallback,
    ) -> ManualScheduledPoll:
        self.intervals.append(interval_s)
        poll = ManualScheduledPoll(callback)
        self.polls.append(poll)
        return poll


class RecordingAggregationService:
    def __init__(self) -> None:
        self.refresh_count = 0
        self.on_refresh: Callable[[], None] | None = None
        self.state = state_for_revision(0)

    def get_state(self) -> ForgeAggregationState:
        return self.state

    def refresh_all(self) -> ForgeAggregationState:
        self.refresh_count += 1
        callback = self.on_refresh
        if callback is not None:
            callback()
        self.state = state_for_revision(self.refresh_count)
        return self.state

    def refresh_provider(self, provider: SpotProvider) -> ForgeAggregationState:
        assert provider is SpotProvider.DX
        self.refresh_count += 1
        self.state = state_for_revision(self.refresh_count)
        return self.state


def state_for_revision(revision: int) -> ForgeAggregationState:
    status = (
        ForgeProviderHealthStatus.STARTING
        if revision == 0
        else ForgeProviderHealthStatus.HEALTHY
    )
    return ForgeAggregationState(
        revision=revision,
        snapshot=SpotSnapshot.empty(generated_at=BASE_TIME),
        providers=(
            ForgeProviderHealth(
                provider=SpotProvider.POTA,
                status=status,
                active_spot_count=0,
                last_attempt_at=BASE_TIME if revision else None,
                last_success_at=BASE_TIME if revision else None,
            ),
        ),
    )


def test_polling_interval_must_be_positive() -> None:
    service = RecordingAggregationService()
    with pytest.raises(ValueError, match="positive"):
        ForgeSpotPollingService(service, RecordingScheduler(), interval_s=0)  # type: ignore[arg-type]


def test_start_without_immediate_refresh_only_schedules() -> None:
    service = RecordingAggregationService()
    scheduler = RecordingScheduler()
    polling = ForgeSpotPollingService(  # type: ignore[arg-type]
        service,
        scheduler,
        interval_s=45,
        refresh_on_start=False,
    )

    state = polling.start()

    assert state.revision == 0
    assert service.refresh_count == 0
    assert scheduler.intervals == [45]
    assert polling.is_running is True
    assert polling.is_refreshing is False


def test_start_with_immediate_refresh_publishes_result_before_scheduling() -> None:
    service = RecordingAggregationService()
    scheduler = RecordingScheduler()
    polling = ForgeSpotPollingService(  # type: ignore[arg-type]
        service,
        scheduler,
        interval_s=30,
        refresh_on_start=True,
    )

    state = polling.start()

    assert state.revision == 1
    assert polling.latest_state.revision == 1
    assert service.refresh_count == 1
    assert polling.refresh_count == 1
    assert scheduler.intervals == [30]


def test_scheduled_callback_refreshes_and_stop_cancels_future_delivery() -> None:
    service = RecordingAggregationService()
    scheduler = RecordingScheduler()
    polling = ForgeSpotPollingService(  # type: ignore[arg-type]
        service,
        scheduler,
        refresh_on_start=False,
    )
    polling.start()

    scheduler.polls[0].callback()
    stopped = polling.stop()
    scheduler.polls[0].callback()

    assert stopped.revision == 1
    assert service.refresh_count == 1
    assert polling.refresh_count == 1
    assert polling.is_running is False
    assert scheduler.polls[0].cancelled is True


def test_reentrant_scheduled_callback_does_not_overlap() -> None:
    service = RecordingAggregationService()
    scheduler = RecordingScheduler()
    polling = ForgeSpotPollingService(  # type: ignore[arg-type]
        service,
        scheduler,
        refresh_on_start=False,
    )
    polling.start()
    service.on_refresh = scheduler.polls[0].callback

    scheduler.polls[0].callback()

    assert service.refresh_count == 1
    assert polling.refresh_count == 1
    assert polling.is_refreshing is False


def test_dx_cache_publication_uses_independent_fast_local_cadence() -> None:
    service = RecordingAggregationService()
    scheduler = RecordingScheduler()
    polling = ForgeSpotPollingService(  # type: ignore[arg-type]
        service,
        scheduler,
        interval_s=60,
        dx_cache_publish_interval_s=5,
        refresh_on_start=False,
    )

    polling.start()

    assert scheduler.intervals == [60, 5]

    scheduler.polls[1].callback()

    assert service.refresh_count == 1
    assert polling.latest_state.revision == 1


def test_stop_cancels_full_and_dx_cache_pollers() -> None:
    service = RecordingAggregationService()
    scheduler = RecordingScheduler()
    polling = ForgeSpotPollingService(  # type: ignore[arg-type]
        service,
        scheduler,
        interval_s=60,
        dx_cache_publish_interval_s=5,
        refresh_on_start=False,
    )

    polling.start()
    polling.stop()

    assert len(scheduler.polls) == 2
    assert scheduler.polls[0].cancelled is True
    assert scheduler.polls[1].cancelled is True


def test_start_rejects_duplicate_lifecycle_start() -> None:
    service = RecordingAggregationService()
    polling = ForgeSpotPollingService(  # type: ignore[arg-type]
        service,
        RecordingScheduler(),
        refresh_on_start=False,
    )
    polling.start()

    with pytest.raises(RuntimeError, match="already running"):
        polling.start()
