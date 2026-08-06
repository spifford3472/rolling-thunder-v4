"""Versioned read-only JSON API for already-published Forge spot state."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from json import dumps
from typing import Literal, Protocol
from urllib.parse import urlsplit

from rolling_thunder.domain import DomainModel
from rolling_thunder.forge_spot_aggregation import (
    ForgeAggregationState,
    ForgeProviderHealth,
    ForgeProviderHealthStatus,
)
from rolling_thunder.spot_domain import SpotProvider, SpotRecord

_API_SCHEMA_VERSION: Literal["1"] = "1"
_JSON_CONTENT_TYPE = "application/json; charset=utf-8"
_LOGGER = logging.getLogger("rolling_thunder.forge_spots")


class ForgeAggregationStateSource(Protocol):
    """Read-only published-state boundary consumed by API presentation."""

    def get_state(self) -> ForgeAggregationState:
        """Return one immutable already-published aggregation state."""
        ...


class ForgeServiceStatus(StrEnum):
    """Overall public health state for the Forge spot process."""

    STARTING = "starting"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class ForgeApiProviderHealth(DomainModel):
    """Provider health serialized by both versioned endpoints."""

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


class ForgeHealthResponse(DomainModel):
    """Version-1 service-health response."""

    api_schema_version: Literal["1"] = _API_SCHEMA_VERSION
    service_status: ForgeServiceStatus
    snapshot_revision: int
    snapshot_generated_at: datetime
    active_spot_count: int
    providers: tuple[ForgeApiProviderHealth, ...]
    startup_storage_error: str | None = None
    persistence_error: str | None = None


class ForgeSpotsResponse(DomainModel):
    """Version-1 complete immutable active-snapshot response."""

    api_schema_version: Literal["1"] = _API_SCHEMA_VERSION
    snapshot_revision: int
    generated_at: datetime
    spots: tuple[SpotRecord, ...]
    providers: tuple[ForgeApiProviderHealth, ...]


@dataclass(frozen=True, slots=True)
class ForgeHttpResponse:
    """Transport-independent complete HTTP response."""

    status_code: int
    headers: tuple[tuple[str, str], ...]
    body: bytes


class ForgeSpotApiApplication:
    """Pure request router over one immutable published-state source."""

    def __init__(self, state_source: ForgeAggregationStateSource) -> None:
        self._state_source = state_source

    def handle(self, method: str, target: str) -> ForgeHttpResponse:
        """Return one deterministic response without provider or storage work."""
        normalized_method = method.strip().upper()
        path = urlsplit(target).path

        if normalized_method != "GET":
            return self._error_response(
                status_code=405,
                error="method_not_allowed",
                message="Only GET is supported by the Forge spot API.",
                extra_headers=(("Allow", "GET"),),
            )

        if path not in {"/api/v1/health", "/api/v1/spots"}:
            return self._error_response(
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

    @classmethod
    def _error_response(
        cls,
        *,
        status_code: int,
        error: str,
        message: str,
        extra_headers: tuple[tuple[str, str], ...] = (),
    ) -> ForgeHttpResponse:
        return cls._json_response(
            status_code,
            {
                "api_schema_version": _API_SCHEMA_VERSION,
                "error": error,
                "message": message,
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


def derive_service_status(state: ForgeAggregationState) -> ForgeServiceStatus:
    """Derive one deterministic overall service status from published state."""
    statuses = {provider.status for provider in state.providers}
    has_storage_error = (
        state.startup_storage_error is not None
        or state.persistence_error is not None
    )

    if statuses == {ForgeProviderHealthStatus.STARTING} and not has_storage_error:
        return ForgeServiceStatus.STARTING

    if (
        statuses == {ForgeProviderHealthStatus.HEALTHY}
        and not has_storage_error
    ):
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
        server_version = "RollingThunderForgeSpots/1"
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
            response = application.handle(self.command, self.path)
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
