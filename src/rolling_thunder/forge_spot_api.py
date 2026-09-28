"""Versioned private Forge JSON API for retained spots, location, and weather."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from json import JSONDecodeError, dumps, loads
from typing import Final, Literal, Protocol
from urllib.parse import urlsplit

from pydantic import ValidationError

from rolling_thunder.domain import DomainModel
from rolling_thunder.forge_mobile_location import (
    ForgeMobileLocationService,
    ForgeMobileLocationStorageError,
    InvalidMobileLocationTimingError,
    MobileLocationRecord,
    StaleMobileLocationError,
)
from rolling_thunder.forge_spot_aggregation import (
    ForgeAggregationState,
    ForgeProviderHealth,
    ForgeProviderHealthStatus,
)
from rolling_thunder.forge_weather import (
    ForgeWeatherState,
    WeatherProviderStatus,
    WeatherSnapshot,
)
from rolling_thunder.spot_domain import SpotProvider, SpotRecord

_API_SCHEMA_VERSION: Literal["1"] = "1"
_JSON_CONTENT_TYPE = "application/json; charset=utf-8"
_MOBILE_LOCATION_PATH = "/api/v1/mobile-location"
_WEATHER_PATH = "/api/v1/weather"
MAX_MOBILE_LOCATION_PAYLOAD_BYTES: Final = 4_096
_LOGGER = logging.getLogger("rolling_thunder.forge_spots")


class ForgeAggregationStateSource(Protocol):
    """Read-only published-state boundary consumed by API presentation."""

    def get_state(self) -> ForgeAggregationState:
        """Return one immutable already-published aggregation state."""
        ...


class ForgeWeatherStateSource(Protocol):
    """Read-only retained-weather boundary consumed by API presentation."""

    def get_state(self) -> ForgeWeatherState:
        """Return already-published weather state without provider I/O."""
        ...

    def is_stale(self) -> bool:
        """Return whether retained weather is absent, aged, or spatially stale."""
        ...


class ForgeServiceStatus(StrEnum):
    """Overall public health state for the Forge spot process."""

    STARTING = "starting"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class ForgeApiProviderHealth(DomainModel):
    """Spot-provider health serialized by versioned read endpoints."""

    provider: SpotProvider
    status: ForgeProviderHealthStatus
    active_spot_count: int
    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error: str | None = None

    @classmethod
    def from_health(cls, health: ForgeProviderHealth) -> ForgeApiProviderHealth:
        """Copy one immutable internal provider-health record."""
        return cls(
            provider=health.provider,
            status=health.status,
            active_spot_count=health.active_spot_count,
            last_attempt_at=health.last_attempt_at,
            last_success_at=health.last_success_at,
            last_error=health.last_error,
        )


class ForgeApiWeatherHealth(DomainModel):
    """Read-only health metadata for retained Forge weather."""

    status: WeatherProviderStatus
    stale: bool
    revision: int
    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error: str | None = None
    startup_storage_error: str | None = None
    persistence_error: str | None = None

    @classmethod
    def from_state(
        cls,
        state: ForgeWeatherState,
        *,
        stale: bool,
    ) -> ForgeApiWeatherHealth:
        """Copy one immutable weather state into public health metadata."""
        return cls(
            status=state.provider_status,
            stale=stale,
            revision=state.revision,
            last_attempt_at=state.last_attempt_at,
            last_success_at=state.last_success_at,
            last_error=state.last_error,
            startup_storage_error=state.startup_storage_error,
            persistence_error=state.persistence_error,
        )


class ForgeHealthResponse(DomainModel):
    """Version-1 service-health response."""

    api_schema_version: Literal["1"] = _API_SCHEMA_VERSION
    service_status: ForgeServiceStatus
    snapshot_revision: int
    snapshot_generated_at: datetime
    active_spot_count: int
    providers: tuple[ForgeApiProviderHealth, ...]
    weather: ForgeApiWeatherHealth | None = None
    startup_storage_error: str | None = None
    persistence_error: str | None = None


class ForgeSpotsResponse(DomainModel):
    """Version-1 complete immutable active-snapshot response."""

    api_schema_version: Literal["1"] = _API_SCHEMA_VERSION
    snapshot_revision: int
    generated_at: datetime
    spots: tuple[SpotRecord, ...]
    providers: tuple[ForgeApiProviderHealth, ...]


class ForgeWeatherResponse(DomainModel):
    """Version-1 retained provider-neutral weather response."""

    api_schema_version: Literal["1"] = _API_SCHEMA_VERSION
    revision: int
    stale: bool
    snapshot: WeatherSnapshot | None = None
    health: ForgeApiWeatherHealth


class ForgeMobileLocationWriteRequest(DomainModel):
    """Version-1 bounded mobile-location write request."""

    api_schema_version: Literal["1"]
    location: MobileLocationRecord


class ForgeMobileLocationWriteResponse(DomainModel):
    """Version-1 acknowledgement for one durably accepted location."""

    api_schema_version: Literal["1"] = _API_SCHEMA_VERSION
    revision: int
    location: MobileLocationRecord


@dataclass(frozen=True, slots=True)
class ForgeHttpResponse:
    """Transport-independent complete HTTP response."""

    status_code: int
    headers: tuple[tuple[str, str], ...]
    body: bytes


class ForgeSpotApiApplication:
    """Pure router over already-published Forge spots, location, and weather."""

    def __init__(
        self,
        state_source: ForgeAggregationStateSource,
        *,
        mobile_location: ForgeMobileLocationService | None = None,
        weather: ForgeWeatherStateSource | None = None,
    ) -> None:
        self._state_source = state_source
        self._mobile_location = mobile_location
        self._weather = weather

    def handle(
        self,
        method: str,
        target: str,
        *,
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
    ) -> ForgeHttpResponse:
        """Return one deterministic response without provider refresh work."""
        normalized_method = method.strip().upper()
        path = urlsplit(target).path

        if path == _MOBILE_LOCATION_PATH:
            return self._handle_mobile_location(
                normalized_method,
                headers=headers or {},
                body=body,
            )

        if path == _WEATHER_PATH:
            return self._handle_weather(normalized_method)

        if normalized_method != "GET":
            return self.error_response(
                status_code=405,
                error="method_not_allowed",
                message="Only GET is supported by the Forge spot API.",
                extra_headers=(("Allow", "GET"),),
            )

        if path not in {"/api/v1/health", "/api/v1/spots"}:
            return self.error_response(
                status_code=404,
                error="not_found",
                message="The requested Forge spot API path does not exist.",
            )

        state = self._state_source.get_state()
        providers = tuple(
            ForgeApiProviderHealth.from_health(health)
            for health in state.providers
        )

        payload: ForgeHealthResponse | ForgeSpotsResponse
        if path == "/api/v1/health":
            payload = ForgeHealthResponse(
                service_status=derive_service_status(state),
                snapshot_revision=state.revision,
                snapshot_generated_at=state.snapshot.generated_at,
                active_spot_count=len(state.snapshot.spots),
                providers=providers,
                weather=self._weather_health(),
                startup_storage_error=state.startup_storage_error,
                persistence_error=state.persistence_error,
            )
        else:
            payload = ForgeSpotsResponse(
                snapshot_revision=state.revision,
                generated_at=state.snapshot.generated_at,
                spots=state.snapshot.spots,
                providers=providers,
            )

        return self._json_response(200, payload.model_dump(mode="json"))

    def _handle_weather(self, method: str) -> ForgeHttpResponse:
        if method != "GET":
            return self.error_response(
                status_code=405,
                error="method_not_allowed",
                message="Only GET is supported by the Forge weather endpoint.",
                extra_headers=(("Allow", "GET"),),
            )
        if self._weather is None:
            return self.error_response(
                status_code=503,
                error="weather_unavailable",
                message="Forge retained weather is disabled or unavailable.",
            )

        state = self._weather.get_state()
        stale = self._weather.is_stale()
        response = ForgeWeatherResponse(
            revision=state.revision,
            stale=stale,
            snapshot=state.snapshot,
            health=ForgeApiWeatherHealth.from_state(state, stale=stale),
        )
        return self._json_response(200, response.model_dump(mode="json"))

    def _weather_health(self) -> ForgeApiWeatherHealth | None:
        if self._weather is None:
            return None
        state = self._weather.get_state()
        return ForgeApiWeatherHealth.from_state(
            state,
            stale=self._weather.is_stale(),
        )

    def _handle_mobile_location(
        self,
        method: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None,
    ) -> ForgeHttpResponse:
        if method != "PUT":
            return self.error_response(
                status_code=405,
                error="method_not_allowed",
                message="Only PUT is supported by the Forge mobile-location endpoint.",
                extra_headers=(("Allow", "PUT"),),
            )

        if self._mobile_location is None:
            return self.error_response(
                status_code=503,
                error="mobile_location_unavailable",
                message="Forge mobile-location publication is unavailable.",
            )

        content_type = self._header_value(headers, "Content-Type")
        if (
            content_type is None
            or content_type.split(";", 1)[0].strip().lower() != "application/json"
        ):
            return self.error_response(
                status_code=415,
                error="unsupported_media_type",
                message="Forge mobile-location writes require application/json.",
            )

        if body is None:
            return self.error_response(
                status_code=411,
                error="length_required",
                message="Forge mobile-location writes require a request body.",
            )
        if len(body) > MAX_MOBILE_LOCATION_PAYLOAD_BYTES:
            return self.error_response(
                status_code=413,
                error="payload_too_large",
                message="Forge mobile-location payload exceeds 4096 bytes.",
            )
        if not body:
            return self.error_response(
                status_code=400,
                error="malformed_json",
                message="Forge mobile-location request body must contain JSON.",
            )

        try:
            decoded = body.decode("utf-8")
            raw_payload = loads(decoded)
        except (UnicodeDecodeError, JSONDecodeError):
            return self.error_response(
                status_code=400,
                error="malformed_json",
                message="Forge mobile-location request body is not valid UTF-8 JSON.",
            )

        if not isinstance(raw_payload, dict):
            return self.error_response(
                status_code=400,
                error="invalid_payload",
                message="Forge mobile-location JSON root must be an object.",
            )

        schema_version = raw_payload.get("api_schema_version")
        if schema_version != _API_SCHEMA_VERSION:
            return self.error_response(
                status_code=400,
                error="unsupported_schema_version",
                message="Forge mobile-location api_schema_version must be '1'.",
            )

        try:
            request = ForgeMobileLocationWriteRequest.model_validate(raw_payload)
        except ValidationError as error:
            return self.error_response(
                status_code=422,
                error="invalid_location",
                message=self._validation_message(error),
            )

        try:
            state = self._mobile_location.publish(request.location)
        except (InvalidMobileLocationTimingError, StaleMobileLocationError) as error:
            return self.error_response(
                status_code=409,
                error="stale_location",
                message=str(error),
            )
        except ForgeMobileLocationStorageError:
            return self.error_response(
                status_code=503,
                error="location_persistence_unavailable",
                message="Forge could not durably retain the mobile location.",
            )

        assert state.location is not None
        response = ForgeMobileLocationWriteResponse(
            revision=state.revision,
            location=state.location,
        )
        return self._json_response(200, response.model_dump(mode="json"))

    @classmethod
    def error_response(
        cls,
        *,
        status_code: int,
        error: str,
        message: str,
        extra_headers: tuple[tuple[str, str], ...] = (),
    ) -> ForgeHttpResponse:
        """Build a bounded versioned JSON error response."""
        return cls._json_response(
            status_code,
            {
                "api_schema_version": _API_SCHEMA_VERSION,
                "error": error,
                "message": message[:500],
            },
            extra_headers=extra_headers,
        )

    @staticmethod
    def _json_response(
        status_code: int,
        payload: object,
        *,
        extra_headers: tuple[tuple[str, str], ...] = (),
    ) -> ForgeHttpResponse:
        body = dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        headers = (
            ("Content-Type", _JSON_CONTENT_TYPE),
            ("Content-Length", str(len(body))),
            ("Cache-Control", "no-store"),
            *extra_headers,
        )
        return ForgeHttpResponse(
            status_code=status_code,
            headers=headers,
            body=body,
        )

    @staticmethod
    def _header_value(headers: Mapping[str, str], name: str) -> str | None:
        wanted = name.lower()
        for header_name, value in headers.items():
            if header_name.lower() == wanted:
                return value
        return None

    @staticmethod
    def _validation_message(error: ValidationError) -> str:
        first = error.errors(include_url=False)[0]
        location = ".".join(str(part) for part in first["loc"]) or "payload"
        return f"Invalid mobile-location field {location}: {first['msg']}"[:500]


def derive_service_status(state: ForgeAggregationState) -> ForgeServiceStatus:
    """Derive one deterministic overall service status from published spot state."""
    statuses = {provider.status for provider in state.providers}
    has_storage_error = (
        state.startup_storage_error is not None
        or state.persistence_error is not None
    )

    if statuses == {ForgeProviderHealthStatus.STARTING} and not has_storage_error:
        return ForgeServiceStatus.STARTING

    if statuses == {ForgeProviderHealthStatus.HEALTHY} and not has_storage_error:
        return ForgeServiceStatus.HEALTHY

    if (
        state.revision == 0
        and not state.snapshot.spots
        and statuses
        and statuses <= {ForgeProviderHealthStatus.UNAVAILABLE}
    ):
        return ForgeServiceStatus.UNAVAILABLE

    return ForgeServiceStatus.DEGRADED


def make_forge_request_handler(
    application: ForgeSpotApiApplication,
    *,
    logger: logging.Logger | None = None,
) -> type[BaseHTTPRequestHandler]:
    """Create a standard-library request handler bound to one API application."""
    request_logger = logger or _LOGGER

    class ForgeRequestHandler(BaseHTTPRequestHandler):
        server_version = "RollingThunderForge/1"
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:
            self._dispatch()

        def do_HEAD(self) -> None:
            self._dispatch()

        def do_POST(self) -> None:
            self._dispatch()

        def do_PUT(self) -> None:
            self._dispatch()

        def do_PATCH(self) -> None:
            self._dispatch()

        def do_DELETE(self) -> None:
            self._dispatch()

        def do_OPTIONS(self) -> None:
            self._dispatch()

        def _dispatch(self) -> None:
            body: bytes | None = None
            path = urlsplit(self.path).path
            if self.command == "PUT" and path == _MOBILE_LOCATION_PATH:
                body_or_error = self._read_mobile_location_body()
                if isinstance(body_or_error, ForgeHttpResponse):
                    self._send_response(body_or_error)
                    return
                body = body_or_error

            response = application.handle(
                self.command,
                self.path,
                headers={name: value for name, value in self.headers.items()},
                body=body,
            )
            self._send_response(response)

        def _read_mobile_location_body(self) -> bytes | ForgeHttpResponse:
            raw_length = self.headers.get("Content-Length")
            if raw_length is None:
                return application.error_response(
                    status_code=411,
                    error="length_required",
                    message="Forge mobile-location writes require Content-Length.",
                )
            try:
                length = int(raw_length, 10)
            except ValueError:
                self.close_connection = True
                return application.error_response(
                    status_code=400,
                    error="invalid_content_length",
                    message="Content-Length must be a non-negative decimal integer.",
                    extra_headers=(("Connection", "close"),),
                )
            if length < 0:
                self.close_connection = True
                return application.error_response(
                    status_code=400,
                    error="invalid_content_length",
                    message="Content-Length must be a non-negative decimal integer.",
                    extra_headers=(("Connection", "close"),),
                )
            if length > MAX_MOBILE_LOCATION_PAYLOAD_BYTES:
                self.close_connection = True
                return application.error_response(
                    status_code=413,
                    error="payload_too_large",
                    message="Forge mobile-location payload exceeds 4096 bytes.",
                    extra_headers=(("Connection", "close"),),
                )
            return self.rfile.read(length)

        def _send_response(self, response: ForgeHttpResponse) -> None:
            self.send_response(response.status_code)
            for name, value in response.headers:
                self.send_header(name, value)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(response.body)

        def log_message(self, format_string: str, *args: object) -> None:
            request_logger.info(
                "%s - %s",
                self.address_string(),
                format_string % args,
            )

    return ForgeRequestHandler


class ForgeHttpServer:
    """Lifecycle wrapper around the standard-library threaded HTTP server."""

    def __init__(
        self,
        bind_host: str,
        bind_port: int,
        application: ForgeSpotApiApplication,
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        handler = make_forge_request_handler(application, logger=logger)
        self._server = ThreadingHTTPServer((bind_host, bind_port), handler)
        self._server.daemon_threads = True

    @property
    def server_address(self) -> tuple[str, int]:
        """Return the effective bound host and port."""
        host, port = self._server.server_address[:2]
        return str(host), int(port)

    def serve_forever(self) -> None:
        """Serve requests until shutdown is requested."""
        self._server.serve_forever(poll_interval=0.5)

    def shutdown(self) -> None:
        """Stop a running serve loop from another thread."""
        self._server.shutdown()

    def close(self) -> None:
        """Close the listening socket."""
        self._server.server_close()
