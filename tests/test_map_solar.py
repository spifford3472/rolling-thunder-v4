"""Tests for GPS-driven automatic DAY/NIGHT map style policy."""

from datetime import UTC, datetime, timedelta

from rolling_thunder.domain import GPSFixState, GPSPosition
from rolling_thunder.gps import GPSConnectionState, GPSState
from rolling_thunder.map_solar import (
    MapSolarStyleService,
    next_solar_transition,
    solar_map_style,
)
from rolling_thunder.map_sources import MapPackageStyle
from rolling_thunder.radio_polling import PollCallback

LATITUDE = 39.53
LONGITUDE = -84.09


class ManualScheduledPoll:
    def __init__(self, interval_s: float, callback: PollCallback) -> None:
        self.interval_s = interval_s
        self.callback = callback
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True

    def fire(self) -> None:
        if not self.cancelled:
            self.callback()


class ManualScheduler:
    def __init__(self) -> None:
        self.polls: list[ManualScheduledPoll] = []

    def schedule_repeating(
        self,
        interval_s: float,
        callback: PollCallback,
    ) -> ManualScheduledPoll:
        poll = ManualScheduledPoll(interval_s, callback)
        self.polls.append(poll)
        return poll


class FakeMapStyleTarget:
    def __init__(self, style: MapPackageStyle) -> None:
        self._style = style
        self.requests: list[MapPackageStyle] = []

    @property
    def style(self) -> MapPackageStyle:
        return self._style

    def set_style(self, style: MapPackageStyle) -> bool:
        self.requests.append(style)
        if self._style is style:
            return False
        self._style = style
        return True


def gps_state(
    when: datetime,
    *,
    latitude: float = LATITUDE,
    longitude: float = LONGITUDE,
) -> GPSState:
    position = GPSPosition(
        fix_state=GPSFixState.THREE_DIMENSIONAL,
        latitude=latitude,
        longitude=longitude,
        altitude_m=260.0,
        satellites=9,
        updated_at=when,
    )
    return GPSState(
        connection_state=GPSConnectionState.CONNECTED,
        position=position,
        updated_at=when,
    )


def test_ohio_summer_midday_and_night_choose_expected_styles() -> None:
    assert solar_map_style(
        datetime(2026, 6, 21, 17, 0, tzinfo=UTC),
        LATITUDE,
        LONGITUDE,
    ) is MapPackageStyle.DAY
    assert solar_map_style(
        datetime(2026, 6, 21, 6, 0, tzinfo=UTC),
        LATITUDE,
        LONGITUDE,
    ) is MapPackageStyle.NIGHT


def test_next_transition_is_one_real_style_change() -> None:
    now = datetime(2026, 6, 21, 17, 0, tzinfo=UTC)
    transition = next_solar_transition(now, LATITUDE, LONGITUDE)

    assert transition is not None
    assert now < transition < now + timedelta(hours=12)
    assert solar_map_style(
        transition + timedelta(minutes=1),
        LATITUDE,
        LONGITUDE,
    ) is not solar_map_style(now, LATITUDE, LONGITUDE)


def test_first_valid_fix_applies_style_and_schedules_only_next_transition() -> None:
    now = datetime(2026, 6, 21, 17, 0, tzinfo=UTC)
    scheduler = ManualScheduler()
    target = FakeMapStyleTarget(MapPackageStyle.NIGHT)
    service = MapSolarStyleService(
        target,
        scheduler,
        stale_after=timedelta(seconds=10),
        wall_clock=lambda: now,
    )

    service.start(gps_state(now))

    assert target.style is MapPackageStyle.DAY
    assert target.requests == [MapPackageStyle.DAY]
    assert len(scheduler.polls) == 1
    assert scheduler.polls[0].interval_s > 0


def test_missing_gps_is_safe_and_does_not_schedule() -> None:
    now = datetime(2026, 6, 21, 17, 0, tzinfo=UTC)
    scheduler = ManualScheduler()
    target = FakeMapStyleTarget(MapPackageStyle.NIGHT)
    service = MapSolarStyleService(
        target,
        scheduler,
        stale_after=timedelta(seconds=10),
        wall_clock=lambda: now,
    )

    service.start(None)

    assert service.is_running is True
    assert target.style is MapPackageStyle.NIGHT
    assert scheduler.polls == []


def test_meaningful_location_change_replaces_transition_but_small_motion_does_not() -> None:
    now = datetime(2026, 6, 21, 17, 0, tzinfo=UTC)
    scheduler = ManualScheduler()
    target = FakeMapStyleTarget(MapPackageStyle.NIGHT)
    service = MapSolarStyleService(
        target,
        scheduler,
        stale_after=timedelta(seconds=10),
        wall_clock=lambda: now,
        location_change_miles=25.0,
    )
    service.start(gps_state(now))
    first_poll = scheduler.polls[-1]

    service.observe_gps_state(
        gps_state(now, latitude=39.54, longitude=-84.08)
    )
    assert scheduler.polls[-1] is first_poll
    assert first_poll.cancelled is False

    service.observe_gps_state(
        gps_state(now, latitude=40.10, longitude=-83.60)
    )

    assert first_poll.cancelled is True
    assert len(scheduler.polls) == 2


def test_manual_override_survives_location_reschedule_until_solar_transition() -> None:
    clock = [datetime(2026, 6, 21, 17, 0, tzinfo=UTC)]
    scheduler = ManualScheduler()
    target = FakeMapStyleTarget(MapPackageStyle.NIGHT)
    service = MapSolarStyleService(
        target,
        scheduler,
        stale_after=timedelta(seconds=10),
        wall_clock=lambda: clock[0],
        location_change_miles=25.0,
    )
    service.start(gps_state(clock[0]))
    target.set_style(MapPackageStyle.NIGHT)
    target.requests.clear()
    service.note_manual_override()

    moved_latitude = 40.10
    moved_longitude = -83.60
    service.observe_gps_state(
        gps_state(
            clock[0],
            latitude=moved_latitude,
            longitude=moved_longitude,
        )
    )

    assert target.style is MapPackageStyle.NIGHT
    assert target.requests == []
    transition_poll = scheduler.polls[-1]

    clock[0] += timedelta(seconds=transition_poll.interval_s + 60)
    transition_poll.fire()

    assert target.requests
    assert target.requests[-1] is solar_map_style(
        clock[0],
        moved_latitude,
        moved_longitude,
    )
    assert transition_poll.cancelled is True


def test_stop_cancels_pending_transition() -> None:
    now = datetime(2026, 6, 21, 17, 0, tzinfo=UTC)
    scheduler = ManualScheduler()
    service = MapSolarStyleService(
        FakeMapStyleTarget(MapPackageStyle.NIGHT),
        scheduler,
        stale_after=timedelta(seconds=10),
        wall_clock=lambda: now,
    )
    service.start(gps_state(now))
    poll = scheduler.polls[-1]

    service.stop()

    assert service.is_running is False
    assert poll.cancelled is True
