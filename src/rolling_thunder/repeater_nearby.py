"""Pure GPS-aware nearby filtering for the local six-meter repeater catalog."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from math import asin, cos, radians, sin, sqrt

from rolling_thunder.domain import GPSFixState
from rolling_thunder.gps import GPSConnectionState, GPSState
from rolling_thunder.repeater_domain import RepeaterCatalog, RepeaterRecord

EARTH_RADIUS_MILES = 3_958.7613
DEFAULT_REPEATER_RADIUS_MILES = 50.0
DEFAULT_REPEATER_GPS_STALE_AFTER = timedelta(seconds=10)


class NearbyRepeaterStateKind(StrEnum):
    """Whether current GPS can support truthful nearby-repeater filtering."""

    READY = "ready"
    GPS_UNAVAILABLE = "gps_unavailable"
    GPS_STALE = "gps_stale"


@dataclass(frozen=True, slots=True)
class NearbyRepeater:
    """One distance-qualified repeater with effective operator Active state."""

    repeater: RepeaterRecord
    distance_miles: float
    effective_active: bool


@dataclass(frozen=True, slots=True)
class NearbyRepeaterState:
    """Immutable nearby-filter result for later UI/controller consumption."""

    kind: NearbyRepeaterStateKind
    repeaters: tuple[NearbyRepeater, ...] = ()
    gps_fix_time: datetime | None = None
    detail: str = ""

    @property
    def available(self) -> bool:
        """Return whether distance filtering is based on a current GPS fix."""
        return self.kind is NearbyRepeaterStateKind.READY


def haversine_distance_miles(
    latitude_a: float,
    longitude_a: float,
    latitude_b: float,
    longitude_b: float,
) -> float:
    """Return great-circle distance in statute miles using the Haversine formula."""
    latitude_delta = radians(latitude_b - latitude_a)
    longitude_delta = radians(longitude_b - longitude_a)
    latitude_a_rad = radians(latitude_a)
    latitude_b_rad = radians(latitude_b)

    haversine = (
        sin(latitude_delta / 2) ** 2
        + cos(latitude_a_rad)
        * cos(latitude_b_rad)
        * sin(longitude_delta / 2) ** 2
    )
    central_angle = 2 * asin(min(1.0, sqrt(haversine)))
    return EARTH_RADIUS_MILES * central_angle


def nearby_repeater_order_key(
    item: NearbyRepeater,
) -> tuple[float, int, str]:
    """Apply deterministic distance/frequency/identity ordering."""
    return (
        item.distance_miles,
        item.repeater.rx_frequency.hz,
        item.repeater.stable_key,
    )


class RepeaterNearbyService:
    """Apply stored Active overrides and current-GPS 50-mile eligibility."""

    def __init__(
        self,
        catalog: RepeaterCatalog,
        *,
        overrides: Mapping[str, bool] | None = None,
        maximum_distance_miles: float = DEFAULT_REPEATER_RADIUS_MILES,
        gps_stale_after: timedelta = DEFAULT_REPEATER_GPS_STALE_AFTER,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if maximum_distance_miles <= 0:
            raise ValueError("maximum repeater distance must be positive")
        if gps_stale_after <= timedelta(0):
            raise ValueError("repeater GPS stale threshold must be positive")
        self._catalog = catalog
        self._overrides = dict(overrides or {})
        self._maximum_distance_miles = maximum_distance_miles
        self._gps_stale_after = gps_stale_after
        self._clock = clock or (lambda: datetime.now(UTC))

    def replace_overrides(self, overrides: Mapping[str, bool]) -> None:
        """Replace the in-memory effective-Active overlay without mutating source data."""
        self._overrides = dict(overrides)

    def set_override(self, stable_key: str, active: bool) -> None:
        """Apply one already-persisted Active override to in-memory state only."""
        self._overrides[stable_key] = active

    def effective_active(self, repeater: RepeaterRecord) -> bool:
        """Return stored override when present, otherwise immutable source default."""
        return self._overrides.get(repeater.stable_key, repeater.source_active)

    def nearby(self, gps_state: GPSState | None) -> NearbyRepeaterState:
        """Return canonically ordered repeaters within radius of a current GPS fix."""
        now = self._aware_now()
        current = self._current_position(gps_state)
        if current is None:
            return NearbyRepeaterState(
                kind=NearbyRepeaterStateKind.GPS_UNAVAILABLE,
                detail=self._unavailable_detail(gps_state),
            )

        latitude, longitude, fix_time = current
        age = max(timedelta(0), now - fix_time)
        if age > self._gps_stale_after:
            return NearbyRepeaterState(
                kind=NearbyRepeaterStateKind.GPS_STALE,
                gps_fix_time=fix_time,
                detail="GPS STALE — NEARBY REPEATERS UNAVAILABLE",
            )

        repeaters = []
        for repeater in self._catalog.repeaters:
            distance = haversine_distance_miles(
                latitude,
                longitude,
                repeater.location.latitude,
                repeater.location.longitude,
            )
            if distance <= self._maximum_distance_miles:
                repeaters.append(
                    NearbyRepeater(
                        repeater=repeater,
                        distance_miles=distance,
                        effective_active=self.effective_active(repeater),
                    )
                )

        return NearbyRepeaterState(
            kind=NearbyRepeaterStateKind.READY,
            repeaters=tuple(sorted(repeaters, key=nearby_repeater_order_key)),
            gps_fix_time=fix_time,
            detail=f"{len(repeaters)} REPEATERS WITHIN {self._maximum_distance_miles:g} MILES",
        )

    @staticmethod
    def _current_position(
        gps_state: GPSState | None,
    ) -> tuple[float, float, datetime] | None:
        if (
            gps_state is None
            or gps_state.connection_state is not GPSConnectionState.CONNECTED
            or gps_state.position is None
            or gps_state.position.fix_state is GPSFixState.NO_FIX
            or gps_state.position.latitude is None
            or gps_state.position.longitude is None
        ):
            return None
        return (
            gps_state.position.latitude,
            gps_state.position.longitude,
            gps_state.position.updated_at,
        )

    @staticmethod
    def _unavailable_detail(gps_state: GPSState | None) -> str:
        if gps_state is None:
            return "GPS DISABLED — NEARBY REPEATERS UNAVAILABLE"
        if gps_state.connection_state is GPSConnectionState.ERROR:
            return "GPS ERROR — NEARBY REPEATERS UNAVAILABLE"
        if gps_state.connection_state is GPSConnectionState.DISCONNECTED:
            return "GPS DISCONNECTED — NEARBY REPEATERS UNAVAILABLE"
        return "WAITING FOR GPS FIX — NEARBY REPEATERS UNAVAILABLE"

    def _aware_now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("repeater clock must return timezone-aware timestamps")
        return now.astimezone(UTC)
