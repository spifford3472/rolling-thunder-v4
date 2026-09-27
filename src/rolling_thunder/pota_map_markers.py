"""Background viewport queries for POTA catalog map markers."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from concurrent.futures import Executor, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock

from rolling_thunder.live_map import GeoPoint
from rolling_thunder.map_tiles import MapViewport, web_mercator_world_pixel


@dataclass(frozen=True)
class PotaMapMarker:
    """One catalog park occurrence eligible for map presentation."""

    reference: str
    name: str
    latitude: float
    longitude: float


@dataclass(frozen=True)
class PotaMapMarkerSnapshot:
    """Immutable visible POTA markers for one exact map viewport."""

    viewport: MapViewport | None
    markers: tuple[PotaMapMarker, ...]
    detail: str
    updated_at: datetime


@dataclass(frozen=True)
class PotaMarkerPlacement:
    """One POTA marker projected into viewport pixel coordinates."""

    marker: PotaMapMarker
    x_px: float
    y_px: float


def _utc_now() -> datetime:
    return datetime.now(UTC)


def viewport_bounds(viewport: MapViewport) -> tuple[float, float, float, float]:
    """Return south, west, north, east bounds for a non-antimeridian viewport."""
    center_x, center_y = web_mercator_world_pixel(viewport.center, viewport.zoom)
    world_size = 256 * (1 << viewport.zoom)
    left_x = center_x - viewport.width_px / 2.0
    right_x = center_x + viewport.width_px / 2.0
    top_y = center_y - viewport.height_px / 2.0
    bottom_y = center_y + viewport.height_px / 2.0

    def longitude(world_x: float) -> float:
        return world_x / world_size * 360.0 - 180.0

    import math

    def latitude(world_y: float) -> float:
        mercator = math.pi * (1.0 - 2.0 * world_y / world_size)
        return math.degrees(math.atan(math.sinh(mercator)))

    return latitude(bottom_y), longitude(left_x), latitude(top_y), longitude(right_x)


def project_pota_marker(
    marker: PotaMapMarker,
    viewport: MapViewport,
) -> PotaMarkerPlacement:
    """Project one catalog coordinate using the base map's Web Mercator transform."""
    center_x, center_y = web_mercator_world_pixel(viewport.center, viewport.zoom)
    marker_x, marker_y = web_mercator_world_pixel(
        GeoPoint(marker.latitude, marker.longitude),
        viewport.zoom,
    )
    world_size = 256 * (1 << viewport.zoom)
    delta_x = marker_x - center_x
    if delta_x > world_size / 2:
        delta_x -= world_size
    elif delta_x < -world_size / 2:
        delta_x += world_size
    return PotaMarkerPlacement(
        marker=marker,
        x_px=viewport.width_px / 2.0 + delta_x,
        y_px=viewport.height_px / 2.0 + (marker_y - center_y),
    )


class PotaMapMarkerService:
    """Query only visible POTA catalog rows on one bounded background worker."""

    def __init__(
        self,
        database_path: Path,
        *,
        clock: Callable[[], datetime] = _utc_now,
        executor: Executor | None = None,
    ) -> None:
        self._database_path = database_path
        self._clock = clock
        self._executor = executor
        self._owns_executor = executor is None
        self._started = False
        self._lock = Lock()
        self._generation = 0
        self._pending_viewport: MapViewport | None = None
        self._latest = PotaMapMarkerSnapshot(
            viewport=None,
            markers=(),
            detail="POTA MARKERS IDLE",
            updated_at=self._aware_now(),
        )

    @property
    def latest_state(self) -> PotaMapMarkerSnapshot:
        """Return immutable state without disk I/O."""
        with self._lock:
            return self._latest

    def start(self) -> None:
        """Start the dedicated single worker."""
        if self._started:
            raise RuntimeError("POTA map marker service is already running.")
        if self._executor is None:
            self._executor = ThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix="rolling-thunder-pota-map",
            )
        self._started = True

    def stop(self) -> None:
        """Stop accepting work without blocking the Tkinter thread."""
        self._started = False
        executor = self._executor
        if executor is not None and self._owns_executor:
            executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None

    def request_viewport(self, viewport: MapViewport) -> None:
        """Schedule a visible-park query, coalescing identical viewport requests."""
        if not self._started:
            return
        with self._lock:
            if viewport == self._pending_viewport or viewport == self._latest.viewport:
                return
            self._generation += 1
            generation = self._generation
            self._pending_viewport = viewport
        executor = self._executor
        if executor is not None:
            executor.submit(self._load_viewport, viewport, generation)

    def _load_viewport(self, viewport: MapViewport, generation: int) -> None:
        try:
            markers = self._query(viewport)
            detail = f"POTA MARKERS READY — {len(markers)} VISIBLE"
        except (OSError, sqlite3.Error, ValueError) as error:
            markers = ()
            detail = f"POTA MARKERS UNAVAILABLE — {error}"

        snapshot = PotaMapMarkerSnapshot(
            viewport=viewport,
            markers=markers,
            detail=detail,
            updated_at=self._aware_now(),
        )
        with self._lock:
            if generation != self._generation:
                return
            self._pending_viewport = None
            self._latest = snapshot

    def _query(self, viewport: MapViewport) -> tuple[PotaMapMarker, ...]:
        south, west, north, east = viewport_bounds(viewport)
        if west < -180.0 or east > 180.0:
            # Rolling Thunder's normal operating area is far from the antimeridian.
            # Keep the query conservative rather than inventing wrapped bounds.
            west = max(-180.0, west)
            east = min(180.0, east)
        uri = f"{self._database_path.resolve().as_uri()}?mode=ro"
        with sqlite3.connect(uri, uri=True) as connection:
            rows = connection.execute(
                """
                SELECT reference, name, latitude, longitude
                FROM parks
                WHERE latitude BETWEEN ? AND ?
                  AND longitude BETWEEN ? AND ?
                  AND status != 'inactive'
                GROUP BY reference, name, latitude, longitude
                ORDER BY reference
                """,
                (south, north, west, east),
            ).fetchall()
        return tuple(
            PotaMapMarker(
                reference=str(reference),
                name=str(name),
                latitude=float(latitude),
                longitude=float(longitude),
            )
            for reference, name, latitude, longitude in rows
        )

    def _aware_now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("POTA map marker clock must return aware timestamps.")
        return now.astimezone(UTC)
