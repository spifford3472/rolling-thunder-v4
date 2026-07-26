"""Tests for deterministic Home Station Platform health polling."""

from collections.abc import Callable
from datetime import UTC, datetime

import pytest

from rolling_thunder.home_platform import (
    ContactUploadRequest,
    ContactUploadResult,
    HomePlatformAvailability,
    HomePlatformConnectionError,
    HomePlatformState,
)
from rolling_thunder.home_platform_health import HomePlatformHealthService
from rolling_thunder.radio_polling import PollCallback


def timestamp(minute: int = 0) -> datetime:
    return datetime(2026, 7, 26, 13, minute, tzinfo=UTC)


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


class ScriptedHomePlatformClient:
    def __init__(self) -> None:
        self.state = HomePlatformState(
            availability=HomePlatformAvailability.UNKNOWN,
            checked_at=timestamp(),
        )
        self.check_count = 0
        self.next_state: HomePlatformState | None = None
        self.next_error: HomePlatformConnectionError | None = None
        self.during_check: Callable[[], None] | None = None

    def get_state(self) -> HomePlatformState:
        return self.state

    def check_health(self) -> HomePlatformState:
        self.check_count += 1
        if self.during_check is not None:
            self.during_check()
        if self.next_error is not None:
            error = self.next_error
            self.next_error = None
            raise error
        if self.next_state is not None:
            self.state = self.next_state
        return self.state

    def upload_contact(self, request: ContactUploadRequest) -> ContactUploadResult:
        del request
        raise AssertionError("health polling must not upload contacts")


def available_state(minute: int = 1) -> HomePlatformState:
    return HomePlatformState(
        availability=HomePlatformAvailability.AVAILABLE,
        checked_at=timestamp(minute),
    )


def unavailable_state(minute: int = 2) -> HomePlatformState:
    return HomePlatformState(
        availability=HomePlatformAvailability.UNAVAILABLE,
        checked_at=timestamp(minute),
        last_error="connection refused",
    )


def test_start_schedules_without_immediate_io() -> None:
    client = ScriptedHomePlatformClient()
    scheduler = ManualScheduler()
    service = HomePlatformHealthService(client, scheduler, interval_s=15.0)

    state = service.start()

    assert state.availability is HomePlatformAvailability.UNKNOWN
    assert client.check_count == 0
    assert scheduler.interval_s == 15.0
    assert service.is_running is True


def test_poll_publishes_available_and_unavailable_states() -> None:
    client = ScriptedHomePlatformClient()
    scheduler = ManualScheduler()
    service = HomePlatformHealthService(client, scheduler)
    service.start()
    client.next_state = available_state()

    scheduler.fire()

    assert service.latest_state.availability is HomePlatformAvailability.AVAILABLE
    client.next_state = unavailable_state()
    scheduler.fire()
    assert service.latest_state.availability is HomePlatformAvailability.UNAVAILABLE
    assert service.latest_state.last_error == "connection refused"
    assert service.is_running is True


def test_typed_failure_becomes_unavailable_and_polling_continues() -> None:
    client = ScriptedHomePlatformClient()
    scheduler = ManualScheduler()
    service = HomePlatformHealthService(
        client,
        scheduler,
        clock=lambda: timestamp(3),
    )
    service.start()
    client.next_error = HomePlatformConnectionError("request timed out")

    scheduler.fire()

    assert service.latest_state.availability is HomePlatformAvailability.UNAVAILABLE
    assert service.latest_state.last_error == "request timed out"
    assert service.latest_state.checked_at == timestamp(3)
    assert service.is_running is True


def test_polling_recovers_after_failure() -> None:
    client = ScriptedHomePlatformClient()
    scheduler = ManualScheduler()
    service = HomePlatformHealthService(client, scheduler, clock=lambda: timestamp(3))
    service.start()
    client.next_error = HomePlatformConnectionError("temporary outage")
    scheduler.fire()
    client.next_state = available_state(4)

    scheduler.fire()

    assert service.latest_state.availability is HomePlatformAvailability.AVAILABLE
    assert service.latest_state.last_error is None
    assert service.is_running is True


def test_stop_cancels_future_checks() -> None:
    client = ScriptedHomePlatformClient()
    scheduler = ManualScheduler()
    service = HomePlatformHealthService(client, scheduler)
    service.start()

    service.stop()
    scheduler.fire()

    assert service.is_running is False
    assert client.check_count == 0
    assert scheduler.poll is not None
    assert scheduler.poll.cancelled is True


def test_repeated_start_is_rejected() -> None:
    service = HomePlatformHealthService(
        ScriptedHomePlatformClient(),
        ManualScheduler(),
    )
    service.start()

    with pytest.raises(RuntimeError, match="already running"):
        service.start()


def test_reentrant_callback_does_not_overlap_check() -> None:
    client = ScriptedHomePlatformClient()
    scheduler = ManualScheduler()
    service = HomePlatformHealthService(client, scheduler)
    service.start()
    client.during_check = scheduler.fire

    scheduler.fire()

    assert client.check_count == 1


@pytest.mark.parametrize("interval_s", [0.0, -1.0])
def test_interval_must_be_positive(interval_s: float) -> None:
    with pytest.raises(ValueError, match="must be positive"):
        HomePlatformHealthService(
            ScriptedHomePlatformClient(),
            ManualScheduler(),
            interval_s=interval_s,
        )


def test_error_clock_must_be_timezone_aware() -> None:
    client = ScriptedHomePlatformClient()
    scheduler = ManualScheduler()

    def naive_clock() -> datetime:
        return datetime(2026, 7, 26, 13, 0)  # noqa: DTZ001

    service = HomePlatformHealthService(client, scheduler, clock=naive_clock)
    service.start()
    client.next_error = HomePlatformConnectionError("offline")

    with pytest.raises(ValueError, match="timezone-aware"):
        scheduler.fire()
