"""Background map-tile loading and immutable viewport snapshots."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Executor, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from threading import Lock

from rolling_thunder.live_map import GeoPoint
from rolling_thunder.map_refresh import MapRefreshReason
from rolling_thunder.map_sources import (
    DEFAULT_MAP_ATTRIBUTION,
    InstalledMapMetadata,
    MapPackageStyle,
    MapTileResolver,
    MapTileSource,
    ResolvedMapTile,
)
from rolling_thunder.map_tiles import (
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


@dataclass(frozen=True)
class MapTileSnapshot:
    """One viewport placement and its optional validated PNG bytes."""

    placement: MapTilePlacement
    png: bytes | None
    source: MapTileSource
    attribution: str | None = None


@dataclass(frozen=True)
class LiveMapSnapshot:
    """Immutable background map-data state consumed by Tkinter."""

    status: MapDataStatus
    viewport: MapViewport | None
    tiles: tuple[MapTileSnapshot, ...]
    detail: str
    updated_at: datetime
    attribution: str = DEFAULT_MAP_ATTRIBUTION


def _utc_now() -> datetime:
    return datetime.now(UTC)


class LiveMapService:
    """Own one bounded worker for visible map-tile cache and HTTP work."""

    def __init__(
        self,
        resolver: MapTileResolver,
        *,
        zoom: int = 13,
        clock: Callable[[], datetime] = _utc_now,
        executor: Executor | None = None,
    ) -> None:
        if not 0 <= zoom <= 22:
            raise ValueError("Live-map zoom must be between 0 and 22.")

        self._resolver = resolver
        self._zoom = zoom
        self._clock = clock
        self._executor = executor
        self._owns_executor = executor is None
        self._started = False
        self._lock = Lock()

        self._next_generation = 0
        self._pending_generation: int | None = None
        self._pending_keyset: tuple[MapTileKey, ...] | None = None
        self._pending_viewport: MapViewport | None = None
        self._queued_generation: int | None = None
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

    @property
    def zoom(self) -> int:
        """Return the active in-memory zoom without performing I/O."""
        with self._lock:
            return self._zoom

    @property
    def style(self) -> MapPackageStyle:
        """Return the active local/Forge map style."""
        return self._resolver.style

    @property
    def available_styles(self) -> tuple[MapPackageStyle, ...]:
        """Return styles provided by installed offline packages."""
        return self._resolver.available_styles

    @property
    def installed_packages(self) -> tuple[InstalledMapMetadata, ...]:
        """Return validated installed packages in lookup order."""
        return self._resolver.installed_packages

    @property
    def source_diagnostics(self) -> tuple[str, ...]:
        """Return non-fatal installed-package loading or read failures."""
        return self._resolver.diagnostics

    def set_zoom(self, zoom: int) -> bool:
        """Change zoom in memory; the next normal viewport request loads it."""
        if not 0 <= zoom <= 22:
            raise ValueError("Live-map zoom must be between 0 and 22.")
        with self._lock:
            if zoom == self._zoom:
                return False
            self._zoom = zoom
        return True

    def set_style(self, style: MapPackageStyle) -> bool:
        """Switch day/night source and invalidate only base-map presentation data."""
        if not self._resolver.set_style(style):
            return False
        with self._lock:
            self._pending_generation = None
            self._pending_keyset = None
            self._pending_viewport = None
            self._queued_generation = None
            self._queued_viewport = None
            self._latest = LiveMapSnapshot(
                status=MapDataStatus.IDLE,
                viewport=None,
                tiles=(),
                detail=f"LOADING {style.value.upper()} MAP",
                updated_at=self._aware_now(),
            )
        return True

    def start(self) -> None:
        """Start the single bounded background map worker and deferred refresh worker."""
        if self._started:
            raise RuntimeError("Live map service is already running.")
        if self._executor is None:
            self._executor = ThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix="rolling-thunder-live-map",
            )
        self._started = True
        self._resolver.start_background_refresh()

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
            self._pending_generation = None
            self._pending_keyset = None
            self._pending_viewport = None
            self._queued_generation = None
            self._queued_viewport = None
        self._resolver.close()

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
        with self._lock:
            zoom = self._zoom
        viewport = build_map_viewport(
            center,
            zoom=zoom,
            width_px=max(1, width_px),
            height_px=max(1, height_px),
        )
        keyset = viewport.tile_keys
        submit_viewport: MapViewport | None = None
        submit_generation: int | None = None

        with self._lock:
            existing = self._tiles_by_key(self._latest)
            if self._pending_keyset is not None:
                if keyset == self._pending_keyset:
                    self._pending_viewport = viewport
                    self._reframe_latest_if_matching(viewport, existing)
                    return
                queued = self._queued_viewport
                if queued is not None and keyset == queued.tile_keys:
                    self._queued_viewport = viewport
                    self._reframe_latest_if_matching(viewport, existing)
                    return
                generation = self._new_generation_locked()
                self._queued_generation = generation
                self._queued_viewport = viewport
                self._latest = self._loading_snapshot(viewport, existing)
                return

            if keyset and all(
                key in existing and existing[key].png is not None for key in keyset
            ):
                if self._latest.viewport == viewport:
                    return
                self._latest = self._reframe_snapshot(
                    self._latest,
                    viewport,
                    existing,
                )
                return

            generation = self._new_generation_locked()
            self._pending_generation = generation
            self._pending_keyset = keyset
            self._pending_viewport = viewport
            self._latest = self._loading_snapshot(viewport, existing)
            submit_viewport = viewport
            submit_generation = generation

        self._submit(submit_viewport, submit_generation)

    def _submit(
        self,
        viewport: MapViewport | None,
        generation: int | None,
    ) -> None:
        if viewport is None or generation is None or not self._started:
            return
        executor = self._executor
        if executor is None:
            return
        executor.submit(self._load_viewport, viewport, generation)

    def _load_viewport(
        self,
        requested_viewport: MapViewport,
        generation: int,
    ) -> None:
        loaded: dict[MapTileKey, ResolvedMapTile] = {}
        refresh_keys: list[MapTileKey] = []

        for key in requested_viewport.tile_keys:
            local = self._resolver.read_local(key)
            loaded[key] = local
            self._resolver.observe_installed_tile(
                local,
                reason=MapRefreshReason.DISPLAYED,
            )
            if local.online_refresh_allowed and local.source in {
                MapTileSource.STALE_CACHE,
                MapTileSource.MISSING,
            }:
                refresh_keys.append(key)

        # This runs on the map worker, never the Tkinter rendering thread.
        self._resolver.observe_gps_position(requested_viewport.center)

        self._publish_progress(requested_viewport, generation, loaded)
        for key in refresh_keys:
            if self._is_superseded(generation):
                break
            loaded[key] = self._refresh_tile(key, loaded[key])
            self._publish_progress(requested_viewport, generation, loaded)

        self._finish_request(requested_viewport, generation, loaded)

    def _refresh_tile(
        self,
        key: MapTileKey,
        fallback: ResolvedMapTile,
    ) -> ResolvedMapTile:
        return self._resolver.refresh_online(key, fallback)

    def _publish_progress(
        self,
        requested_viewport: MapViewport,
        generation: int,
        loaded: dict[MapTileKey, ResolvedMapTile],
    ) -> None:
        with self._lock:
            if (
                not self._started
                or self._pending_generation != generation
                or self._queued_viewport is not None
            ):
                return
            publish_viewport = self._pending_viewport or requested_viewport
            if publish_viewport.tile_keys != requested_viewport.tile_keys:
                return
            self._latest = self._build_snapshot(
                publish_viewport,
                loaded,
                loading=True,
            )

    def _finish_request(
        self,
        requested_viewport: MapViewport,
        generation: int,
        loaded: dict[MapTileKey, ResolvedMapTile],
    ) -> None:
        next_viewport: MapViewport | None = None
        next_generation: int | None = None
        with self._lock:
            if not self._started or self._pending_generation != generation:
                return
            queued_viewport = self._queued_viewport
            queued_generation = self._queued_generation
            if queued_viewport is not None and queued_generation is not None:
                self._pending_generation = queued_generation
                self._pending_keyset = queued_viewport.tile_keys
                self._pending_viewport = queued_viewport
                self._queued_generation = None
                self._queued_viewport = None
                next_viewport = queued_viewport
                next_generation = queued_generation
            else:
                publish_viewport = self._pending_viewport or requested_viewport
                if publish_viewport.tile_keys != requested_viewport.tile_keys:
                    publish_viewport = requested_viewport
                self._latest = self._build_snapshot(
                    publish_viewport,
                    loaded,
                    loading=False,
                )
                self._pending_generation = None
                self._pending_keyset = None
                self._pending_viewport = None
        self._submit(next_viewport, next_generation)

    def _is_superseded(self, generation: int) -> bool:
        with self._lock:
            return (
                not self._started
                or self._pending_generation != generation
                or self._queued_viewport is not None
            )

    def _build_snapshot(
        self,
        viewport: MapViewport,
        loaded: dict[MapTileKey, ResolvedMapTile],
        *,
        loading: bool,
    ) -> LiveMapSnapshot:
        tiles = tuple(
            MapTileSnapshot(
                placement=placement,
                png=loaded[placement.key].png,
                source=loaded[placement.key].source,
                attribution=loaded[placement.key].attribution,
            )
            for placement in viewport.placements
        )
        attribution = self._attribution_for_tiles(tiles)
        if loading:
            return LiveMapSnapshot(
                status=MapDataStatus.LOADING,
                viewport=viewport,
                tiles=tiles,
                detail="LOADING MAP DATA",
                updated_at=self._aware_now(),
                attribution=attribution,
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
            attribution=attribution,
        )

    def _loading_snapshot(
        self,
        viewport: MapViewport,
        existing: dict[MapTileKey, MapTileSnapshot],
    ) -> LiveMapSnapshot:
        tiles = self._reuse_tiles(viewport, existing)
        return LiveMapSnapshot(
            status=MapDataStatus.LOADING,
            viewport=viewport,
            tiles=tiles,
            detail="LOADING MAP DATA",
            updated_at=self._aware_now(),
            attribution=self._attribution_for_tiles(tiles),
        )

    def _reframe_latest_if_matching(
        self,
        viewport: MapViewport,
        existing: dict[MapTileKey, MapTileSnapshot],
    ) -> None:
        current = self._latest.viewport
        if current is None or current.tile_keys != viewport.tile_keys:
            return
        if current == viewport:
            return
        self._latest = self._reframe_snapshot(
            self._latest,
            viewport,
            existing,
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
                    attribution=existing[placement.key].attribution,
                )
                for placement in viewport.placements
            ),
            detail=snapshot.detail,
            updated_at=self._aware_now(),
            attribution=snapshot.attribution,
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
                attribution=(
                    existing[placement.key].attribution
                    if placement.key in existing
                    else None
                ),
            )
            for placement in viewport.placements
        )

    @staticmethod
    def _attribution_for_tiles(
        tiles: tuple[MapTileSnapshot, ...],
    ) -> str:
        attributions = tuple(
            dict.fromkeys(
                tile.attribution
                for tile in tiles
                if tile.attribution is not None
            )
        )
        return " | ".join(attributions) or DEFAULT_MAP_ATTRIBUTION

    @staticmethod
    def _tiles_by_key(
        snapshot: LiveMapSnapshot,
    ) -> dict[MapTileKey, MapTileSnapshot]:
        return {tile.placement.key: tile for tile in snapshot.tiles}

    def _new_generation_locked(self) -> int:
        self._next_generation += 1
        return self._next_generation

    def _aware_now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Live-map clock must return timezone-aware timestamps.")
        return now.astimezone(UTC)
