"""Automatic local DAY/NIGHT map style selection from GPS and solar position."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from math import acos, asin, cos, degrees, pi, radians, sin, sqrt
from threading import Lock
from typing import Protocol

from rolling_thunder.domain import GPSFixState
from rolling_thunder.gps import GPSConnectionState, GPSState
from rolling_thunder.live_map import GeoPoint
from rolling_thunder.map_sources import MapPackageStyle
from rolling_thunder.radio_polling import PollScheduler, ScheduledPoll

WallClock = Callable[[], datetime]

_SOLAR_HORIZON_DEGREES = -0.833
_TRANSITION_SCAN_STEP = timedelta(minutes=5)
_TRANSITION_SCAN_HORIZON = timedelta(hours=48)
_DEFAULT_LOCATION_CHANGE_MILES = 25.0
_EARTH_RADIUS_MILES = 3958.7613


class MapStyleTarget(Protocol):
    """In-memory map-style capability used by the solar policy."""

    @property
    def style(self) -> MapPackageStyle:
        ...

    def set_style(self, style: MapPackageStyle) -> bool:
        ...


class PrimaryMapStyleTarget(MapStyleTarget, Protocol):
    """Authoritative map style plus its operator-visible availability."""

    @property
    def available_styles(self) -> tuple[MapPackageStyle, ...]:
        ...


class SynchronizedMapStyleTarget:
    """Apply accepted primary-map styles to zero or more mirror maps."""

    def __init__(
        self,
        primary: PrimaryMapStyleTarget,
        mirrors: Iterable[MapStyleTarget] = (),
    ) -> None:
        self._primary = primary
        self._mirrors = tuple(mirrors)

    @property
    def style(self) -> MapPackageStyle:
        """Return the authoritative primary-map style."""
        return self._primary.style

    @property
    def available_styles(self) -> tuple[MapPackageStyle, ...]:
        """Return only styles advertised by the primary live map."""
        return self._primary.available_styles

    def set_style(self, style: MapPackageStyle) -> bool:
        """Apply one primary-accepted style to the primary and every mirror."""
        available = self._primary.available_styles
        if available and style not in available:
            return False

        changed = self._primary.set_style(style)
        if self._primary.style is not style:
            return False
        for mirror in self._mirrors:
            changed = mirror.set_style(style) or changed
        return changed


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Solar map-style clock must return timezone-aware timestamps.")
    return value.astimezone(UTC)


def solar_elevation_degrees(
    when: datetime,
    latitude: float,
    longitude: float,
) -> float:
    """Approximate apparent solar elevation using NOAA's fractional-year equations."""
    utc = _aware_utc(when)
    days_in_year = 366 if _is_leap_year(utc.year) else 365
    hour = (
        utc.hour
        + utc.minute / 60.0
        + utc.second / 3600.0
        + utc.microsecond / 3_600_000_000.0
    )
    gamma = 2.0 * pi / days_in_year * (utc.timetuple().tm_yday - 1 + (hour - 12.0) / 24.0)

    equation_of_time = 229.18 * (
        0.000075
        + 0.001868 * cos(gamma)
        - 0.032077 * sin(gamma)
        - 0.014615 * cos(2.0 * gamma)
        - 0.040849 * sin(2.0 * gamma)
    )
    declination = (
        0.006918
        - 0.399912 * cos(gamma)
        + 0.070257 * sin(gamma)
        - 0.006758 * cos(2.0 * gamma)
        + 0.000907 * sin(2.0 * gamma)
        - 0.002697 * cos(3.0 * gamma)
        + 0.00148 * sin(3.0 * gamma)
    )

    true_solar_minutes = (hour * 60.0 + equation_of_time + 4.0 * longitude) % 1440.0
    hour_angle = radians(true_solar_minutes / 4.0 - 180.0)
    latitude_rad = radians(latitude)
    cosine_zenith = (
        sin(latitude_rad) * sin(declination)
        + cos(latitude_rad) * cos(declination) * cos(hour_angle)
    )
    cosine_zenith = max(-1.0, min(1.0, cosine_zenith))
    return 90.0 - degrees(acos(cosine_zenith))


def solar_map_style(
    when: datetime,
    latitude: float,
    longitude: float,
) -> MapPackageStyle:
    """Return DAY between apparent sunrise/sunset and NIGHT otherwise."""
    return (
        MapPackageStyle.DAY
        if solar_elevation_degrees(when, latitude, longitude) >= _SOLAR_HORIZON_DEGREES
        else MapPackageStyle.NIGHT
    )


def next_solar_transition(
    when: datetime,
    latitude: float,
    longitude: float,
) -> datetime | None:
    """Find the next apparent sunrise/sunset without a timezone or network dependency."""
    start = _aware_utc(when)
    starting_style = solar_map_style(start, latitude, longitude)
    lower = start
    upper = start + _TRANSITION_SCAN_STEP
    limit = start + _TRANSITION_SCAN_HORIZON

    while upper <= limit:
        if solar_map_style(upper, latitude, longitude) is not starting_style:
            for _ in range(24):
                midpoint = lower + (upper - lower) / 2
                if solar_map_style(midpoint, latitude, longitude) is starting_style:
                    lower = midpoint
                else:
                    upper = midpoint
            return upper
        lower = upper
        upper += _TRANSITION_SCAN_STEP

    return None


