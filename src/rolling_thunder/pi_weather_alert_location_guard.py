"""Pure local-GPS guard for location-aware retained weather alerts."""

from __future__ import annotations

from collections.abc import Callable
from math import asin, cos, radians, sin, sqrt
from time import monotonic

from rolling_thunder.domain import GPSFixState
from rolling_thunder.forge_weather_alerts import (
    WeatherAlertApplicability,
)
from rolling_thunder.gps import GPSConnectionState, GPSState
from rolling_thunder.pi_forge_weather_alert_service import (
    PiForgeWeatherAlertErrorKind,
    PiForgeWeatherAlertState,
    PiForgeWeatherAlertStateKind,
)

GPSStateSource = Callable[[], GPSState]
MonotonicClock = Callable[[], float]

_EARTH_RADIUS_M = 6_371_000.0


class PiWeatherAlertLocationGuard:
    """Downgrade Forge applicability unless current local GPS still supports it."""

    def __init__(
        self,
        state_source: GPSStateSource,
        *,
        monotonic_clock: MonotonicClock = monotonic,
        maximum_gps_sample_age_s: float = 5.0,
        maximum_snapshot_age_s: float = 60.0,
        location_publish_interval_s: float = 15.0,
        base_position_tolerance_m: float = 100.0,
    ) -> None:
        for value, name in (
            (
                maximum_gps_sample_age_s,
                "maximum GPS sample age",
            ),
            (
                maximum_snapshot_age_s,
                "maximum alert snapshot age",
            ),
            (
                location_publish_interval_s,
                "location publication interval",
            ),
            (
                base_position_tolerance_m,
                "base position tolerance",
            ),
        ):
            if value <= 0:
                raise ValueError(
                    f"Weather-alert {name} must be positive."
                )

        self._state_source = state_source
        self._monotonic_clock = monotonic_clock
        self._maximum_gps_sample_age_s = (
            maximum_gps_sample_age_s
        )
        self._maximum_snapshot_age_s = maximum_snapshot_age_s
        self._location_publish_interval_s = (
            location_publish_interval_s
        )
        self._base_position_tolerance_m = (
            base_position_tolerance_m
        )

    def apply(
        self,
        state: PiForgeWeatherAlertState,
    ) -> PiForgeWeatherAlertState:
        """Return state with current local location authority applied."""
        if not state.is_verified_current:
            return state

        gps_state = self._state_source()
        reason = self._unverified_reason(
            state,
            gps_state,
        )

        if reason is None:
            return state

        return self._downgrade(
            state,
            reason=reason,
        )

    def _unverified_reason(
        self,
        state: PiForgeWeatherAlertState,
        gps_state: GPSState,
    ) -> str | None:
        if (
            gps_state.connection_state
            is not GPSConnectionState.CONNECTED
        ):
            return "Current GPS is not connected."

        position = gps_state.position

        if position is None:
            return "Current GPS position is unavailable."

        if position.fix_state is GPSFixState.NO_FIX:
            return "Current GPS does not have a valid fix."

        if (
            position.latitude is None
            or position.longitude is None
        ):
            return "Current GPS position is missing coordinates."

        utc = gps_state.utc

        if not utc.trusted or utc.value is None:
            return "Current GPS UTC is not trusted."

        received_monotonic = utc.received_monotonic_s

        if received_monotonic is None:
            return "Current GPS UTC receipt time is unavailable."

        sample_age_s = (
            self._monotonic_clock() - received_monotonic
        )

        if sample_age_s < 0:
            return "Current GPS UTC receipt time is in the future."

        if sample_age_s > self._maximum_gps_sample_age_s:
            return "Current GPS sample is stale."

        snapshot = state.snapshot
        assert snapshot is not None

        snapshot_age_s = (
            utc.value - snapshot.fetched_at
        ).total_seconds()

        if snapshot_age_s < -5.0:
            return "Forge alert snapshot is later than trusted GPS UTC."

        if snapshot_age_s > self._maximum_snapshot_age_s:
            return "Forge alert snapshot is too old for current applicability."

        distance_m = self._distance_m(
            position.latitude,
            position.longitude,
            snapshot.latitude,
            snapshot.longitude,
        )

        speed_m_s = position.speed_m_s or 0.0
        accuracy_m = position.accuracy_m or 0.0

        plausible_elapsed_s = (
            max(snapshot_age_s, 0.0)
            + self._location_publish_interval_s
        )

        maximum_plausible_distance_m = (
            self._base_position_tolerance_m
            + accuracy_m
            + speed_m_s * plausible_elapsed_s
        )

        if distance_m > maximum_plausible_distance_m:
            return (
                "Forge alert query point no longer matches "
                "the current GPS position."
            )

        return None

    @staticmethod
    def _downgrade(
        state: PiForgeWeatherAlertState,
        *,
        reason: str,
    ) -> PiForgeWeatherAlertState:
        assert state.snapshot is not None
        assert state.snapshot_revision is not None
        assert state.last_success_at is not None

        return PiForgeWeatherAlertState(
            kind=PiForgeWeatherAlertStateKind.RETAINED,
            snapshot_revision=state.snapshot_revision,
            snapshot=state.snapshot,
            health=state.health,
            applicability=(
                WeatherAlertApplicability.RETAINED_UNVERIFIED
            ),
            last_attempt_at=state.last_attempt_at,
            last_success_at=state.last_success_at,
            error_kind=(
                PiForgeWeatherAlertErrorKind.LOCATION_UNVERIFIED
            ),
            last_error=reason,
        )

    @staticmethod
    def _distance_m(
        latitude_a: float,
        longitude_a: float,
        latitude_b: float,
        longitude_b: float,
    ) -> float:
        lat_a = radians(latitude_a)
        lat_b = radians(latitude_b)

        delta_lat = lat_b - lat_a
        delta_lon = radians(longitude_b - longitude_a)

        haversine = (
            sin(delta_lat / 2.0) ** 2
            + cos(lat_a)
            * cos(lat_b)
            * sin(delta_lon / 2.0) ** 2
        )

        return (
            2.0
            * _EARTH_RADIUS_M
            * asin(min(1.0, sqrt(haversine)))
        )
