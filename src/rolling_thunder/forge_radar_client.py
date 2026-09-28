"""Typed Pi-side client for provider-neutral Forge radar manifests and tiles."""

from __future__ import annotations

import logging
from collections import OrderedDict
from collections.abc import Callable
from datetime import UTC, datetime
from io import BytesIO
from json import JSONDecodeError, loads
from threading import RLock
from time import monotonic
from typing import Literal
from urllib.error import URLError
from urllib.parse import quote, urlparse
from zipfile import BadZipFile, ZipFile

from pydantic import Field, ValidationError, field_validator, model_validator

from rolling_thunder.domain import DomainModel
from rolling_thunder.http_home_platform import (
    HttpResponse,
    HttpTransport,
    UrllibHttpTransport,
)
from rolling_thunder.map_tiles import MapTileError, MapTileKey, validate_map_tile_png
from rolling_thunder.radar_domain import RadarFrame, RadarProviderStatus

_JSON_ACCEPT = "application/json"
_USER_AGENT = "RollingThunder-v4.1"
_MAX_ERROR_LENGTH = 500
_RADAR_PREFETCH_COLUMNS = 20
_RADAR_PREFETCH_ROWS = 16
_RADAR_PREFETCH_CACHE_TILES = 640
_RADAR_PREFETCH_CACHE_BYTES = 64_000_000
_MAX_COVERAGE_RESPONSE_BYTES = 96_000_000
_LOGGER = logging.getLogger("rolling_thunder.live_radar")


class ForgeRadarClientError(Exception):
    """Base exception for Pi-side Forge radar failures."""


class ForgeRadarConnectionError(ForgeRadarClientError):
    """Raised when Forge radar cannot be reached."""


class ForgeRadarResponseError(ForgeRadarClientError):
    """Raised when Forge returns unusable radar HTTP or JSON data."""


class ForgeRadarValidationError(ForgeRadarClientError):
    """Raised when a Forge radar response violates the versioned contract."""


