"""Background map-tile loading and immutable viewport snapshots."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Executor, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from threading import Lock

from rolling_thunder.live_map import GeoPoint
from rolling_thunder.map_tiles import (
    MapTileCache,
    MapTileClient,
    MapTileError,
    MapTileKey,
    MapTilePlacement,
    MapViewport,
    build_map_viewport,
)


class MapDataStatus(StrEnum):
    """Availability state for the current map viewport."""

    IDLE = "idle"
    LOADING = "loading"
    READY = "ready"
    CACHE_ONLY = "cache_only"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class MapTileSource(StrEnum):
    """Origin or availability of one rendered tile."""

    NETWORK = "network"
    CACHE = "cache"
    STALE_CACHE = "stale_cache"
    MISSING = "missing"


@dataclass(frozen=True)
class MapTileSnapshot:
    """One viewport placement and its optional validated PNG bytes."""

    placement: MapTilePlacement
    png: bytes | None
    source: MapTileSource


@dataclass(frozen=True)
class LiveMapSnapshot:
    """Immutable background map-data state consumed by Tkinter."""

    status: MapDataStatus
    viewport: MapViewport | None
    tiles: tuple[MapTileSnapshot, ...]
    detail: str
    updated_at: datetime


@dataclass(frozen=True)
class _LoadedTile:
    png: bytes | None
    source: MapTileSource


def _utc_now() -> datetime:
    return datetime.now(UTC)


class LiveMapService:
    """Own one bounded worker for visible map-tile cache and HTTP work."""

    def __init__(
        self,
        tile_client: MapTileClient,
        cache: MapTileCache,
        *,
        zoom: int = 13,
        clock: Callable[[], datetime] = _utc_now,
        executor: Executor | None = None,
    ) -> None:
        if not 0 <= zoom <= 22:
            raise ValueError("Live-map zoom must be between 0 and 22.")
        self._tile_client = tile_client
        self._cache = cache
        self._zoom = zoom
        self._clock = clock
        self._executor = executor
        self._owns_executor = executor is None
        self._started = False
        self._lock = Lock()
        self._pending_keyset: tuple[MapTileKey, ...] | None = None
        self._pending_viewport: MapViewport | None = None
        self._queued_viewport: MapViewport | None = None
        self._latest = LiveMapSnapshot(
            status=MapDataStatus.IDLE,
            viewport=None,
            tiles=(),
            detail="WAITING FOR GPS FIX",
            updated_at=self._aware_now(),
        )

    @property
    def is_running(self) -> bool:
        """Return whether viewport work may be submitted."""
        return self._started

    @property
    def latest_state(self) -> LiveMapSnapshot:
        """Return the latest immutable map-data snapshot without performing I/O."""
        with self._lock:
            return self._latest

    def start(self) -> None:
        """Start the single bounded background map worker."""
        if self._started:
            raise RuntimeError("Live map service is already running.")
        if self._executor is None:
            self._executor = ThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix="rolling-thunder-live-map",
            )
        self._started = True

    def stop(self) -> None:
        """Stop accepting work and cancel queued work without blocking the UI."""
        if not self._started:
            return
        self._started = False
        executor = self._executor
        if executor is not None and self._owns_executor:
            executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None
        with self._lock:
            self._pending_keyset = None
            self._pending_viewport = None
            self._queued_viewport = None

    def request_viewport(
        self,
        center: GeoPoint,
        *,
        width_px: int,
        height_px: int,
    ) -> None:
        """Request the centered visible viewport without blocking the caller."""
        if not self._started:
            return

        viewport = build_map_viewport(
            center,
            zoom=self._zoom,
            width_px=max(1, width_px),
            height_px=max(1, height_px),
        )
        keyset = viewport.tile_keys
        submit_viewport: MapViewport | None = None

        with self._lock:
            if self._pending_keyset is not None:
                if keyset == self._pending_keyset:
                    self._pending_viewport = viewport
                else:
                    self._queued_viewport = viewport
                return

            existing = self._tiles_by_key(self._latest)
            if keyset and all(
                key in existing and existing[key].png is not None for key in keyset
            ):
                self._latest = self._reframe_snapshot(
                    self._latest,
                    viewport,
                    existing,
                )
                return

            self._pending_keyset = keyset
            self._pending_viewport = viewport
            self._latest = LiveMapSnapshot(
                status=MapDataStatus.LOADING,
                viewport=viewport,
                tiles=self._reuse_tiles(viewport, existing),
                detail="LOADING MAP DATA",
                updated_at=self._aware_now(),
            )
            submit_viewport = viewport

        self._submit(submit_viewport)

    def _submit(self, viewport: MapViewport | None) -> None:
        if viewport is None or not self._started:
            return
        executor = self._executor
        if executor is None:
            return
        executor.submit(self._load_viewport, viewport)

    def _load_viewport(self, requested_viewport: MapViewport) -> None:
        loaded: dict[MapTileKey, _LoadedTile] = {}
        for key in requested_viewport.tile_keys:
            loaded[key] = self._load_tile(key)

        next_viewport: MapViewport | None = None
        with self._lock:
            if not self._started:
                return

            publish_viewport = self._pending_viewport or requested_viewport
            if publish_viewport.tile_keys != requested_viewport.tile_keys:
                publish_viewport = requested_viewport

            self._latest = self._build_snapshot(publish_viewport, loaded)
            self._pending_keyset = None
            self._pending_viewport = None

            queued = self._queued_viewport
            self._queued_viewport = None
            if queued is not None:
                if queued.tile_keys == requested_viewport.tile_keys:
                    self._latest = self._build_snapshot(queued, loaded)
                else:
                    self._pending_keyset = queued.tile_keys
                    self._pending_viewport = queued
                    self._latest = LiveMapSnapshot(
                        status=MapDataStatus.LOADING,
                        viewport=queued,
                        tiles=self._reuse_tiles(
                            queued,
                            self._tiles_by_key(self._latest),
                        ),
                        detail="LOADING MAP DATA",
                        updated_at=self._aware_now(),
                    )
                    next_viewport = queued

        self._submit(next_viewport)

    def _load_tile(self, key: MapTileKey) -> _LoadedTile:
        cached = self._cache.read(key)
        if cached is not None and cached.is_fresh:
            return _LoadedTile(cached.png, MapTileSource.CACHE)

        stale_png = cached.png if cached is not None else None
        try:
            png = self._tile_client.fetch(key)
            self._cache.write(key, png)
            return _LoadedTile(png, MapTileSource.NETWORK)
        except MapTileError:
            if stale_png is not None:
                return _LoadedTile(stale_png, MapTileSource.STALE_CACHE)
            return _LoadedTile(None, MapTileSource.MISSING)

    def _build_snapshot(
        self,
        viewport: MapViewport,
        loaded: dict[MapTileKey, _LoadedTile],
    ) -> LiveMapSnapshot:
        tiles = tuple(
            MapTileSnapshot(
                placement=placement,
                png=loaded[placement.key].png,
                source=loaded[placement.key].source,
            )
            for placement in viewport.placements
        )
        sources = {tile.source for tile in tiles}
        available_count = sum(tile.png is not None for tile in tiles)

        if tiles and available_count == len(tiles):
            if MapTileSource.STALE_CACHE in sources:
                status = MapDataStatus.CACHE_ONLY
                detail = "MAP DATA OFFLINE — USING CACHE"
            else:
                status = MapDataStatus.READY
                detail = "MAP READY"
        elif available_count:
            status = MapDataStatus.PARTIAL
            detail = "MAP DATA PARTIAL"
        else:
            status = MapDataStatus.UNAVAILABLE
            detail = "MAP DATA UNAVAILABLE"

        return LiveMapSnapshot(
            status=status,
            viewport=viewport,
            tiles=tiles,
            detail=detail,
            updated_at=self._aware_now(),
        )

    def _reframe_snapshot(
        self,
        snapshot: LiveMapSnapshot,
        viewport: MapViewport,
        existing: dict[MapTileKey, MapTileSnapshot],
    ) -> LiveMapSnapshot:
        return LiveMapSnapshot(
            status=snapshot.status,
            viewport=viewport,
            tiles=tuple(
                MapTileSnapshot(
                    placement=placement,
                    png=existing[placement.key].png,
                    source=existing[placement.key].source,
                )
                for placement in viewport.placements
            ),
            detail=snapshot.detail,
            updated_at=self._aware_now(),
        )

    @staticmethod
    def _reuse_tiles(
        viewport: MapViewport,
        existing: dict[MapTileKey, MapTileSnapshot],
    ) -> tuple[MapTileSnapshot, ...]:
        return tuple(
            MapTileSnapshot(
                placement=placement,
                png=(
                    existing[placement.key].png
                    if placement.key in existing
                    else None
                ),
                source=(
                    existing[placement.key].source
                    if placement.key in existing
                    else MapTileSource.MISSING
                ),
            )
            for placement in viewport.placements
        )

    @staticmethod
    def _tiles_by_key(
        snapshot: LiveMapSnapshot,
    ) -> dict[MapTileKey, MapTileSnapshot]:
        return {tile.placement.key: tile for tile in snapshot.tiles}

    def _aware_now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Live-map clock must return timezone-aware timestamps.")
        return now.astimezone(UTC)
