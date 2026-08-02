"""Pure GPS presentation state for the persistent live map."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from rolling_thunder.domain import GPSFixState
from rolling_thunder.gps import GPSConnectionState, GPSState
from rolling_thunder.maidenhead import maidenhead_grid


class LiveMapGpsStatus(StrEnum):
    """Operator-facing GPS status for the live-map presentation."""

    WAITING = "waiting"
    READY = "ready"
    STALE = "stale"
    LAST_KNOWN = "last_known"
    ERROR = "error"


@dataclass(frozen=True)
class GeoPoint:
    """One validated latitude/longitude position."""

    latitude: float
    longitude: float

    def __post_init__(self) -> None:
        if not -90 <= self.latitude <= 90:
            raise ValueError("Latitude must be between -90 and 90 degrees.")
        if not -180 <= self.longitude <= 180:
            raise ValueError("Longitude must be between -180 and 180 degrees.")


@dataclass(frozen=True)
class LiveMapPresentation:
    """Immutable GPS-facing presentation state for the live-map widget."""

    status: LiveMapGpsStatus
    position: GeoPoint | None
    grid: str | None
    detail: str
    fix_time: datetime | None
    is_current: bool
    heading_degrees: float | None = None


def _utc_now() -> datetime:
    return datetime.now(UTC)


class LiveMapController:
    """Retain the last valid fix without ever presenting stale data as current."""

    def __init__(
        self,
        *,
        stale_after: timedelta = timedelta(seconds=10),
        minimum_heading_speed_m_s: float = 0.9,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        if stale_after <= timedelta(0):
            raise ValueError("Live-map GPS stale threshold must be positive.")
        if minimum_heading_speed_m_s < 0:
            raise ValueError("Minimum heading speed cannot be negative.")
        self._stale_after = stale_after
        self._minimum_heading_speed_m_s = minimum_heading_speed_m_s
        self._clock = clock
        self._last_position: GeoPoint | None = None
        self._last_fix_time: datetime | None = None
        self._last_heading_degrees: float | None = None

    def update(self, gps_state: GPSState | None) -> LiveMapPresentation:
        """Build current map presentation from one immutable GPS snapshot."""
        now = self._aware_now()
        current = self._valid_position(gps_state)
        if current is not None:
            position, fix_time = current
            if self._last_fix_time is None or fix_time >= self._last_fix_time:
                self._last_position = position
                self._last_fix_time = fix_time
                self._retain_reliable_heading(gps_state)

            age = max(timedelta(0), now - fix_time)
            if age <= self._stale_after:
                return self._presentation(
                    LiveMapGpsStatus.READY,
                    position,
                    "GPS READY",
                    fix_time,
                    is_current=True,
                )
            return self._presentation(
                LiveMapGpsStatus.STALE,
                position,
                f"GPS STALE — LAST FIX {self._format_age(age)} AGO",
                fix_time,
                is_current=False,
            )

        if self._last_position is not None and self._last_fix_time is not None:
            reason = self._unavailable_reason(gps_state)
            return self._presentation(
                LiveMapGpsStatus.LAST_KNOWN,
                self._last_position,
                f"{reason} — LAST KNOWN POSITION",
                self._last_fix_time,
                is_current=False,
            )

        if gps_state is not None and gps_state.connection_state is GPSConnectionState.ERROR:
            return LiveMapPresentation(
                status=LiveMapGpsStatus.ERROR,
                position=None,
                grid=None,
                detail="GPS ERROR — POSITION UNAVAILABLE",
                fix_time=None,
                is_current=False,
            )

        return LiveMapPresentation(
            status=LiveMapGpsStatus.WAITING,
            position=None,
            grid=None,
            detail=self._unavailable_reason(gps_state),
            fix_time=None,
            is_current=False,
        )

    def _presentation(
        self,
        status: LiveMapGpsStatus,
        position: GeoPoint,
        detail: str,
        fix_time: datetime,
        *,
        is_current: bool,
    ) -> LiveMapPresentation:
        return LiveMapPresentation(
            status=status,
            position=position,
            grid=maidenhead_grid(position.latitude, position.longitude),
            detail=detail,
            fix_time=fix_time,
            is_current=is_current,
            heading_degrees=self._last_heading_degrees,
        )

    def _retain_reliable_heading(self, gps_state: GPSState | None) -> None:
        if gps_state is None or gps_state.position is None:
            return
        position = gps_state.position
        if (
            position.speed_m_s is None
            or position.heading_degrees is None
            or position.speed_m_s < self._minimum_heading_speed_m_s
        ):
            return
        self._last_heading_degrees = position.heading_degrees

    @staticmethod
    def _valid_position(
        gps_state: GPSState | None,
    ) -> tuple[GeoPoint, datetime] | None:
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
            GeoPoint(
                latitude=gps_state.position.latitude,
                longitude=gps_state.position.longitude,
            ),
            gps_state.position.updated_at,
        )

    @staticmethod
    def _unavailable_reason(gps_state: GPSState | None) -> str:
        if gps_state is None:
            return "GPS DISABLED"
        if gps_state.connection_state is GPSConnectionState.ERROR:
            return "GPS ERROR"
        if gps_state.connection_state is GPSConnectionState.DISCONNECTED:
            return "GPS DISCONNECTED"
        return "WAITING FOR GPS FIX"

    @staticmethod
    def _format_age(age: timedelta) -> str:
        seconds = max(0, int(age.total_seconds()))
        if seconds < 60:
            return f"{seconds} SECONDS"
        minutes, remaining_seconds = divmod(seconds, 60)
        if minutes < 60:
            return f"{minutes}M {remaining_seconds:02d}S"
        hours, remaining_minutes = divmod(minutes, 60)
        return f"{hours}H {remaining_minutes:02d}M"

    def _aware_now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Live-map clock must return timezone-aware timestamps.")
        return now.astimezone(UTC)