class MapSolarStyleService:
    """Apply GPS-based map style and schedule only the next solar transition."""

    def __init__(
        self,
        target: MapStyleTarget,
        scheduler: PollScheduler,
        *,
        stale_after: timedelta,
        wall_clock: WallClock = _utc_now,
        location_change_miles: float = _DEFAULT_LOCATION_CHANGE_MILES,
    ) -> None:
        if stale_after <= timedelta(0):
            raise ValueError("Solar map-style GPS stale threshold must be positive.")
        if location_change_miles <= 0:
            raise ValueError("Solar map-style location threshold must be positive.")
        self._target = target
        self._scheduler = scheduler
        self._stale_after = stale_after
        self._wall_clock = wall_clock
        self._location_change_miles = location_change_miles
        self._lock = Lock()
        self._running = False
        self._position: GeoPoint | None = None
        self._scheduled: ScheduledPoll | None = None
        self._generation = 0
        self._manual_override = False

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._running

    def start(self, initial_gps_state: GPSState | None = None) -> None:
        """Start without blocking; a missing fix simply leaves configured style in place."""
        with self._lock:
            if self._running:
                raise RuntimeError("Solar map-style service is already running.")
            self._running = True
        self.observe_gps_state(initial_gps_state)

    def stop(self) -> None:
        """Cancel the pending one-shot transition."""
        with self._lock:
            self._running = False
            self._generation += 1
            scheduled = self._scheduled
            self._scheduled = None
        if scheduled is not None:
            scheduled.cancel()

    def note_manual_override(self) -> None:
        """Preserve an operator DAY/NIGHT choice until the next real transition."""
        with self._lock:
            if self._running:
                self._manual_override = True

    def observe_gps_state(self, gps_state: GPSState | None) -> None:
        """Reschedule only when an existing GPS update represents meaningful movement."""
        now = _aware_utc(self._wall_clock())
        point = self._usable_point(gps_state, now)
        if point is None:
            return

        with self._lock:
            if not self._running:
                return
            previous = self._position
            if (
                previous is not None
                and _distance_miles(previous, point) < self._location_change_miles
            ):
                return
            self._position = point
            self._generation += 1
            generation = self._generation
            scheduled = self._scheduled
            self._scheduled = None

        if scheduled is not None:
            scheduled.cancel()
        self._apply_and_schedule(point, now, generation, solar_transition=False)

    def _transition_due(self, generation: int) -> None:
        with self._lock:
            if not self._running or generation != self._generation:
                return
            scheduled = self._scheduled
            self._scheduled = None
            self._manual_override = False
            point = self._position
            self._generation += 1
            next_generation = self._generation

        if scheduled is not None:
            # ThreadScheduledPoll.cancel() is safe from its own callback and turns
            # the repeating scheduler primitive into one-shot delivery.
            scheduled.cancel()
        if point is None:
            return
        self._apply_and_schedule(
            point,
            _aware_utc(self._wall_clock()),
            next_generation,
            solar_transition=True,
        )

    def _apply_and_schedule(
        self,
        point: GeoPoint,
        now: datetime,
        generation: int,
        *,
        solar_transition: bool,
    ) -> None:
        desired = solar_map_style(now, point.latitude, point.longitude)
        transition = next_solar_transition(now, point.latitude, point.longitude)

        with self._lock:
            if (
                not self._running
                or generation != self._generation
                or self._position != point
            ):
                return
            manual_override = self._manual_override
            if solar_transition:
                manual_override = False
                self._manual_override = False

            if not manual_override:
                self._target.set_style(desired)

            if transition is None:
                return
            delay_s = max(1.0, (transition - now).total_seconds())
            self._scheduled = self._scheduler.schedule_repeating(
                delay_s,
                lambda: self._transition_due(generation),
            )

    def _usable_point(self, gps_state: GPSState | None, now: datetime) -> GeoPoint | None:
        if gps_state is None or gps_state.connection_state is not GPSConnectionState.CONNECTED:
            return None
        position = gps_state.position
        if (
            position is None
            or position.fix_state is GPSFixState.NO_FIX
            or position.latitude is None
            or position.longitude is None
        ):
            return None
        age = now - position.updated_at.astimezone(UTC)
        if age > self._stale_after:
            return None
        return GeoPoint(position.latitude, position.longitude)


def _distance_miles(first: GeoPoint, second: GeoPoint) -> float:
    lat1 = radians(first.latitude)
    lat2 = radians(second.latitude)
    delta_lat = lat2 - lat1
    delta_lon = radians(second.longitude - first.longitude)
    a = (
        sin(delta_lat / 2.0) ** 2
        + cos(lat1) * cos(lat2) * sin(delta_lon / 2.0) ** 2
    )
    return 2.0 * _EARTH_RADIUS_MILES * asin(min(1.0, sqrt(a)))


def _is_leap_year(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
