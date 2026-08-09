"""Bounded Pi worker for immutable latest-frame radar overlay snapshots."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Executor, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from threading import Lock
from time import monotonic

from rolling_thunder.forge_radar_client import (
    ForgeRadarClientError,
    ForgeRadarManifest,
    HttpForgeRadarClient,
)
from rolling_thunder.map_tiles import MapTileKey, MapTilePlacement, MapViewport
from rolling_thunder.radar_domain import RadarFrame
from rolling_thunder.radar_tiles import apply_radar_opacity


class RadarDataStatus(StrEnum):
    """Availability state for the optional live radar overlay."""

    IDLE = "idle"
    LOADING = "loading"
    READY = "ready"
    STALE = "stale"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class RadarTileSnapshot:
    """One placement and already-opacity-processed radar PNG."""

    placement: MapTilePlacement
    png: bytes | None


@dataclass(frozen=True)
class LiveRadarSnapshot:
    """Immutable radar state consumed by Tkinter without any I/O."""

    status: RadarDataStatus
    viewport: MapViewport | None
    frame: RadarFrame | None
    tiles: tuple[RadarTileSnapshot, ...]
    detail: str
    updated_at: datetime
    attribution: str | None = None


def _utc_now() -> datetime:
    return datetime.now(UTC)


class LiveRadarOverlayService:
    """Coalesce viewport requests and load one frame atomically off the UI thread."""

    def __init__(
        self,
        client: HttpForgeRadarClient,
        *,
        manifest_refresh_interval_s: float = 60.0,
        stale_after_s: float = 900.0,
        hide_after_s: float = 1_800.0,
        opacity: float = 0.55,
        clock: Callable[[], datetime] = _utc_now,
        monotonic_clock: Callable[[], float] = monotonic,
        executor: Executor | None = None,
    ) -> None:
        if manifest_refresh_interval_s <= 0:
            raise ValueError("Radar manifest refresh interval must be positive.")
        if stale_after_s <= 0 or hide_after_s <= stale_after_s:
            raise ValueError("Radar freshness thresholds are invalid.")
        if not 0.0 < opacity <= 1.0:
            raise ValueError("Radar opacity must be greater than zero and at most one.")
        self._client = client
        self._manifest_refresh_interval_s = manifest_refresh_interval_s
        self._stale_after = timedelta(seconds=stale_after_s)
        self._hide_after = timedelta(seconds=hide_after_s)
        self._opacity = opacity
        self._clock = clock
        self._monotonic_clock = monotonic_clock
        self._executor = executor
        self._owns_executor = executor is None
        self._started = False
        self._lock = Lock()
        self._next_generation = 0
        self._pending_generation: int | None = None
        self._pending_viewport: MapViewport | None = None
        self._queued_generation: int | None = None
        self._queued_viewport: MapViewport | None = None
        self._cached_manifest: ForgeRadarManifest | None = None
        self._manifest_checked_monotonic: float | None = None
        self._latest = LiveRadarSnapshot(
            status=RadarDataStatus.IDLE,
            viewport=None,
            frame=None,
            tiles=(),
            detail="RADAR WAITING FOR MAP",
            updated_at=self._aware_now(),
        )

    @property
    def is_running(self) -> bool:
        return self._started

    @property
    def latest_state(self) -> LiveRadarSnapshot:
        with self._lock:
            return self._latest

    def start(self) -> None:
        """Start the single bounded overlay worker."""
        if self._started:
            raise RuntimeError("Live radar overlay service is already running.")
        if self._executor is None:
            self._executor = ThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix="rolling-thunder-live-radar",
            )
        self._started = True

    def stop(self) -> None:
        """Stop accepting work and cancel queued radar tasks without UI blocking."""
        if not self._started:
            return
        self._started = False
        executor = self._executor
        if executor is not None and self._owns_executor:
            executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None
        with self._lock:
            self._pending_generation = None
            self._pending_viewport = None
            self._queued_generation = None
            self._queued_viewport = None

    def request_viewport(self, viewport: MapViewport) -> None:
        """Request radar for the already-published base-map viewport without blocking."""
        if not self._started:
            return
        submit_viewport: MapViewport | None = None
        submit_generation: int | None = None
        with self._lock:
            if self._pending_generation is not None:
                pending = self._pending_viewport
                if pending is not None and pending.tile_keys == viewport.tile_keys:
                    self._pending_viewport = viewport
                    self._reframe_latest_locked(viewport)
                    return
                queued = self._queued_viewport
                if queued is not None and queued.tile_keys == viewport.tile_keys:
                    self._queued_viewport = viewport
                    self._reframe_latest_locked(viewport)
                    return
                generation = self._new_generation_locked()
                self._queued_generation = generation
                self._queued_viewport = viewport
                self._latest = self._loading_snapshot_locked(viewport)
                return

            if (
                self._latest.viewport is not None
                and self._latest.viewport.tile_keys == viewport.tile_keys
                and not self._manifest_due_locked()
            ):
                self._reframe_latest_locked(viewport)
                return

            generation = self._new_generation_locked()
            self._pending_generation = generation
            self._pending_viewport = viewport
            self._latest = self._loading_snapshot_locked(viewport)
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
        if executor is not None:
            executor.submit(self._load_viewport, viewport, generation)

    def _load_viewport(self, requested: MapViewport, generation: int) -> None:
        manifest, manifest_error = self._manifest_for_worker()
        if manifest is None:
            self._finish_failure(
                requested,
                generation,
                manifest_error or "RADAR MANIFEST UNAVAILABLE",
            )
            return

        frame = manifest.frame
        if frame is None or not self._locally_renderable(frame) or not manifest.health.renderable:
            self._finish_unavailable(
                requested,
                generation,
                manifest,
                "RADAR FRAME TOO OLD" if frame is not None else "RADAR UNAVAILABLE",
            )
            return

        loaded: dict[MapTileKey, bytes | None] = {}
        errors = 0
        for key in requested.tile_keys:
            if self._is_superseded(generation):
                break
            try:
                loaded[key] = apply_radar_opacity(
                    self._client.fetch_tile(frame.frame_token, key),
                    self._opacity,
                )
            except (ForgeRadarClientError, ValueError):
                loaded[key] = None
                errors += 1

        self._finish_loaded(
            requested,
            generation,
            manifest,
            loaded,
            errors=errors,
        )

    def _manifest_for_worker(self) -> tuple[ForgeRadarManifest | None, str | None]:
        now_mono = self._monotonic_clock()
        with self._lock:
            cached = self._cached_manifest
            checked = self._manifest_checked_monotonic
            due = checked is None or now_mono - checked >= self._manifest_refresh_interval_s
        if not due and cached is not None:
            return cached, None
        try:
            manifest = self._client.fetch_manifest()
        except ForgeRadarClientError as error:
            with self._lock:
                self._manifest_checked_monotonic = now_mono
                cached = self._cached_manifest
            if cached is not None and cached.frame is not None and self._locally_renderable(
                cached.frame
            ):
                return cached, str(error)
            return None, str(error)
        with self._lock:
            self._cached_manifest = manifest
            self._manifest_checked_monotonic = now_mono
        return manifest, None

    def _finish_loaded(
        self,
        requested: MapViewport,
        generation: int,
        manifest: ForgeRadarManifest,
        loaded: dict[MapTileKey, bytes | None],
        *,
        errors: int,
    ) -> None:
        next_viewport: MapViewport | None = None
        next_generation: int | None = None
        with self._lock:
            if not self._started or self._pending_generation != generation:
                return
            queued = self._queued_viewport
            queued_generation = self._queued_generation
            if queued is not None and queued_generation is not None:
                self._pending_generation = queued_generation
                self._pending_viewport = queued
                self._queued_generation = None
                self._queued_viewport = None
                next_viewport = queued
                next_generation = queued_generation
            else:
                publish = self._pending_viewport or requested
                if publish.tile_keys != requested.tile_keys:
                    publish = requested
                candidate = self._snapshot_from_loaded(
                    publish,
                    manifest,
                    loaded,
                    errors=errors,
                )
                if errors and self._can_retain_previous_locked(publish):
                    self._latest = self._retained_failure_snapshot_locked(
                        publish,
                        "RADAR UPDATE PARTIAL — RETAINING PRIOR FRAME",
                    )
                else:
                    self._latest = candidate
                self._pending_generation = None
                self._pending_viewport = None
        self._submit(next_viewport, next_generation)

    def _finish_failure(
        self,
        requested: MapViewport,
        generation: int,
        detail: str,
    ) -> None:
        with self._lock:
            if not self._started or self._pending_generation != generation:
                return
            publish = self._pending_viewport or requested
            if self._can_retain_previous_locked(publish):
                self._latest = self._retained_failure_snapshot_locked(
                    publish,
                    "RADAR OFFLINE — RETAINING PRIOR FRAME",
                )
            else:
                self._latest = LiveRadarSnapshot(
                    status=RadarDataStatus.UNAVAILABLE,
                    viewport=publish,
                    frame=None,
                    tiles=(),
                    detail=(detail.strip() or "RADAR UNAVAILABLE")[:160],
                    updated_at=self._aware_now(),
                )
            self._complete_or_promote_queue_locked()
        self._submit_queued_after_failure()

    def _finish_unavailable(
        self,
        requested: MapViewport,
        generation: int,
        manifest: ForgeRadarManifest,
        detail: str,
    ) -> None:
        next_viewport: MapViewport | None = None
        next_generation: int | None = None
        with self._lock:
            if not self._started or self._pending_generation != generation:
                return
            queued = self._queued_viewport
            queued_generation = self._queued_generation
            if queued is not None and queued_generation is not None:
                self._pending_generation = queued_generation
                self._pending_viewport = queued
                self._queued_generation = None
                self._queued_viewport = None
                next_viewport = queued
                next_generation = queued_generation
            else:
                publish = self._pending_viewport or requested
                self._latest = LiveRadarSnapshot(
                    status=RadarDataStatus.UNAVAILABLE,
                    viewport=publish,
                    frame=manifest.frame,
                    tiles=(),
                    detail=detail,
                    updated_at=self._aware_now(),
                    attribution=(
                        manifest.frame.source.attribution_text
                        if manifest.frame is not None
                        else None
                    ),
                )
                self._pending_generation = None
                self._pending_viewport = None
        self._submit(next_viewport, next_generation)

    def _snapshot_from_loaded(
        self,
        viewport: MapViewport,
        manifest: ForgeRadarManifest,
        loaded: dict[MapTileKey, bytes | None],
        *,
        errors: int,
    ) -> LiveRadarSnapshot:
        frame = manifest.frame
        assert frame is not None
        tiles = tuple(
            RadarTileSnapshot(
                placement=placement,
                png=loaded.get(placement.key),
            )
            for placement in viewport.placements
        )
        available = sum(tile.png is not None for tile in tiles)
        if not available:
            status = RadarDataStatus.UNAVAILABLE
            detail = "RADAR TILE DATA UNAVAILABLE"
        elif errors:
            status = RadarDataStatus.PARTIAL
            detail = "RADAR DATA PARTIAL"
        elif self._locally_stale(frame) or manifest.health.stale:
            status = RadarDataStatus.STALE
            detail = "RADAR STALE"
        else:
            status = RadarDataStatus.READY
            detail = "RADAR READY"
        return LiveRadarSnapshot(
            status=status,
            viewport=viewport,
            frame=frame,
            tiles=tiles,
            detail=detail,
            updated_at=self._aware_now(),
            attribution=frame.source.attribution_text,
        )

    def _loading_snapshot_locked(self, viewport: MapViewport) -> LiveRadarSnapshot:
        previous = self._latest
        if (
            previous.frame is not None
            and previous.viewport is not None
            and previous.viewport.tile_keys == viewport.tile_keys
            and self._locally_renderable(previous.frame)
        ):
            return LiveRadarSnapshot(
                status=RadarDataStatus.LOADING,
                viewport=viewport,
                frame=previous.frame,
                tiles=self._reframe_tiles(previous.tiles, viewport),
                detail="UPDATING RADAR",
                updated_at=self._aware_now(),
                attribution=previous.attribution,
            )
        return LiveRadarSnapshot(
            status=RadarDataStatus.LOADING,
            viewport=viewport,
            frame=None,
            tiles=(),
            detail="LOADING RADAR",
            updated_at=self._aware_now(),
        )

    def _can_retain_previous_locked(self, viewport: MapViewport) -> bool:
        previous = self._latest
        return (
            previous.frame is not None
            and previous.viewport is not None
            and previous.viewport.tile_keys == viewport.tile_keys
            and self._locally_renderable(previous.frame)
            and bool(previous.tiles)
            and all(tile.png is not None for tile in previous.tiles)
        )

    def _retained_failure_snapshot_locked(
        self,
        viewport: MapViewport,
        detail: str,
    ) -> LiveRadarSnapshot:
        previous = self._latest
        assert previous.frame is not None
        return LiveRadarSnapshot(
            status=RadarDataStatus.STALE,
            viewport=viewport,
            frame=previous.frame,
            tiles=self._reframe_tiles(previous.tiles, viewport),
            detail=detail,
            updated_at=self._aware_now(),
            attribution=previous.attribution,
        )

    def _reframe_latest_locked(self, viewport: MapViewport) -> None:
        previous = self._latest
        if previous.viewport is None or previous.viewport.tile_keys != viewport.tile_keys:
            return
        if previous.viewport == viewport:
            return
        self._latest = LiveRadarSnapshot(
            status=previous.status,
            viewport=viewport,
            frame=previous.frame,
            tiles=self._reframe_tiles(previous.tiles, viewport),
            detail=previous.detail,
            updated_at=self._aware_now(),
            attribution=previous.attribution,
        )

    @staticmethod
    def _reframe_tiles(
        tiles: tuple[RadarTileSnapshot, ...],
        viewport: MapViewport,
    ) -> tuple[RadarTileSnapshot, ...]:
        by_key = {tile.placement.key: tile.png for tile in tiles}
        return tuple(
            RadarTileSnapshot(
                placement=placement,
                png=by_key.get(placement.key),
            )
            for placement in viewport.placements
        )

    def _complete_or_promote_queue_locked(self) -> None:
        queued = self._queued_viewport
        queued_generation = self._queued_generation
        if queued is not None and queued_generation is not None:
            self._pending_generation = queued_generation
            self._pending_viewport = queued
            self._queued_generation = None
            self._queued_viewport = None
        else:
            self._pending_generation = None
            self._pending_viewport = None

    def _submit_queued_after_failure(self) -> None:
        with self._lock:
            viewport = self._pending_viewport
            generation = self._pending_generation
        self._submit(viewport, generation)

    def _is_superseded(self, generation: int) -> bool:
        with self._lock:
            return (
                not self._started
                or self._pending_generation != generation
                or self._queued_viewport is not None
            )

    def _manifest_due_locked(self) -> bool:
        checked = self._manifest_checked_monotonic
        return (
            checked is None
            or self._monotonic_clock() - checked >= self._manifest_refresh_interval_s
        )

    def _locally_stale(self, frame: RadarFrame) -> bool:
        return self._frame_age(frame) > self._stale_after

    def _locally_renderable(self, frame: RadarFrame) -> bool:
        return self._frame_age(frame) <= self._hide_after

    def _frame_age(self, frame: RadarFrame) -> timedelta:
        return max(timedelta(0), self._aware_now() - frame.observed_at)

    def _new_generation_locked(self) -> int:
        self._next_generation += 1
        return self._next_generation

    def _aware_now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Live-radar clock must return a timezone-aware timestamp.")
        return value.astimezone(UTC)
