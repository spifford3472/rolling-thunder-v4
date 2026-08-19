"""Bounded Pi worker for immutable latest-frame radar coverage buffers."""

from __future__ import annotations

import logging
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
from rolling_thunder.map_tiles import MapTileError, MapTileKey, MapTilePlacement, MapViewport
from rolling_thunder.radar_coverage import (
    DEFAULT_RADAR_COVERAGE_MARGIN_TILES,
    DEFAULT_RADAR_RECENTER_THRESHOLD_TILES,
    build_radar_coverage_viewport,
    radar_viewport_is_covered,
    radar_viewport_is_usefully_centered,
    radar_viewport_needs_recenter,
)
from rolling_thunder.radar_domain import RadarFrame, RadarProviderStatus
from rolling_thunder.radar_tiles import apply_radar_opacity

_LOGGER = logging.getLogger("rolling_thunder.live_radar")
_RADAR_RETRY_DELAY_S = 5.0


class RadarDataStatus(StrEnum):
    """Availability state for the optional live radar overlay."""

    DISABLED = "disabled"
    IDLE = "idle"
    LOADING = "loading"
    READY = "ready"
    STALE = "stale"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class RadarRefreshReason(StrEnum):
    """Why one background radar coverage generation was requested."""

    INITIAL = "initial"
    SPATIAL = "spatial"
    TEMPORAL = "temporal"
    ZOOM = "zoom"


@dataclass(frozen=True)
class RadarTileSnapshot:
    """One placement and already-opacity-processed radar PNG."""

    placement: MapTilePlacement
    png: bytes | None


@dataclass(frozen=True)
class RadarCoverageBuffer:
    """One complete immutable exact-frame radar coverage area."""

    viewport: MapViewport
    frame: RadarFrame
    tiles: tuple[RadarTileSnapshot, ...]
    attribution: str


@dataclass(frozen=True)
class LiveRadarSnapshot:
    """Immutable visible radar state consumed by Tkinter without any I/O."""

    status: RadarDataStatus
    viewport: MapViewport | None
    frame: RadarFrame | None
    tiles: tuple[RadarTileSnapshot, ...]
    detail: str
    updated_at: datetime
    attribution: str | None = None
    coverage_viewport: MapViewport | None = None


@dataclass(frozen=True)
class _RadarLoadTarget:
    generation: int
    visible_viewport: MapViewport
    coverage_viewport: MapViewport
    reason: RadarRefreshReason


def _utc_now() -> datetime:
    return datetime.now(UTC)


