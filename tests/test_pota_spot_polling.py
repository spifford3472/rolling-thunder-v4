"""Tests for controlled deterministic POTA spot polling."""

from datetime import UTC, datetime

import pytest

from rolling_thunder.pota_spot_polling import PotaSpotPollingService
from rolling_thunder.pota_spot_service import PotaSpotService, PotaSpotServiceState
from rolling_thunder.pota_spot_source import PotaSpotSourceAvailability
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

    def fire(self) -> None:
        assert self.poll is not None
        self.poll.fire()


class ScriptedPotaSpotService(PotaSpotService):
    def __init__(self) -> None:
        self.state = unknown_state()
        self.refresh_calls = 0
        self.next_state: PotaSpotServiceState | None = None
        self.during_refresh: PollCallback | None = None

    def get_state(self) -> PotaSpotServiceState:
        return self.state

    def refresh(self) -> PotaSpotServiceState:
        self.refresh_calls += 1
        if self.during_refresh is not None:
            self.during_refresh()
        if self.next_state is not None:
            self.state = self.next_state
        return self.state


def timestamp(minute: int = 0) -> datetime:
    return datetime(2026, 7, 26, 18, minute, tzinfo=UTC)


def unknown_state() -> PotaSpotServiceState:
    return PotaSpotServiceState(
        availability=PotaSpotSourceAvailability.UNKNOWN,
    )


def available_state(minute: int = 0) -> PotaSpotServiceState:
    observed_at = timestamp(minute)
    return PotaSpotServiceState(
        availability=PotaSpotSourceAvailability.AVAILABLE,
        last_attempt_at=observed_at,
        last_success_at=observed_at,
    )


def unavailable_state(minute: int = 0) -> PotaSpotServiceState:
    return PotaSpotServiceState(
        availability=PotaSpotSourceAvailability.UNAVAILABLE,
        last_attempt_at=timestamp(minute),
        last_error="POTA source unavailable",
    )


def test_start_refreshes_immediately_and_schedules_interval() -> None:
    pota_service = ScriptedPotaSpotService()
    pota_service.next_state = available_state()
    scheduler = ManualScheduler()
    polling = PotaSpotPollingService(pota_service, scheduler, interval_s=45.0)

    state = polling.start()

    assert state.availability is PotaSpotSourceAvailability.AVAILABLE
    assert polling.is_running is True
    assert polling.refresh_count == 1
    assert pota_service.refresh_calls == 1
    assert scheduler.interval_s == 45.0


def test_start_can_defer_first_refresh() -> None:
    pota_service = ScriptedPotaSpotService()
    scheduler = ManualScheduler()
    polling = PotaSpotPollingService(
        pota_service,
        scheduler,
        refresh_on_start=False,
    )

    state = polling.start()

    assert state.availability is PotaSpotSourceAvailability.UNKNOWN
    assert polling.refresh_count == 0
    assert pota_service.refresh_calls == 0
    assert polling.is_running is True


def test_scheduled_callback_refreshes_latest_state() -> None:
    pota_service = ScriptedPotaSpotService()
    scheduler = ManualScheduler()
    polling = PotaSpotPollingService(
        pota_service,
        scheduler,
        refresh_on_start=False,
    )
    polling.start()
    pota_service.next_state = available_state(1)

    scheduler.fire()

    assert polling.latest_state == available_state(1)
    assert polling.refresh_count == 1
    assert pota_service.refresh_calls == 1


def test_source_failure_state_does_not_stop_polling() -> None:
    pota_service = ScriptedPotaSpotService()
    scheduler = ManualScheduler()
    polling = PotaSpotPollingService(
        pota_service,
        scheduler,
        refresh_on_start=False,
    )
    polling.start()
    pota_service.next_state = unavailable_state(2)

    scheduler.fire()

    assert polling.latest_state.availability is PotaSpotSourceAvailability.UNAVAILABLE
    assert polling.latest_state.last_error == "POTA source unavailable"
    assert polling.refresh_count == 1
    assert polling.is_running is True


def test_stop_cancels_future_refreshes() -> None:
    pota_service = ScriptedPotaSpotService()
    scheduler = ManualScheduler()
    polling = PotaSpotPollingService(
        pota_service,
        scheduler,
        refresh_on_start=False,
    )
    polling.start()

    state = polling.stop()
    scheduler.fire()

    assert state.availability is PotaSpotSourceAvailability.UNKNOWN
    assert polling.is_running is False
    assert scheduler.poll is not None
    assert scheduler.poll.cancelled is True
    assert pota_service.refresh_calls == 0


def test_stop_is_idempotent() -> None:
    polling = PotaSpotPollingService(
        ScriptedPotaSpotService(),
        ManualScheduler(),
        refresh_on_start=False,
    )

    first_state = polling.stop()
    second_state = polling.stop()

    assert first_state == second_state
    assert polling.is_running is False


def test_repeated_start_is_rejected() -> None:
    polling = PotaSpotPollingService(
        ScriptedPotaSpotService(),
        ManualScheduler(),
        refresh_on_start=False,
    )
    polling.start()

    with pytest.raises(RuntimeError, match="already running"):
        polling.start()


def test_reentrant_callback_does_not_overlap_refresh() -> None:
    pota_service = ScriptedPotaSpotService()
    scheduler = ManualScheduler()
    polling = PotaSpotPollingService(
        pota_service,
        scheduler,
        refresh_on_start=False,
    )
    polling.start()
    pota_service.during_refresh = scheduler.fire

    scheduler.fire()

    assert pota_service.refresh_calls == 1
    assert polling.refresh_count == 1
    assert polling.is_refreshing is False


@pytest.mark.parametrize("interval_s", [0.0, -1.0])
def test_polling_interval_must_be_positive(interval_s: float) -> None:
    with pytest.raises(ValueError, match="must be positive"):
        PotaSpotPollingService(
            ScriptedPotaSpotService(),
            ManualScheduler(),
            interval_s=interval_s,
        )
