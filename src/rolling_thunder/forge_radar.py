"""Provider-neutral retained radar frame state and bounded coverage cache."""

from __future__ import annotations

import logging
from collections import OrderedDict
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from threading import RLock
from time import monotonic
from typing import Protocol

from rolling_thunder.domain import DomainModel
from rolling_thunder.forge_mobile_location import (
    ForgeMobileLocationService,
    MobileLocationRecord,
)
from rolling_thunder.map_tiles import MapTileKey, validate_map_tile_png
from rolling_thunder.radar_domain import (
    RadarFrame,
    RadarProviderStatus,
    RadarSourceMetadata,
)

_LOGGER = logging.getLogger("rolling_thunder.forge_spots")
_MAX_COVERAGE_COLUMNS = 32
_MAX_COVERAGE_ROWS = 16
_RETAINED_FRAME_COUNT = 2


class ForgeRadarError(RuntimeError):
    """Base exception for optional Forge radar work."""


class ForgeRadarProviderError(ForgeRadarError):
    """Raised when a radar provider cannot return a valid frame or tile."""


class RadarProviderFrame(DomainModel):
    """Internal provider result before an opaque public token is assigned."""

    provider_frame_id: str
    observed_at: datetime
    valid_until: datetime | None = None
    source: RadarSourceMetadata


class ForgeRadarState(DomainModel):
    """Immutable latest radar publication and health metadata."""

    revision: int = 0
    frame: RadarFrame | None = None
    provider_status: RadarProviderStatus = RadarProviderStatus.STARTING
    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error: str | None = None