class LiveRadarOverlayService:
    """Own one FRONT radar buffer and build one coalesced BACK buffer off-Tk."""

    def __init__(
        self,
        client: HttpForgeRadarClient,
        *,
        manifest_refresh_interval_s: float = 60.0,
        stale_after_s: float = 900.0,
        hide_after_s: float = 1_800.0,
        opacity: float = 0.55,
        display_enabled: bool = True,
        coverage_margin_tiles: int = DEFAULT_RADAR_COVERAGE_MARGIN_TILES,
        recenter_threshold_tiles: int = DEFAULT_RADAR_RECENTER_THRESHOLD_TILES,
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
        if coverage_margin_tiles < 1:
            raise ValueError("Radar coverage margin must be at least one tile.")
        if not 0 <= recenter_threshold_tiles < coverage_margin_tiles:
            raise ValueError(
                "Radar recenter threshold must be non-negative and smaller than the margin."
            )
        self._client = client
        self._manifest_refresh_interval_s = manifest_refresh_interval_s
        self._stale_after = timedelta(seconds=stale_after_s)
        self._hide_after = timedelta(seconds=hide_after_s)
        self._opacity = opacity
        self._coverage_margin_tiles = coverage_margin_tiles
        self._recenter_threshold_tiles = recenter_threshold_tiles
        self._clock = clock
        self._monotonic_clock = monotonic_clock
        self._executor = executor
        self._owns_executor = executor is None
        self._started = False
        self._lock = Lock()
        self._display_enabled = display_enabled
        self._next_generation = 0
        self._desired_viewport: MapViewport | None = None
        self._pending_target: _RadarLoadTarget | None = None
        self._queued_target: _RadarLoadTarget | None = None
        self._front: RadarCoverageBuffer | None = None
        self._front_degraded_detail: str | None = None
        self._retry_not_before_monotonic: float | None = None
        self._cached_manifest: ForgeRadarManifest | None = None
        self._manifest_checked_monotonic: float | None = None
        self._latest = self._idle_snapshot() if display_enabled else self._disabled_snapshot()

    @property
    def is_running(self) -> bool:
        return self._started

    @property
    def display_enabled(self) -> bool:
        """Return whether Pi-side radar image work is currently enabled."""
        with self._lock:
            return self._display_enabled

    @property
    def latest_state(self) -> LiveRadarSnapshot:
        with self._lock:
            return self._latest

    def set_display_enabled(self, enabled: bool) -> bool:
        """Enable or disable Pi-side radar image work without changing Forge."""
        with self._lock:
            if self._display_enabled is enabled:
                return False
            self._display_enabled = enabled
            self._desired_viewport = None
            self._pending_target = None
            self._queued_target = None
            self._front = None
            self._front_degraded_detail = None
            self._retry_not_before_monotonic = None
            self._latest = self._idle_snapshot() if enabled else self._disabled_snapshot()
            return True

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
            self._desired_viewport = None
            self._pending_target = None
            self._queued_target = None
            self._front = None
            self._front_degraded_detail = None

    def request_viewport(self, viewport: MapViewport) -> None:
        """Move the visible radar window and schedule BACK work only when necessary."""
        if not self._started:
            return

        submit_target: _RadarLoadTarget | None = None
        with self._lock:
            if not self._display_enabled:
                return

            self._desired_viewport = viewport
            front = self._front
            if front is not None and not self._locally_renderable(front.frame):
                self._front = None
                self._front_degraded_detail = None
                self._manifest_checked_monotonic = None
                front = None

            front_usable = (
                front is not None
                and front.viewport.zoom == viewport.zoom
                and radar_viewport_is_covered(viewport, front.viewport)
            )

            if front_usable:
                assert front is not None
                spatial_due = radar_viewport_needs_recenter(
                    viewport,
                    front.viewport,
                    threshold_tiles=self._recenter_threshold_tiles,
                )
                temporal_due = self._manifest_due_locked()

                if spatial_due:
                    submit_target = self._ensure_refresh_locked(
                        viewport,
                        RadarRefreshReason.SPATIAL,
                    )
                elif temporal_due:
                    submit_target = self._ensure_refresh_locked(
                        viewport,
                        RadarRefreshReason.TEMPORAL,
                    )

                self._latest = self._snapshot_from_front_locked(
                    viewport,
                    background_loading=self._pending_target is not None,
                )
                _LOGGER.debug(
                    "RADAR FRONT REFRAME zoom=%d coverage_tiles=%d",
                    viewport.zoom,
                    len(front.viewport.tile_keys),
                )
            else:
                if front is None:
                    reason = RadarRefreshReason.INITIAL
                elif front.viewport.zoom != viewport.zoom:
                    reason = RadarRefreshReason.ZOOM
                else:
                    reason = RadarRefreshReason.SPATIAL

                submit_target = self._ensure_refresh_locked(viewport, reason)
                if self._pending_target is not None:
                    detail = (
                        "LOADING RADAR FOR MAP ZOOM"
                        if reason is RadarRefreshReason.ZOOM
                        else "LOADING RADAR"
                    )
                    self._latest = self._loading_without_front_locked(viewport, detail)
                else:
                    self._latest = self._unavailable_snapshot_locked(
                        viewport,
                        self._front_degraded_detail or "RADAR UNAVAILABLE",
                    )

        self._submit_target(submit_target)

    def _ensure_refresh_locked(
        self,
        viewport: MapViewport,
        reason: RadarRefreshReason,
    ) -> _RadarLoadTarget | None:
        if self._retry_blocked_locked() and self._pending_target is None:
            return None

        pending = self._pending_target
        if pending is not None:
            if self._target_satisfies(pending, viewport):
                return None

            queued = self._queued_target
            if queued is not None and self._target_satisfies(queued, viewport):
                return None

            replacement = self._new_target_locked(viewport, reason)
            self._queued_target = replacement
            _LOGGER.info(
                "RADAR BACK LOAD SUPERSEDED generation=%d by=%d reason=%s",
                pending.generation,
                replacement.generation,
                reason.value,
            )
            return None

        target = self._new_target_locked(viewport, reason)
        self._pending_target = target
        if reason is RadarRefreshReason.SPATIAL:
            _LOGGER.info(
                "RADAR REFRESH BY SPATIAL THRESHOLD generation=%d",
                target.generation,
            )
        elif reason is RadarRefreshReason.TEMPORAL:
            _LOGGER.info(
                "RADAR REFRESH BY AGE generation=%d",
                target.generation,
            )
        return target

    def _new_target_locked(
        self,
        viewport: MapViewport,
        reason: RadarRefreshReason,
    ) -> _RadarLoadTarget:
        self._next_generation += 1
        return _RadarLoadTarget(
            generation=self._next_generation,
            visible_viewport=viewport,
            coverage_viewport=build_radar_coverage_viewport(
                viewport,
                margin_tiles=self._coverage_margin_tiles,
            ),
            reason=reason,
        )

    def _target_satisfies(
        self,
        target: _RadarLoadTarget,
        viewport: MapViewport,
    ) -> bool:
        return radar_viewport_is_usefully_centered(
            viewport,
            target.coverage_viewport,
            threshold_tiles=self._recenter_threshold_tiles,
        )

    def _submit_target(self, target: _RadarLoadTarget | None) -> None:
        if target is None or not self._started:
            return
        executor = self._executor
        if executor is not None:
            executor.submit(self._load_target, target)

    def _load_target(self, target: _RadarLoadTarget) -> None:
        _LOGGER.info(
            "RADAR BACK LOAD START generation=%d reason=%s zoom=%d tiles=%d",
            target.generation,
            target.reason.value,
            target.coverage_viewport.zoom,
            len(target.coverage_viewport.tile_keys),
        )
        manifest, manifest_error = self._manifest_for_worker()
        if manifest is None:
            self._finish_failure(
                target,
                manifest_error or "RADAR MANIFEST UNAVAILABLE",
            )
            return

        frame = manifest.frame
        if frame is None or not self._locally_renderable(frame) or not manifest.health.renderable:
            self._finish_failure(
                target,
                "RADAR FRAME TOO OLD" if frame is not None else "RADAR UNAVAILABLE",
            )
            return

        loaded = self._reusable_front_tiles(frame, target.coverage_viewport)
        for key in target.coverage_viewport.tile_keys:
            if key in loaded:
                continue
            if self._is_superseded(target.generation):
                self._finish_superseded(target)
                return
            try:
                loaded[key] = apply_radar_opacity(
                    self._client.fetch_tile(frame.frame_token, key),
                    self._opacity,
                )
            except (ForgeRadarClientError, MapTileError, ValueError) as error:
                self._finish_failure(
                    target,
                    str(error).strip() or "RADAR TILE DATA UNAVAILABLE",
                )
                return

        if self._is_superseded(target.generation):
            self._finish_superseded(target)
            return

        buffer = RadarCoverageBuffer(
            viewport=target.coverage_viewport,
            frame=frame,
            tiles=tuple(
                RadarTileSnapshot(
                    placement=placement,
                    png=loaded[placement.key],
                )
                for placement in target.coverage_viewport.placements
            ),
            attribution=frame.source.attribution_text,
        )
        self._finish_buffer(target, manifest, buffer)

    def _reusable_front_tiles(
        self,
        frame: RadarFrame,
        coverage: MapViewport,
    ) -> dict[MapTileKey, bytes]:
        with self._lock:
            front = self._front
            if front is None or front.frame.frame_token != frame.frame_token:
                return {}
            needed = set(coverage.tile_keys)
            return {
                tile.placement.key: tile.png
                for tile in front.tiles
                if tile.png is not None and tile.placement.key in needed
            }

    def _finish_buffer(
        self,
        target: _RadarLoadTarget,
        manifest: ForgeRadarManifest,
        buffer: RadarCoverageBuffer,
    ) -> None:
        next_target: _RadarLoadTarget | None = None
        with self._lock:
            pending = self._pending_target
            if (
                not self._started
                or not self._display_enabled
                or pending is None
                or pending.generation != target.generation
            ):
                return

            if self._queued_target is not None:
                next_target = self._promote_queue_locked()
            else:
                desired = self._desired_viewport or target.visible_viewport
                if not radar_viewport_is_usefully_centered(
                    desired,
                    buffer.viewport,
                    threshold_tiles=self._recenter_threshold_tiles,
                ):
                    reason = (
                        RadarRefreshReason.ZOOM
                        if desired.zoom != buffer.viewport.zoom
                        else RadarRefreshReason.SPATIAL
                    )
                    next_target = self._new_target_locked(desired, reason)
                    self._pending_target = next_target
                else:
                    self._front = buffer
                    self._front_degraded_detail = self._manifest_degraded_detail(manifest)
                    self._retry_not_before_monotonic = None
                    self._pending_target = None
                    self._latest = self._snapshot_from_front_locked(
                        desired,
                        background_loading=False,
                    )
                    _LOGGER.info(
                        "RADAR BUFFER SWAP generation=%d frame=%s tiles=%d",
                        target.generation,
                        buffer.frame.frame_token[:12],
                        len(buffer.viewport.tile_keys),
                    )

        self._submit_target(next_target)

    def _finish_superseded(self, target: _RadarLoadTarget) -> None:
        next_target: _RadarLoadTarget | None = None
        with self._lock:
            pending = self._pending_target
            if pending is None or pending.generation != target.generation:
                return
            next_target = self._promote_queue_locked()
        self._submit_target(next_target)

    def _finish_failure(
        self,
        target: _RadarLoadTarget,
        detail: str,
    ) -> None:
        next_target: _RadarLoadTarget | None = None
        with self._lock:
            pending = self._pending_target
            if (
                not self._started
                or not self._display_enabled
                or pending is None
                or pending.generation != target.generation
            ):
                return

            normalized_detail = (detail.strip() or "RADAR UNAVAILABLE")[:160]
            self._front_degraded_detail = "RADAR UPDATE FAILED — RETAINING PRIOR FRAME"
            self._retry_not_before_monotonic = (
                self._monotonic_clock() + _RADAR_RETRY_DELAY_S
            )

            if self._queued_target is not None:
                next_target = self._promote_queue_locked()
            else:
                self._pending_target = None

            desired = self._desired_viewport or target.visible_viewport
            if self._front_can_render_locked(desired):
                self._latest = self._snapshot_from_front_locked(
                    desired,
                    background_loading=next_target is not None,
                    detail_override=self._front_degraded_detail,
                )
            else:
                self._latest = self._unavailable_snapshot_locked(
                    desired,
                    normalized_detail,
                )

        self._submit_target(next_target)

    def _promote_queue_locked(self) -> _RadarLoadTarget | None:
        queued = self._queued_target
        self._queued_target = None
        self._pending_target = queued
        return queued

    def _is_superseded(self, generation: int) -> bool:
        with self._lock:
            pending = self._pending_target
            return (
                not self._started
                or not self._display_enabled
                or pending is None
                or pending.generation != generation
                or self._queued_target is not None
            )

    def _front_can_render_locked(self, viewport: MapViewport) -> bool:
        front = self._front
        return (
            front is not None
            and front.viewport.zoom == viewport.zoom
            and self._locally_renderable(front.frame)
            and radar_viewport_is_covered(viewport, front.viewport)
        )

    def _snapshot_from_front_locked(
        self,
        viewport: MapViewport,
        *,
        background_loading: bool,
        detail_override: str | None = None,
    ) -> LiveRadarSnapshot:
        front = self._front
        assert front is not None
        by_key = {
            tile.placement.key: tile.png
            for tile in front.tiles
            if tile.png is not None
        }
        if not radar_viewport_is_covered(viewport, front.viewport) or any(
            key not in by_key for key in viewport.tile_keys
        ):
            return self._unavailable_snapshot_locked(
                viewport,
                "RADAR COVERAGE UNAVAILABLE",
            )

        tiles = tuple(
            RadarTileSnapshot(
                placement=placement,
                png=by_key[placement.key],
            )
            for placement in viewport.placements
        )

        detail = detail_override or self._front_degraded_detail
        if self._locally_stale(front.frame):
            status = RadarDataStatus.STALE
            detail = detail or "RADAR STALE"
        elif detail is not None:
            status = RadarDataStatus.STALE
        elif background_loading:
            status = RadarDataStatus.LOADING
            detail = "UPDATING RADAR"
        else:
            status = RadarDataStatus.READY
            detail = "RADAR READY"

        return LiveRadarSnapshot(
            status=status,
            viewport=viewport,
            frame=front.frame,
            tiles=tiles,
            detail=detail,
            updated_at=self._aware_now(),
            attribution=front.attribution,
            coverage_viewport=front.viewport,
        )

    def _loading_without_front_locked(
        self,
        viewport: MapViewport,
        detail: str,
    ) -> LiveRadarSnapshot:
        return LiveRadarSnapshot(
            status=RadarDataStatus.LOADING,
            viewport=viewport,
            frame=None,
            tiles=(),
            detail=detail,
            updated_at=self._aware_now(),
        )

    def _unavailable_snapshot_locked(
        self,
        viewport: MapViewport,
        detail: str,
    ) -> LiveRadarSnapshot:
        return LiveRadarSnapshot(
            status=RadarDataStatus.UNAVAILABLE,
            viewport=viewport,
            frame=None,
            tiles=(),
            detail=(detail.strip() or "RADAR UNAVAILABLE")[:160],
            updated_at=self._aware_now(),
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
                checked_at = self._aware_now()
                degraded_health = cached.health.model_copy(
                    update={
                        "status": RadarProviderStatus.DEGRADED,
                        "last_attempt_at": checked_at,
                        "last_error": str(error)[:500] or "Forge radar manifest unavailable",
                    }
                )
                degraded = cached.model_copy(
                    update={
                        "health": degraded_health,
                        "received_at": checked_at,
                    }
                )
                return degraded, str(error)
            return None, str(error)
        with self._lock:
            self._cached_manifest = manifest
            self._manifest_checked_monotonic = now_mono
        return manifest, None

    def _manifest_degraded_detail(
        self,
        manifest: ForgeRadarManifest,
    ) -> str | None:
        if manifest.health.status is not RadarProviderStatus.HEALTHY:
            return "RADAR OFFLINE — USING CACHED FRAME"
        if manifest.health.stale:
            return "RADAR STALE"
        return None

    def _manifest_due_locked(self) -> bool:
        checked = self._manifest_checked_monotonic
        return (
            checked is None
            or self._monotonic_clock() - checked >= self._manifest_refresh_interval_s
        )

    def _retry_blocked_locked(self) -> bool:
        retry_at = self._retry_not_before_monotonic
        return retry_at is not None and self._monotonic_clock() < retry_at

    def _locally_stale(self, frame: RadarFrame) -> bool:
        return self._frame_age(frame) > self._stale_after

    def _locally_renderable(self, frame: RadarFrame) -> bool:
        return self._frame_age(frame) <= self._hide_after

    def _frame_age(self, frame: RadarFrame) -> timedelta:
        return max(timedelta(0), self._aware_now() - frame.observed_at)

    def _idle_snapshot(self) -> LiveRadarSnapshot:
        return LiveRadarSnapshot(
            status=RadarDataStatus.IDLE,
            viewport=None,
            frame=None,
            tiles=(),
            detail="RADAR WAITING FOR MAP",
            updated_at=self._aware_now(),
        )

    def _disabled_snapshot(self) -> LiveRadarSnapshot:
        return LiveRadarSnapshot(
            status=RadarDataStatus.DISABLED,
            viewport=None,
            frame=None,
            tiles=(),
            detail="RADAR DISABLED",
            updated_at=self._aware_now(),
        )

    def _aware_now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Live-radar clock must return a timezone-aware timestamp.")
        return value.astimezone(UTC)
