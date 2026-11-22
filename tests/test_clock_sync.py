"""Deterministic tests for bounded GPS-assisted system-clock synchronization."""

import time
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from rolling_thunder.clock_sync import (
    ClockSetError,
    ClockSynchronizationService,
    ClockSyncStatus,
)
from rolling_thunder.domain import GPSFixState, GPSPosition
from rolling_thunder.gps import (
    GPSConnectionState,
    GPSState,
    GPSUTCObservation,
    GPSUTCSource,
)
from rolling_thunder.radio_polling import PollCallback

_BASE_UTC = datetime(2026, 8, 8, 21, 15, 0, tzinfo=UTC)


class MutableMonotonic:
    def __init__(self, value: float = 0.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class MutableWallClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


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


class FakeClockSetter:
    def __init__(self) -> None:
        self.values: list[datetime] = []
        self.error: ClockSetError | None = None

    def set_utc(self, value: datetime) -> None:
        if self.error is not None:
            raise self.error
        self.values.append(value)


class MutableGPSState:
    def __init__(self, state: GPSState | None) -> None:
        self.state = state

    def __call__(self) -> GPSState | None:
        return self.state


def trusted_state(
    value: datetime = _BASE_UTC,
    *,
    received_monotonic_s: float | None = None,
) -> GPSState:
    position = GPSPosition(
        fix_state=GPSFixState.THREE_DIMENSIONAL,
        latitude=39.53,
        longitude=-84.08,
        altitude_m=260.0,
        satellites=10,
        updated_at=_BASE_UTC,
    )
    return GPSState(
        connection_state=GPSConnectionState.CONNECTED,
        position=position,
        updated_at=_BASE_UTC,
        utc=GPSUTCObservation(
            value=value,
            source=GPSUTCSource.RMC,
            valid=True,
            fix_valid=True,
            advancing=True,
            fresh=True,
            age_s=0.2,
            received_monotonic_s=received_monotonic_s,
        ),
    )


def untrusted_state(value: datetime = _BASE_UTC) -> GPSState:
    position = GPSPosition(
        fix_state=GPSFixState.THREE_DIMENSIONAL,
        latitude=39.53,
        longitude=-84.08,
        altitude_m=260.0,
        satellites=10,
        updated_at=_BASE_UTC,
    )
    return GPSState(
        connection_state=GPSConnectionState.CONNECTED,
        position=position,
        updated_at=_BASE_UTC,
        utc=GPSUTCObservation(
            value=value,
            source=GPSUTCSource.RMC,
            valid=True,
            fix_valid=True,
            advancing=False,
            fresh=True,
            age_s=0.2,
        ),
    )


def build_service(
    gps: MutableGPSState,
    monotonic: MutableMonotonic,
    wall: MutableWallClock,
    setter: FakeClockSetter,
    scheduler: ManualScheduler,
) -> ClockSynchronizationService:
    return ClockSynchronizationService(
        gps,
        setter,
        scheduler,
        monotonic_clock=monotonic,
        wall_clock=wall,
    )


def test_start_waits_for_trusted_gps_without_writing_clock() -> None:
    gps = MutableGPSState(None)
    monotonic = MutableMonotonic()
    wall = MutableWallClock(_BASE_UTC)
    setter = FakeClockSetter()
    scheduler = ManualScheduler()
    service = build_service(gps, monotonic, wall, setter, scheduler)

    state = service.start()
    scheduler.fire()

    assert state.status is ClockSyncStatus.WAITING_FOR_TRUST
    assert state.last_result is None
    assert service.latest_state.status is ClockSyncStatus.WAITING_FOR_TRUST
    assert scheduler.interval_s == 1.0
    assert setter.values == []


def test_first_opportunity_requires_sixty_seconds_of_continuous_trust() -> None:
    gps = MutableGPSState(trusted_state())
    monotonic = MutableMonotonic()
    wall = MutableWallClock(_BASE_UTC + timedelta(seconds=1))
    setter = FakeClockSetter()
    scheduler = ManualScheduler()
    service = build_service(gps, monotonic, wall, setter, scheduler)
    service.start()

    scheduler.fire()
    assert service.latest_state.status is ClockSyncStatus.WARMING_UP

    monotonic.advance(59.0)
    scheduler.fire()
    assert service.latest_state.status is ClockSyncStatus.WARMING_UP

    monotonic.advance(1.0)
    scheduler.fire()

    state = service.latest_state
    assert state.status is ClockSyncStatus.VERIFIED
    assert state.offset_s == pytest.approx(-1.0)
    assert state.clock_written is False
    assert state.last_result is not None
    assert state.last_result.status is ClockSyncStatus.VERIFIED
    assert state.last_result.offset_s == pytest.approx(-1.0)
    assert state.last_result.clock_written is False
    assert setter.values == []


def test_receipt_anchor_projects_delayed_gps_sample_to_comparison_time() -> None:
    gps = MutableGPSState(trusted_state(received_monotonic_s=100.0))
    monotonic = MutableMonotonic(100.0)
    wall = MutableWallClock(_BASE_UTC + timedelta(seconds=60.5))
    setter = FakeClockSetter()
    scheduler = ManualScheduler()
    service = build_service(gps, monotonic, wall, setter, scheduler)
    service.start()

    scheduler.fire()
    assert service.latest_state.status is ClockSyncStatus.WARMING_UP

    monotonic.advance(60.0)
    gps.state = trusted_state(
        _BASE_UTC + timedelta(seconds=57),
        received_monotonic_s=157.0,
    )
    scheduler.fire()

    state = service.latest_state
    assert state.status is ClockSyncStatus.VERIFIED
    assert state.gps_utc == _BASE_UTC + timedelta(seconds=60)
    assert state.offset_s == pytest.approx(-0.5)
    assert state.clock_written is False
    assert setter.values == []


def test_receipt_anchor_rejects_sample_that_aged_past_clock_sync_bound() -> None:
    gps = MutableGPSState(trusted_state(received_monotonic_s=100.0))
    monotonic = MutableMonotonic(100.0)
    wall = MutableWallClock(_BASE_UTC + timedelta(seconds=60))
    setter = FakeClockSetter()
    scheduler = ManualScheduler()
    service = build_service(gps, monotonic, wall, setter, scheduler)
    service.start()

    scheduler.fire()
    assert service.latest_state.status is ClockSyncStatus.WARMING_UP

    monotonic.advance(60.0)
    gps.state = trusted_state(
        _BASE_UTC + timedelta(seconds=50),
        received_monotonic_s=150.0,
    )
    scheduler.fire()

    assert service.latest_state.status is ClockSyncStatus.WAITING_FOR_TRUST
    assert setter.values == []


def test_lost_trust_resets_initial_sixty_second_window() -> None:
    gps = MutableGPSState(trusted_state())
    monotonic = MutableMonotonic()
    wall = MutableWallClock(_BASE_UTC)
    setter = FakeClockSetter()
    scheduler = ManualScheduler()
    service = build_service(gps, monotonic, wall, setter, scheduler)
    service.start()

    scheduler.fire()
    monotonic.advance(50.0)
    scheduler.fire()

    gps.state = untrusted_state()
    monotonic.advance(1.0)
    scheduler.fire()
    assert service.latest_state.status is ClockSyncStatus.WAITING_FOR_TRUST

    gps.state = trusted_state()
    monotonic.advance(1.0)
    scheduler.fire()
    assert service.latest_state.status is ClockSyncStatus.WARMING_UP

    monotonic.advance(59.0)
    scheduler.fire()
    assert service.latest_state.status is ClockSyncStatus.WARMING_UP
    assert setter.values == []


def test_out_of_tolerance_clock_is_set_from_trusted_gps() -> None:
    gps = MutableGPSState(trusted_state())
    monotonic = MutableMonotonic()
    wall = MutableWallClock(_BASE_UTC - timedelta(minutes=5))
    setter = FakeClockSetter()
    scheduler = ManualScheduler()
    service = build_service(gps, monotonic, wall, setter, scheduler)
    service.start()

    scheduler.fire()
    monotonic.advance(60.0)
    scheduler.fire()

    state = service.latest_state
    assert setter.values == [_BASE_UTC]
    assert state.status is ClockSyncStatus.SYNCHRONIZED
    assert state.clock_written is True
    assert state.offset_s == pytest.approx(300.0)
    assert state.last_result is not None
    assert state.last_result.status is ClockSyncStatus.SYNCHRONIZED
    assert state.last_result.clock_written is True


def test_clock_set_failure_retries_no_more_often_than_sixty_seconds() -> None:
    gps = MutableGPSState(trusted_state())
    monotonic = MutableMonotonic()
    wall = MutableWallClock(_BASE_UTC - timedelta(minutes=5))
    setter = FakeClockSetter()
    setter.error = ClockSetError("authorization denied")
    scheduler = ManualScheduler()
    service = build_service(gps, monotonic, wall, setter, scheduler)
    service.start()

    scheduler.fire()
    monotonic.advance(60.0)
    scheduler.fire()

    assert service.latest_state.status is ClockSyncStatus.RETRY_PENDING
    assert service.latest_state.last_error == "authorization denied"

    setter.error = None
    monotonic.advance(59.0)
    scheduler.fire()
    assert setter.values == []

    monotonic.advance(1.0)
    scheduler.fire()

    assert setter.values == [_BASE_UTC]
    assert service.latest_state.status is ClockSyncStatus.SYNCHRONIZED


def test_untrusted_gps_during_open_window_is_bounded_retry_not_clock_write() -> None:
    gps = MutableGPSState(trusted_state())
    monotonic = MutableMonotonic()
    wall = MutableWallClock(_BASE_UTC - timedelta(minutes=5))
    setter = FakeClockSetter()
    setter.error = ClockSetError("temporary failure")
    scheduler = ManualScheduler()
    service = build_service(gps, monotonic, wall, setter, scheduler)
    service.start()

    scheduler.fire()
    monotonic.advance(60.0)
    scheduler.fire()
    assert service.latest_state.status is ClockSyncStatus.RETRY_PENDING

    gps.state = untrusted_state()
    setter.error = None
    monotonic.advance(60.0)
    scheduler.fire()

    assert service.latest_state.status is ClockSyncStatus.RETRY_PENDING
    assert service.latest_state.last_error is not None
    assert "Trusted GPS UTC" in service.latest_state.last_error
    assert setter.values == []


def test_retry_window_expires_and_defers_until_next_twelve_hour_opportunity() -> None:
    gps = MutableGPSState(trusted_state())
    monotonic = MutableMonotonic()
    wall = MutableWallClock(_BASE_UTC - timedelta(minutes=5))
    setter = FakeClockSetter()
    setter.error = ClockSetError("authorization denied")
    scheduler = ManualScheduler()
    service = build_service(gps, monotonic, wall, setter, scheduler)
    service.start()

    scheduler.fire()
    monotonic.advance(60.0)
    scheduler.fire()
    assert service.latest_state.status is ClockSyncStatus.RETRY_PENDING

    monotonic.advance(600.0)
    scheduler.fire()
    expired = service.latest_state
    assert expired.status is ClockSyncStatus.WINDOW_EXPIRED
    assert expired.last_result is not None
    assert expired.last_result.status is ClockSyncStatus.WINDOW_EXPIRED

    setter.error = None
    monotonic.advance(1.0)
    scheduler.fire()
    waiting = service.latest_state
    assert waiting.status is ClockSyncStatus.WAITING_FOR_CADENCE
    assert waiting.last_result is not None
    assert waiting.last_result.status is ClockSyncStatus.WINDOW_EXPIRED
    assert setter.values == []

    monotonic.value = 60.0 + 43_200.0
    scheduler.fire()

    assert setter.values == [_BASE_UTC]
    assert service.latest_state.status is ClockSyncStatus.SYNCHRONIZED


def test_successful_verification_defers_next_attempt_and_retains_result() -> None:
    gps = MutableGPSState(trusted_state())
    monotonic = MutableMonotonic()
    wall = MutableWallClock(_BASE_UTC)
    setter = FakeClockSetter()
    scheduler = ManualScheduler()
    service = build_service(gps, monotonic, wall, setter, scheduler)
    service.start()

    scheduler.fire()
    monotonic.advance(60.0)
    scheduler.fire()
    verified = service.latest_state
    assert verified.status is ClockSyncStatus.VERIFIED
    assert verified.last_result is not None
    assert verified.last_result.status is ClockSyncStatus.VERIFIED

    monotonic.advance(1.0)
    scheduler.fire()
    waiting = service.latest_state
    assert waiting.status is ClockSyncStatus.WAITING_FOR_CADENCE
    assert waiting.last_result is not None
    assert waiting.last_result.status is ClockSyncStatus.VERIFIED
    assert waiting.last_result.offset_s == pytest.approx(0.0)
    assert waiting.last_result.clock_written is False

    monotonic.advance(43_198.0)
    scheduler.fire()
    waiting = service.latest_state
    assert waiting.status is ClockSyncStatus.WAITING_FOR_CADENCE
    assert waiting.last_result is not None
    assert waiting.last_result.status is ClockSyncStatus.VERIFIED
    assert setter.values == []


def test_stop_preserves_last_completed_result_for_observation() -> None:
    gps = MutableGPSState(trusted_state())
    monotonic = MutableMonotonic()
    wall = MutableWallClock(_BASE_UTC)
    setter = FakeClockSetter()
    scheduler = ManualScheduler()
    service = build_service(gps, monotonic, wall, setter, scheduler)
    service.start()

    scheduler.fire()
    monotonic.advance(60.0)
    scheduler.fire()
    assert service.latest_state.status is ClockSyncStatus.VERIFIED

    state = service.stop()

    assert state.status is ClockSyncStatus.STOPPED
    assert state.last_result is not None
    assert state.last_result.status is ClockSyncStatus.VERIFIED
    assert state.last_result.clock_written is False


def test_stop_cancels_future_policy_evaluation() -> None:
    gps = MutableGPSState(trusted_state())
    monotonic = MutableMonotonic()
    wall = MutableWallClock(_BASE_UTC)
    setter = FakeClockSetter()
    scheduler = ManualScheduler()
    service = build_service(gps, monotonic, wall, setter, scheduler)
    service.start()

    state = service.stop()
    monotonic.advance(120.0)
    scheduler.fire()

    assert state.status is ClockSyncStatus.STOPPED
    assert service.is_running is False
    assert setter.values == []


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"poll_interval_s": 0.0}, "poll interval"),
        ({"initial_trust_s": 0.0}, "initial trust"),
        ({"retry_interval_s": 0.0}, "retry interval"),
        ({"retry_window_s": 30.0}, "retry window"),
        ({"success_interval_s": 600.0}, "success interval"),
        ({"tolerance_s": -0.1}, "tolerance"),
        ({"maximum_gps_sample_age_s": 0.0}, "maximum GPS sample age"),
    ],
)
def test_policy_configuration_is_validated(
    kwargs: dict[str, float],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        ClockSynchronizationService(
            MutableGPSState(None),
            FakeClockSetter(),
            ManualScheduler(),
            monotonic_clock=MutableMonotonic(),
            **kwargs,
        )


@pytest.fixture
def eastern_timezone(monkeypatch: pytest.MonkeyPatch):
    try:
        with monkeypatch.context() as env:
            env.setenv("TZ", "America/New_York")
            time.tzset()
            yield ZoneInfo("America/New_York")
    finally:
        time.tzset()


@pytest.mark.parametrize("day", [1, 7, 15])
def test_schedule_uses_local_slots_across_eastern_dst(day, eastern_timezone) -> None:
    wall = MutableWallClock(datetime(2026, 3, day, 23, 55, tzinfo=eastern_timezone))
    monotonic = MutableMonotonic()
    gps = MutableGPSState(None)
    setter = FakeClockSetter()
    scheduler = ManualScheduler()
    service = ClockSynchronizationService(
        gps, setter, scheduler, monotonic_clock=monotonic, wall_clock=wall,
        use_local_schedule=True,
    )
    service.start()

    def poll(value: datetime) -> None:
        monotonic.advance((value.astimezone(UTC) - wall.value.astimezone(UTC)).total_seconds())
        wall.value = value
        gps.state = trusted_state(value, received_monotonic_s=monotonic.value)
        scheduler.fire()

    next_day = wall.value + timedelta(days=1)
    for hour in (0, 6, 12, 18):
        target = next_day.replace(hour=hour, minute=0)
        poll(target - timedelta(minutes=2))
        assert service.latest_state.status is ClockSyncStatus.WAITING_FOR_CADENCE
        previous = service.latest_state.last_result
        poll(target)
        result = service.latest_state.last_result
        assert result is not None and result is not previous
        assert result.gps_utc == target.astimezone(UTC)
        assert result.status is ClockSyncStatus.VERIFIED
        poll(target + timedelta(minutes=2))
        assert service.latest_state.last_result is result
    assert setter.values == []


def test_scheduled_sync_defers_writes_and_skips_missed_or_repeated_windows(
    eastern_timezone,
) -> None:
    start = datetime(2026, 11, 1, 5, 57, tzinfo=eastern_timezone)
    wall = MutableWallClock(start)
    monotonic = MutableMonotonic()
    gps = MutableGPSState(trusted_state(start))
    setter = FakeClockSetter()
    scheduler = ManualScheduler()
    radio_busy = True
    service = ClockSynchronizationService(
        gps, setter, scheduler, monotonic_clock=monotonic, wall_clock=wall,
        use_local_schedule=True, clock_write_allowed=lambda: not radio_busy,
    )
    service.start()

    def poll(minute: int, *, available: bool = True) -> None:
        monotonic.advance(60)
        wall.value = start + timedelta(minutes=minute)
        target = wall.value.astimezone(UTC) + timedelta(seconds=5)
        gps.state = trusted_state(target, received_monotonic_s=monotonic.value) if available else None
        scheduler.fire()

    poll(0)
    poll(3)
    assert service.latest_state.status is ClockSyncStatus.RETRY_PENDING
    assert setter.values == []
    radio_busy = False
    poll(4)
    assert service.latest_state.status is ClockSyncStatus.SYNCHRONIZED
    assert len(setter.values) == 1
    poll(3)
    assert len(setter.values) == 1
    service.stop()
    service.start()
    poll(5)
    poll(6)
    assert len(setter.values) == 1

    poll(363, available=False)
    poll(374, available=False)
    poll(375)
    poll(376)
    assert len(setter.values) == 1


def test_schedule_uses_gps_calendar_when_pi_wall_clock_is_wrong(eastern_timezone) -> None:
    start = datetime(2026, 11, 2, 5, 58, tzinfo=eastern_timezone)
    wall = MutableWallClock(start + timedelta(hours=8))
    monotonic = MutableMonotonic()
    gps = MutableGPSState(trusted_state(start, received_monotonic_s=0.0))
    setter = FakeClockSetter()
    scheduler = ManualScheduler()
    service = ClockSynchronizationService(
        gps, setter, scheduler, monotonic_clock=monotonic, wall_clock=wall,
        use_local_schedule=True,
    )
    service.start()
    scheduler.fire()
    assert setter.values == []
    monotonic.advance(120)
    target = start + timedelta(minutes=2)
    gps.state = trusted_state(target, received_monotonic_s=monotonic.value)
    scheduler.fire()
    assert setter.values == [target.astimezone(UTC)]