class RadarProvider(Protocol):
    """Typed provider boundary hiding NOAA/ArcGIS implementation details."""

    def discover_latest(self, location: MobileLocationRecord) -> RadarProviderFrame:
        """Return the newest complete frame covering the retained location."""
        ...

    def fetch_tile(self, provider_frame_id: str, key: MapTileKey) -> bytes:
        """Return one transparent 256x256 PNG locked to the provider frame."""
        ...

    def fetch_coverage(
        self,
        provider_frame_id: str,
        *,
        zoom: int,
        x_start: int,
        y_start: int,
        columns: int,
        rows: int,
    ) -> dict[MapTileKey, bytes]:
        """Return one exact-frame rectangular batch of transparent radar tiles."""
        ...


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ForgeRadarService:
    """Retain current/prior frames and provide bounded bulk radar retrieval."""

    def __init__(
        self,
        provider: RadarProvider,
        mobile_location: ForgeMobileLocationService,
        *,
        stale_after_s: float = 900.0,
        hide_after_s: float = 1_800.0,
        maximum_cached_tiles: int = 256,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        if stale_after_s <= 0:
            raise ValueError("Radar stale threshold must be positive.")
        if hide_after_s <= stale_after_s:
            raise ValueError("Radar hide threshold must exceed the stale threshold.")
        if maximum_cached_tiles < 1:
            raise ValueError("Radar tile cache size must be positive.")
        self._provider = provider
        self._mobile_location = mobile_location
        self._stale_after = timedelta(seconds=stale_after_s)
        self._hide_after = timedelta(seconds=hide_after_s)
        self._maximum_cached_tiles = maximum_cached_tiles
        self._now = now
        self._lock = RLock()
        self._state = ForgeRadarState()
        self._retained_frames: OrderedDict[str, tuple[RadarFrame, str]] = OrderedDict()
        self._tile_cache: OrderedDict[tuple[str, MapTileKey], bytes] = OrderedDict()

    def get_state(self) -> ForgeRadarState:
        """Return already-published state without provider I/O."""
        with self._lock:
            return self._state

    def is_stale(self) -> bool:
        """Return whether the current observation is older than 15 minutes."""
        state = self.get_state()
        return state.frame is None or self._age(state.frame) > self._stale_after

    def is_renderable(self) -> bool:
        """Return whether the current observation remains eligible to display."""
        state = self.get_state()
        return state.frame is not None and self._age(state.frame) <= self._hide_after

    def refresh(self) -> ForgeRadarState:
        """Discover latest metadata while retaining the previous frame for handoff."""
        now = self._aware_now()
        location_state = self._mobile_location.get_state()
        location = location_state.location
        if location is None:
            with self._lock:
                self._state = self._state.model_copy(
                    update={
                        "provider_status": RadarProviderStatus.UNAVAILABLE,
                        "last_attempt_at": now,
                        "last_error": "No retained mobile location is available for radar.",
                    }
                )
                return self._state

        try:
            candidate = self._provider.discover_latest(location)
        except Exception as error:  # noqa: BLE001 - optional provider isolation boundary
            message = str(error)[:500] or error.__class__.__name__
            with self._lock:
                status = (
                    RadarProviderStatus.DEGRADED
                    if self._state.frame is not None
                    else RadarProviderStatus.UNAVAILABLE
                )
                self._state = self._state.model_copy(
                    update={
                        "provider_status": status,
                        "last_attempt_at": now,
                        "last_error": message,
                    }
                )
                return self._state

        observed_at = self._aware(candidate.observed_at, "Radar observation time")
        if observed_at > now + timedelta(minutes=2):
            return self._reject_candidate(now, "Radar provider returned a future observation.")
        if candidate.valid_until is not None:
            valid_until = self._aware(candidate.valid_until, "Radar validity end")
            if valid_until < observed_at:
                return self._reject_candidate(now, "Radar provider returned an invalid time range.")

        token = self._frame_token(candidate.provider_frame_id, observed_at)
        discovered_frame = RadarFrame(
            frame_token=token,
            observed_at=observed_at,
            fetched_at=now,
            source=candidate.source,
        )

        with self._lock:
            previous = self._state.frame
            changed = previous is None or previous.frame_token != token
            revision = self._state.revision + 1 if changed else self._state.revision
            frame = discovered_frame if changed or previous is None else previous
            self._retain_frame_locked(frame, candidate.provider_frame_id)
            self._state = ForgeRadarState(
                revision=revision,
                frame=frame,
                provider_status=RadarProviderStatus.HEALTHY,
                last_attempt_at=now,
                last_success_at=now,
                last_error=None,
            )
            if changed and previous is not None:
                _LOGGER.info(
                    "RADAR FRAME HANDOFF current=%s prior=%s retained=%d",
                    token[:12],
                    previous.frame_token[:12],
                    len(self._retained_frames),
                )
            return self._state

    def get_tile(self, frame_token: str, key: MapTileKey) -> bytes:
        """Return one tile, allowing a retained prior frame during handoff."""
        _frame, provider_frame_id = self._resolve_retained_frame(frame_token)
        cache_key = (frame_token, key)
        with self._lock:
            cached = self._tile_cache.get(cache_key)
            if cached is not None:
                self._tile_cache.move_to_end(cache_key)
                return cached

        try:
            png = validate_map_tile_png(self._provider.fetch_tile(provider_frame_id, key))
        except Exception as error:
            self._record_tile_failure(error)
            raise ForgeRadarProviderError("Radar tile retrieval failed.") from error

        with self._lock:
            self._cache_tile_locked(frame_token, key, png)
        return png

    def get_coverage(
        self,
        frame_token: str,
        *,
        zoom: int,
        x_start: int,
        y_start: int,
        columns: int,
        rows: int,
    ) -> dict[MapTileKey, bytes]:
        """Return one bounded exact-frame rectangle using provider bulk export."""
        _frame, provider_frame_id = self._resolve_retained_frame(frame_token)
        keys = self._coverage_keys(
            zoom=zoom,
            x_start=x_start,
            y_start=y_start,
            columns=columns,
            rows=rows,
        )
        with self._lock:
            cached = {
                key: self._tile_cache[(frame_token, key)]
                for key in keys
                if (frame_token, key) in self._tile_cache
            }
            if len(cached) == len(keys):
                for key in keys:
                    self._tile_cache.move_to_end((frame_token, key))
                _LOGGER.info(
                    "RADAR FORGE COVERAGE CACHE frame=%s tiles=%d",
                    frame_token[:12],
                    len(keys),
                )
                return cached

        started = monotonic()
        try:
            fetched = self._provider.fetch_coverage(
                provider_frame_id,
                zoom=zoom,
                x_start=x_start,
                y_start=y_start,
                columns=columns,
                rows=rows,
            )
            if set(fetched) != set(keys):
                raise ForgeRadarProviderError(
                    "Radar provider coverage did not contain exactly the requested tiles."
                )
            validated = {key: validate_map_tile_png(png) for key, png in fetched.items()}
        except Exception as error:
            self._record_tile_failure(error)
            raise ForgeRadarProviderError("Radar coverage retrieval failed.") from error

        with self._lock:
            # A request remains valid if a newer frame became current during provider I/O.
            # Cache only while this token is still one of the two retained generations.
            if frame_token in self._retained_frames:
                for key in keys:
                    self._cache_tile_locked(frame_token, key, validated[key])
        _LOGGER.info(
            "RADAR FORGE COVERAGE READY frame=%s zoom=%d x=%d y=%d cols=%d rows=%d "
            "tiles=%d duration_ms=%d",
            frame_token[:12],
            zoom,
            x_start,
            y_start,
            columns,
            rows,
            len(validated),
            round((monotonic() - started) * 1000),
        )
        return {key: validated[key] for key in keys}

    def _resolve_retained_frame(self, frame_token: str) -> tuple[RadarFrame, str]:
        with self._lock:
            retained = self._retained_frames.get(frame_token)
            if retained is None:
                raise ForgeRadarProviderError("Requested radar frame is no longer retained.")
            frame, provider_frame_id = retained
            if self._age(frame) > self._hide_after:
                raise ForgeRadarProviderError("Requested radar frame is too old to render.")
            self._retained_frames.move_to_end(frame_token)
            return frame, provider_frame_id

    def _retain_frame_locked(self, frame: RadarFrame, provider_frame_id: str) -> None:
        self._retained_frames[frame.frame_token] = (frame, provider_frame_id)
        self._retained_frames.move_to_end(frame.frame_token)
        while len(self._retained_frames) > _RETAINED_FRAME_COUNT:
            expired_token, _ = self._retained_frames.popitem(last=False)
            stale_keys = [
                cache_key for cache_key in self._tile_cache if cache_key[0] == expired_token
            ]
            for cache_key in stale_keys:
                self._tile_cache.pop(cache_key, None)

    def _cache_tile_locked(self, frame_token: str, key: MapTileKey, png: bytes) -> None:
        cache_key = (frame_token, key)
        self._tile_cache[cache_key] = png
        self._tile_cache.move_to_end(cache_key)
        while len(self._tile_cache) > self._maximum_cached_tiles:
            self._tile_cache.popitem(last=False)

    def _record_tile_failure(self, error: Exception) -> None:
        with self._lock:
            self._state = self._state.model_copy(
                update={
                    "provider_status": RadarProviderStatus.DEGRADED,
                    "last_error": (str(error)[:500] or error.__class__.__name__),
                }
            )

    @staticmethod
    def _coverage_keys(
        *,
        zoom: int,
        x_start: int,
        y_start: int,
        columns: int,
        rows: int,
    ) -> tuple[MapTileKey, ...]:
        if not 0 <= zoom <= 22:
            raise ForgeRadarProviderError("Radar coverage zoom was invalid.")
        if not 1 <= columns <= _MAX_COVERAGE_COLUMNS:
            raise ForgeRadarProviderError("Radar coverage width was outside the safe bound.")
        if not 1 <= rows <= _MAX_COVERAGE_ROWS:
            raise ForgeRadarProviderError("Radar coverage height was outside the safe bound.")
        limit = 1 << zoom
        if x_start < 0 or y_start < 0:
            raise ForgeRadarProviderError("Radar coverage origin was invalid.")
        if x_start + columns > limit or y_start + rows > limit:
            raise ForgeRadarProviderError("Radar coverage rectangle exceeded the map world.")
        return tuple(
            MapTileKey(zoom=zoom, x=x, y=y)
            for x in range(x_start, x_start + columns)
            for y in range(y_start, y_start + rows)
        )

    def _reject_candidate(self, now: datetime, message: str) -> ForgeRadarState:
        with self._lock:
            status = (
                RadarProviderStatus.DEGRADED
                if self._state.frame is not None
                else RadarProviderStatus.UNAVAILABLE
            )
            self._state = self._state.model_copy(
                update={
                    "provider_status": status,
                    "last_attempt_at": now,
                    "last_error": message,
                }
            )
            return self._state

    def _age(self, frame: RadarFrame) -> timedelta:
        return max(timedelta(0), self._aware_now() - frame.observed_at)

    def _aware_now(self) -> datetime:
        return self._aware(self._now(), "Radar clock")

    @staticmethod
    def _aware(value: datetime, name: str) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{name} must be timezone-aware.")
        return value.astimezone(UTC)

    @staticmethod
    def _frame_token(provider_frame_id: str, observed_at: datetime) -> str:
        material = f"radar-v1\0{provider_frame_id}\0{observed_at.isoformat()}".encode()
        return sha256(material).hexdigest()[:32]
