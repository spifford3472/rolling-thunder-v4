"""Provider-neutral retained radar frame state and bounded tile cache."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from hashlib import sha256
from threading import RLock
from typing import Protocol

from rolling_thunder.domain import DomainModel
from rolling_thunder.forge_mobile_location import (
    ForgeMobileLocationService,
    MobileLocationRecord,
)
from rolling_thunder.map_tiles import MapTileKey, validate_map_tile_png


class ForgeRadarError(RuntimeError):
    """Base exception for optional Forge radar work."""


class ForgeRadarProviderError(ForgeRadarError):
    """Raised when a radar provider cannot return a valid frame or tile."""


class RadarProviderStatus(StrEnum):
    """Truthful provider health for optional radar intelligence."""

    STARTING = "starting"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class RadarProductToken(StrEnum):
    """Rolling Thunder-owned radar product identifiers."""

    BASE_REFLECTIVITY = "base_reflectivity"


class RadarSourceMetadata(DomainModel):
    """Provider attribution carried with every retained frame."""

    provider_id: str
    provider_name: str
    product: RadarProductToken
    attribution_text: str
    attribution_url: str


class RadarProviderFrame(DomainModel):
    """Internal provider result before an opaque public token is assigned."""

    provider_frame_id: str
    observed_at: datetime
    valid_until: datetime | None = None
    source: RadarSourceMetadata


class RadarFrame(DomainModel):
    """Provider-neutral public metadata for one immutable radar frame."""

    frame_token: str
    observed_at: datetime
    fetched_at: datetime
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


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ForgeRadarService:
    """Retain latest radar metadata and bound provider-backed tile retrieval."""

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
        self._provider_frame_id: str | None = None
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
        """Discover and publish the latest frame while retaining prior good state."""
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
        except Exception as error:
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
        frame = RadarFrame(
            frame_token=token,
            observed_at=observed_at,
            fetched_at=now,
            source=candidate.source,
        )

        with self._lock:
            previous = self._state.frame
            changed = previous is None or previous.frame_token != token
            revision = self._state.revision + 1 if changed else self._state.revision
            if changed:
                self._tile_cache.clear()
            self._provider_frame_id = candidate.provider_frame_id
            self._state = ForgeRadarState(
                revision=revision,
                frame=frame if changed or previous is None else previous,
                provider_status=RadarProviderStatus.HEALTHY,
                last_attempt_at=now,
                last_success_at=now,
                last_error=None,
            )
            return self._state

    def get_tile(self, frame_token: str, key: MapTileKey) -> bytes:
        """Return one validated current-frame tile with bounded single-flight caching."""
        with self._lock:
            state = self._state
            frame = state.frame
            provider_frame_id = self._provider_frame_id
            if frame is None or provider_frame_id is None:
                raise ForgeRadarProviderError("Radar frame is unavailable.")
            if frame.frame_token != frame_token:
                raise ForgeRadarProviderError("Requested radar frame is no longer current.")
            if self._age(frame) > self._hide_after:
                raise ForgeRadarProviderError("Requested radar frame is too old to render.")
            cache_key = (frame_token, key)
            cached = self._tile_cache.get(cache_key)
            if cached is not None:
                self._tile_cache.move_to_end(cache_key)
                return cached

            try:
                png = validate_map_tile_png(
                    self._provider.fetch_tile(provider_frame_id, key)
                )
            except Exception as error:
                self._state = self._state.model_copy(
                    update={
                        "provider_status": RadarProviderStatus.DEGRADED,
                        "last_error": (str(error)[:500] or error.__class__.__name__),
                    }
                )
                raise ForgeRadarProviderError("Radar tile retrieval failed.") from error

            self._tile_cache[cache_key] = png
            self._tile_cache.move_to_end(cache_key)
            while len(self._tile_cache) > self._maximum_cached_tiles:
                self._tile_cache.popitem(last=False)
            return png

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
