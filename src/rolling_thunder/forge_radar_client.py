"""Typed Pi-side client for provider-neutral Forge radar manifests and tiles."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from json import JSONDecodeError, loads
from typing import Literal
from urllib.error import URLError
from urllib.parse import quote, urlparse

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
        max_manifest_bytes: int = 65_536,
        max_tile_bytes: int = 2_000_000,
        transport: HttpTransport | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._api_url = self._validate_api_url(api_url)
        if timeout_s <= 0:
            raise ValueError("Forge radar timeout must be positive.")
        if max_manifest_bytes < 1 or max_tile_bytes < 1:
            raise ValueError("Forge radar response limits must be positive.")
        self._timeout_s = timeout_s
        self._max_manifest_bytes = max_manifest_bytes
        self._max_tile_bytes = max_tile_bytes
        self._transport = transport or UrllibHttpTransport()
        self._clock = clock or (lambda: datetime.now(UTC))

    def fetch_manifest(self) -> ForgeRadarManifest:
        """Fetch and strictly validate the latest version-1 radar manifest."""
        response = self._request(
            f"{self._api_url}/api/v1/radar",
            accept=_JSON_ACCEPT,
        )
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
        """Fetch one validated transparent PNG for the requested immutable frame."""
        encoded_token = quote(frame_token, safe="")
        url = (
            f"{self._api_url}/api/v1/radar/tiles/{encoded_token}/"
            f"{key.zoom}/{key.x}/{key.y}.png"
        )
        response = self._request(url, accept="image/png")
        if len(response.body) > self._max_tile_bytes:
            raise ForgeRadarResponseError("Forge radar tile exceeded the byte limit.")
        try:
            return validate_map_tile_png(
                response.body,
                maximum_bytes=self._max_tile_bytes,
            )
        except MapTileError as error:
            raise ForgeRadarResponseError("Forge radar tile was not a valid PNG.") from error

    def _request(self, url: str, *, accept: str) -> HttpResponse:
        try:
            response = self._transport.request(
                "GET",
                url,
                headers={"Accept": accept, "User-Agent": _USER_AGENT},
                body=None,
                timeout_s=self._timeout_s,
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