class ForgeRadarRemoteHealth(DomainModel):
    """Validated version-1 radar freshness and provider health."""

    status: RadarProviderStatus
    stale: bool
    renderable: bool
    revision: int = Field(ge=0, strict=True)
    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error: str | None = Field(default=None, max_length=_MAX_ERROR_LENGTH)

    @field_validator("last_attempt_at", "last_success_at")
    @classmethod
    def normalize_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("radar health timestamps must include timezone information")
        return value.astimezone(UTC)

    @field_validator("last_error")
    @classmethod
    def normalize_error(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class ForgeRadarManifest(DomainModel):
    """Complete provider-neutral radar state returned by Forge API version 1."""

    api_schema_version: Literal["1"]
    revision: int = Field(ge=0, strict=True)
    frame: RadarFrame | None = None
    health: ForgeRadarRemoteHealth
    received_at: datetime

    @field_validator("received_at")
    @classmethod
    def normalize_received_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("radar received_at must include timezone information")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_contract(self) -> ForgeRadarManifest:
        if self.health.revision != self.revision:
            raise ValueError("radar health revision must match manifest revision")
        if self.frame is None and self.health.renderable:
            raise ValueError("radar without a frame cannot be renderable")
        if self.health.status is RadarProviderStatus.HEALTHY:
            if self.health.last_attempt_at is None or self.health.last_success_at is None:
                raise ValueError("healthy radar requires attempt and success timestamps")
            if self.health.last_error is not None:
                raise ValueError("healthy radar cannot contain an error")
        return self


class _ForgeRadarWireManifest(DomainModel):
    api_schema_version: Literal["1"]
    revision: int = Field(ge=0, strict=True)
    frame: RadarFrame | None = None
    health: ForgeRadarRemoteHealth

    def to_manifest(self, received_at: datetime) -> ForgeRadarManifest:
        return ForgeRadarManifest(
            api_schema_version=self.api_schema_version,
            revision=self.revision,
            frame=self.frame,
            health=self.health,
            received_at=received_at,
        )


class HttpForgeRadarClient:
    """Synchronous Forge radar client intended only for bounded workers."""

    def __init__(
        self,
        api_url: str,
        *,
        timeout_s: float = 5.0,
        coverage_timeout_s: float | None = None,
        max_manifest_bytes: int = 65_536,
        max_tile_bytes: int = 2_000_000,
        max_coverage_bytes: int = _MAX_COVERAGE_RESPONSE_BYTES,
        transport: HttpTransport | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._api_url = self._validate_api_url(api_url)
        if timeout_s <= 0:
            raise ValueError("Forge radar timeout must be positive.")
        resolved_coverage_timeout = (
            max(30.0, timeout_s) if coverage_timeout_s is None else coverage_timeout_s
        )
        if resolved_coverage_timeout <= 0:
            raise ValueError("Forge radar coverage timeout must be positive.")
        if max_manifest_bytes < 1 or max_tile_bytes < 1 or max_coverage_bytes < 1:
            raise ValueError("Forge radar response limits must be positive.")
        self._timeout_s = timeout_s
        self._coverage_timeout_s = resolved_coverage_timeout
        self._max_manifest_bytes = max_manifest_bytes
        self._max_tile_bytes = max_tile_bytes
        self._max_coverage_bytes = max_coverage_bytes
        self._transport = transport or UrllibHttpTransport()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._cache_lock = RLock()
        self._cached_frame_token: str | None = None
        self._prefetched_tiles: OrderedDict[MapTileKey, bytes] = OrderedDict()
        self._prefetched_bytes = 0

    def fetch_manifest(self) -> ForgeRadarManifest:
        """Fetch and strictly validate the latest version-1 radar manifest."""
        response = self._request(f"{self._api_url}/api/v1/radar", accept=_JSON_ACCEPT)
        if len(response.body) > self._max_manifest_bytes:
            raise ForgeRadarResponseError("Forge radar manifest exceeded the byte limit.")
        try:
            payload = loads(response.body)
        except (JSONDecodeError, UnicodeDecodeError) as error:
            raise ForgeRadarResponseError(
                "Forge radar manifest was not valid UTF-8 JSON."
            ) from error
        if not isinstance(payload, dict):
            raise ForgeRadarResponseError(
                "Forge radar manifest JSON must contain an object at the document root."
            )
        try:
            wire = _ForgeRadarWireManifest.model_validate(payload)
        except ValidationError as error:
            raise ForgeRadarValidationError(self._validation_message(error)) from error
        received_at = self._aware_clock()
        try:
            return wire.to_manifest(received_at)
        except ValidationError as error:
            raise ForgeRadarValidationError(self._validation_message(error)) from error

    def fetch_tile(self, frame_token: str, key: MapTileKey) -> bytes:
        """Return one tile while prefetching a large Forge coverage block on cache miss."""
        with self._cache_lock:
            self._select_frame_locked(frame_token)
            cached = self._prefetched_tiles.get(key)
            if cached is not None:
                self._prefetched_tiles.move_to_end(key)
                return cached

        limit = 1 << key.zoom
        columns = min(_RADAR_PREFETCH_COLUMNS, limit - key.x)
        rows = min(_RADAR_PREFETCH_ROWS, limit - key.y)
        tiles = self.fetch_coverage(
            frame_token,
            zoom=key.zoom,
            x_start=key.x,
            y_start=key.y,
            columns=columns,
            rows=rows,
        )
        try:
            return tiles[key]
        except KeyError as error:
            raise ForgeRadarResponseError(
                "Forge radar coverage omitted the requested tile."
            ) from error

    def fetch_coverage(
        self,
        frame_token: str,
        *,
        zoom: int,
        x_start: int,
        y_start: int,
        columns: int,
        rows: int,
    ) -> dict[MapTileKey, bytes]:
        """Fetch and validate one bounded ZIP archive of exact-frame radar tiles."""
        encoded_token = quote(frame_token, safe="")
        url = (
            f"{self._api_url}/api/v1/radar/coverage/{encoded_token}/"
            f"{zoom}/{x_start}/{y_start}/{columns}/{rows}.zip"
        )
        started = monotonic()
        response = self._request(
            url,
            accept="application/zip",
            timeout_s=self._coverage_timeout_s,
        )
        if len(response.body) > self._max_coverage_bytes:
            raise ForgeRadarResponseError("Forge radar coverage exceeded the byte limit.")
        expected = self._coverage_keys(
            zoom=zoom,
            x_start=x_start,
            y_start=y_start,
            columns=columns,
            rows=rows,
        )
        tiles = self._decode_coverage_archive(response.body, expected)
        with self._cache_lock:
            self._select_frame_locked(frame_token)
            for key in expected:
                self._cache_tile_locked(key, tiles[key])
        _LOGGER.info(
            "RADAR PI COVERAGE READY frame=%s zoom=%d x=%d y=%d cols=%d rows=%d "
            "tiles=%d bytes=%d duration_ms=%d",
            frame_token[:12],
            zoom,
            x_start,
            y_start,
            columns,
            rows,
            len(tiles),
            len(response.body),
            round((monotonic() - started) * 1000),
        )
        return tiles

    def _decode_coverage_archive(
        self,
        body: bytes,
        expected: tuple[MapTileKey, ...],
    ) -> dict[MapTileKey, bytes]:
        expected_names = {f"{key.zoom}/{key.x}/{key.y}.png": key for key in expected}
        tiles: dict[MapTileKey, bytes] = {}
        try:
            with ZipFile(BytesIO(body), mode="r") as archive:
                infos = archive.infolist()
                names = [info.filename for info in infos if not info.is_dir()]
                if len(names) != len(set(names)):
                    raise ForgeRadarResponseError(
                        "Forge radar coverage contained duplicate entries."
                    )
                if set(names) != set(expected_names):
                    raise ForgeRadarResponseError(
                        "Forge radar coverage entries did not match the requested rectangle."
                    )
                for info in infos:
                    if info.is_dir():
                        continue
                    if info.file_size > self._max_tile_bytes:
                        raise ForgeRadarResponseError(
                            "Forge radar coverage contained an oversized tile."
                        )
                    key = expected_names[info.filename]
                    try:
                        tiles[key] = validate_map_tile_png(
                            archive.read(info),
                            maximum_bytes=self._max_tile_bytes,
                        )
                    except MapTileError as error:
                        raise ForgeRadarResponseError(
                            "Forge radar coverage contained an invalid PNG tile."
                        ) from error
        except ForgeRadarResponseError:
            raise
        except (BadZipFile, OSError, RuntimeError, ValueError) as error:
            raise ForgeRadarResponseError(
                "Forge radar coverage was not a valid ZIP archive."
            ) from error
        return tiles

    @staticmethod
    def _coverage_keys(
        *,
        zoom: int,
        x_start: int,
        y_start: int,
        columns: int,
        rows: int,
    ) -> tuple[MapTileKey, ...]:
        if columns < 1 or rows < 1:
            raise ForgeRadarResponseError("Radar coverage dimensions must be positive.")
        try:
            return tuple(
                MapTileKey(zoom=zoom, x=x, y=y)
                for x in range(x_start, x_start + columns)
                for y in range(y_start, y_start + rows)
            )
        except ValueError as error:
            raise ForgeRadarResponseError("Radar coverage rectangle was invalid.") from error

    def _select_frame_locked(self, frame_token: str) -> None:
        if self._cached_frame_token == frame_token:
            return
        self._cached_frame_token = frame_token
        self._prefetched_tiles.clear()
        self._prefetched_bytes = 0

    def _cache_tile_locked(self, key: MapTileKey, png: bytes) -> None:
        previous = self._prefetched_tiles.pop(key, None)
        if previous is not None:
            self._prefetched_bytes -= len(previous)
        self._prefetched_tiles[key] = png
        self._prefetched_tiles.move_to_end(key)
        self._prefetched_bytes += len(png)
        while (
            len(self._prefetched_tiles) > _RADAR_PREFETCH_CACHE_TILES
            or self._prefetched_bytes > _RADAR_PREFETCH_CACHE_BYTES
        ):
            _old_key, old_png = self._prefetched_tiles.popitem(last=False)
            self._prefetched_bytes -= len(old_png)

    def _request(
        self,
        url: str,
        *,
        accept: str,
        timeout_s: float | None = None,
    ) -> HttpResponse:
        try:
            response = self._transport.request(
                "GET",
                url,
                headers={"Accept": accept, "User-Agent": _USER_AGENT},
                body=None,
                timeout_s=self._timeout_s if timeout_s is None else timeout_s,
            )
        except (TimeoutError, URLError, OSError) as error:
            raise ForgeRadarConnectionError(
                "Forge radar request could not be completed."
            ) from error
        if not 200 <= response.status_code < 300:
            raise ForgeRadarConnectionError(
                f"Forge radar request returned HTTP {response.status_code}."
            )
        return response

    def _aware_clock(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Forge radar client clock must return an aware datetime.")
        return value.astimezone(UTC)

    @staticmethod
    def _validate_api_url(value: str) -> str:
        normalized = value.strip().rstrip("/")
        parsed = urlparse(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Forge API URL must be an absolute HTTP or HTTPS URL.")
        if parsed.query or parsed.fragment:
            raise ValueError("Forge API URL must not contain a query string or fragment.")
        return normalized

    @staticmethod
    def _validation_message(error: ValidationError) -> str:
        details: list[str] = []
        for item in error.errors(include_url=False):
            location = ".".join(str(part) for part in item["loc"]) or "<response>"
            details.append(f"{location}: {item['msg']}")
        return ("; ".join(details) or "Forge radar validation failed")[:_MAX_ERROR_LENGTH]
