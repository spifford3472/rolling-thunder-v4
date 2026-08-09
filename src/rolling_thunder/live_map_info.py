"""Pure information and subsystem-health projection for the live map."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from rolling_thunder.live_map import LiveMapGpsStatus, LiveMapPresentation
from rolling_thunder.live_map_service import LiveMapSnapshot, MapDataStatus
from rolling_thunder.weather_panel import WeatherPanelPresentation


class LiveMapHealthLevel(StrEnum):
    """Small operator-facing health vocabulary for map subsystems."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class LiveMapSubsystemHealth:
    """Typed health for one live-map dependency."""

    level: LiveMapHealthLevel
    detail: str
    last_usable_at: datetime | None
    age: timedelta | None


@dataclass(frozen=True)
class LiveMapInfoPresentation:
    """Immutable information/status-box state consumed by Tkinter."""

    local_time: str
    utc_time: str
    grid: str
    temperature_f: str
    temperature_c: str
    temperature_detail: str
    map_health: LiveMapSubsystemHealth
    gps_health: LiveMapSubsystemHealth


def _local_now() -> datetime:
    return datetime.now().astimezone()


class LiveMapInfoController:
    """Project typed map/GPS/weather snapshots into compact operator information."""

    def __init__(
        self,
        *,
        unavailable_after: timedelta = timedelta(seconds=30),
        clock: Callable[[], datetime] = _local_now,
    ) -> None:
        if unavailable_after <= timedelta(0):
            raise ValueError("Live-map unavailable threshold must be positive.")
        self._unavailable_after = unavailable_after
        self._clock = clock
        self._last_usable_map_at: datetime | None = None

    def update(
        self,
        presentation: LiveMapPresentation,
        snapshot: LiveMapSnapshot | None,
        weather: WeatherPanelPresentation | None = None,
    ) -> LiveMapInfoPresentation:
        """Build one deterministic presentation without performing I/O."""
        now = self._aware_now()
        map_health = self._map_health(snapshot, now)
        gps_health = self._gps_health(presentation, now)
        has_weather = weather is not None and weather.has_data

        return LiveMapInfoPresentation(
            local_time=self._format_local_time(now),
            utc_time=now.astimezone(UTC).strftime("%H:%M UTC"),
            grid=(presentation.grid.upper() if presentation.grid is not None else "------"),
            temperature_f=(weather.temperature_f if has_weather and weather is not None else "--°F"),
            temperature_c=(weather.temperature_c if has_weather and weather is not None else "--°C"),
            temperature_detail=(weather.detail if weather is not None else "UNAVAILABLE"),
            map_health=map_health,
            gps_health=gps_health,
        )

    def _map_health(
        self,
        snapshot: LiveMapSnapshot | None,
        now: datetime,
    ) -> LiveMapSubsystemHealth:
        if snapshot is not None and self._map_snapshot_is_usable(snapshot):
            self._last_usable_map_at = snapshot.updated_at.astimezone(UTC)

        last_usable = self._last_usable_map_at
        age = self._age(now, last_usable)

        if snapshot is None:
            return LiveMapSubsystemHealth(
                level=LiveMapHealthLevel.UNAVAILABLE,
                detail="DISABLED",
                last_usable_at=last_usable,
                age=age,
            )

        if snapshot.status in {MapDataStatus.READY, MapDataStatus.CACHE_ONLY}:
            return LiveMapSubsystemHealth(
                level=LiveMapHealthLevel.HEALTHY,
                detail=(
                    "READY"
                    if snapshot.status is MapDataStatus.READY
                    else "OFFLINE CACHE"
                ),
                last_usable_at=last_usable,
                age=age,
            )

        if snapshot.status is MapDataStatus.PARTIAL:
            return LiveMapSubsystemHealth(
                level=LiveMapHealthLevel.DEGRADED,
                detail="PARTIAL",
                last_usable_at=last_usable,
                age=age,
            )

        if snapshot.status is MapDataStatus.LOADING and any(
            tile.png is not None for tile in snapshot.tiles
        ):
            return LiveMapSubsystemHealth(
                level=LiveMapHealthLevel.DEGRADED,
                detail="LOADING",
                last_usable_at=last_usable,
                age=age,
            )

        return self._unavailable_health(
            detail={
                MapDataStatus.IDLE: "WAITING",
                MapDataStatus.LOADING: "LOADING",
                MapDataStatus.UNAVAILABLE: "UNAVAILABLE",
            }.get(snapshot.status, "UNAVAILABLE"),
            last_usable_at=last_usable,
            age=age,
        )

    def _gps_health(
        self,
        presentation: LiveMapPresentation,
        now: datetime,
    ) -> LiveMapSubsystemHealth:
        last_usable = (
            presentation.fix_time.astimezone(UTC)
            if presentation.fix_time is not None
            else None
        )
        age = self._age(now, last_usable)

        if presentation.status is LiveMapGpsStatus.READY:
            return LiveMapSubsystemHealth(
                level=LiveMapHealthLevel.HEALTHY,
                detail="READY",
                last_usable_at=last_usable,
                age=age,
            )

        if presentation.status in {
            LiveMapGpsStatus.STALE,
            LiveMapGpsStatus.LAST_KNOWN,
        }:
            detail = (
                "STALE"
                if presentation.status is LiveMapGpsStatus.STALE
                else "LAST KNOWN"
            )
            return self._unavailable_health(
                detail=detail,
                last_usable_at=last_usable,
                age=age,
            )

        return LiveMapSubsystemHealth(
            level=LiveMapHealthLevel.UNAVAILABLE,
            detail={
                LiveMapGpsStatus.WAITING: "WAITING",
                LiveMapGpsStatus.ERROR: "ERROR",
            }.get(presentation.status, "UNAVAILABLE"),
            last_usable_at=last_usable,
            age=age,
        )

    def _unavailable_health(
        self,
        *,
        detail: str,
        last_usable_at: datetime | None,
        age: timedelta | None,
    ) -> LiveMapSubsystemHealth:
        level = LiveMapHealthLevel.UNAVAILABLE
        if age is not None and age < self._unavailable_after:
            level = LiveMapHealthLevel.DEGRADED
        return LiveMapSubsystemHealth(
            level=level,
            detail=detail,
            last_usable_at=last_usable_at,
            age=age,
        )

    @staticmethod
    def _map_snapshot_is_usable(snapshot: LiveMapSnapshot) -> bool:
        if snapshot.status in {
            MapDataStatus.READY,
            MapDataStatus.CACHE_ONLY,
            MapDataStatus.PARTIAL,
        }:
            return True
        return snapshot.status is MapDataStatus.LOADING and any(
            tile.png is not None for tile in snapshot.tiles
        )

    @staticmethod
    def _age(now: datetime, timestamp: datetime | None) -> timedelta | None:
        if timestamp is None:
            return None
        return max(timedelta(0), now.astimezone(UTC) - timestamp.astimezone(UTC))

    @staticmethod
    def _format_local_time(now: datetime) -> str:
        return now.strftime("%I:%M %p").lstrip("0")

    def _aware_now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Live-map information clock must return an aware timestamp.")
        return now
