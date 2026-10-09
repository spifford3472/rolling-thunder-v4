"""Authenticated bounded HTTP ingestion for completed-QSO propagation work."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from hmac import compare_digest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from json import JSONDecodeError, dumps, loads
from threading import BoundedSemaphore
from typing import Final
from uuid import UUID

from pydantic import ValidationError

from rolling_thunder.domain import Contact
from rolling_thunder.forge_propagation_qso_ingestion import (
    CompletedQsoEnqueueResult,
    CompletedQsoIdempotencyConflict,
    CompletedQsoIngestionError,
    CompletedQsoIngestionRepository,
)

MAX_COMPLETED_QSO_PAYLOAD_BYTES: Final = 32_768
_JSON_CONTENT_TYPE = "application/json; charset=utf-8"
_INGESTION_PATH = "/api/v1/completed-qsos"
_LOGGER = logging.getLogger("rolling_thunder.forge_propagation_qso_worker")
Clock = Callable[[], datetime]


@dataclass(frozen=True, slots=True)
class CompletedQsoHttpResponse:
    """Transport-independent complete HTTP response."""

    status_code: int
    headers: tuple[tuple[str, str], ...]
    body: bytes


class CompletedQsoIngestionApiApplication:
    """Validate and durably enqueue authenticated immutable QSO snapshots."""

    def __init__(
        self,
        repository: CompletedQsoIngestionRepository,
        *,
        bearer_token: str,
        ingestion_enabled: bool,
        voacap_enabled: bool,
        clock: Clock = lambda: datetime.now(UTC),
    ) -> None:
        if len(bearer_token) < 32:
            raise ValueError("completed-QSO ingestion bearer token must be at least 32 characters")
        self._repository = repository
        self._bearer_token = bearer_token
        self._ingestion_enabled = ingestion_enabled
        self._voacap_enabled = voacap_enabled
        self._clock = clock

    def handle(
        self,
        method: str,
        target: str,
        *,
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
    ) -> CompletedQsoHttpResponse:
        normalized_method = method.strip().upper()
        normalized_target = target.split("?", 1)[0].rstrip("/") or "/"
        request_headers = headers or {}

        if normalized_target == "/health":
            if normalized_method not in {"GET", "HEAD"}:
                return self._error(405, "method_not_allowed", "Only GET is supported.")
            try:
                queue = self._repository.observe(now_utc=self._now())
            except CompletedQsoIngestionError:
                return self._error(
                    503,
                    "ingestion_storage_unavailable",
                    "Completed-QSO ingestion storage is unavailable.",
                )
            return self._json(
                200,
                {
                    "schema_version": "1",
                    "service": "rolling-thunder-forge-propagation-qso",
                    "ingestion_enabled": self._ingestion_enabled,
                    "voacap_enabled": self._voacap_enabled,
                    "queue": queue.model_dump(mode="json"),
                },
            )

        if normalized_target != _INGESTION_PATH:
            return self._error(404, "not_found", "The requested path does not exist.")
        if normalized_method != "POST":
            return self._error(405, "method_not_allowed", "Only POST is supported.")
        preflight_error = self.preflight_upload(request_headers)
        if preflight_error is not None:
            return preflight_error

        content_type = self._header_value(request_headers, "Content-Type")
        if (
            content_type is None
            or content_type.split(";", 1)[0].strip().lower() != "application/json"
        ):
            return self._error(
                415,
                "unsupported_media_type",
                "Completed-QSO uploads require application/json.",
            )
        if body is None:
            return self._error(411, "length_required", "Completed-QSO uploads require a body.")
        if len(body) > MAX_COMPLETED_QSO_PAYLOAD_BYTES:
            return self._error(413, "payload_too_large", "Completed-QSO upload is too large.")
        if not body:
            return self._error(400, "malformed_json", "Completed-QSO body must contain JSON.")

        try:
            payload = loads(body.decode("utf-8"))
        except (UnicodeDecodeError, JSONDecodeError):
            return self._error(400, "malformed_json", "Upload is not valid UTF-8 JSON.")
        if not isinstance(payload, dict):
            return self._error(400, "invalid_payload", "Upload JSON root must be an object.")
        try:
            contact = Contact.model_validate(payload)
        except ValidationError as error:
            first = error.errors(include_url=False)[0]
            location = ".".join(str(part) for part in first["loc"]) or "payload"
            return self._error(
                422,
                "invalid_contact",
                f"Invalid contact field {location}: {first['msg']}"[:500],
            )

        idempotency_header = self._header_value(request_headers, "Idempotency-Key")
        if idempotency_header is None:
            return self._error(
                400,
                "missing_idempotency_key",
                "Completed-QSO uploads require Idempotency-Key.",
            )
        try:
            idempotency_key = UUID(idempotency_header.strip())
        except ValueError:
            return self._error(400, "invalid_idempotency_key", "Idempotency-Key must be a UUID.")
        if idempotency_key != contact.contact_id:
            return self._error(
                409,
                "idempotency_key_mismatch",
                "Idempotency-Key must match contact_id.",
            )

        received_at = self._now()
        try:
            disposition = self._repository.enqueue(contact, queued_at_utc=received_at)
        except CompletedQsoIdempotencyConflict as error:
            return self._error(409, "idempotency_conflict", str(error))
        except CompletedQsoIngestionError:
            return self._error(
                503,
                "ingestion_storage_unavailable",
                "Forge could not durably enqueue the completed QSO.",
            )
        status = 202 if disposition is CompletedQsoEnqueueResult.ACCEPTED else 200
        return self._json(
            status,
            {
                "schema_version": "1",
                "contact_id": str(contact.contact_id),
                "disposition": disposition.value,
                "received_at_utc": received_at,
            },
        )

    def preflight_upload(
        self, headers: Mapping[str, str]
    ) -> CompletedQsoHttpResponse | None:
        """Reject disabled or unauthenticated uploads before reading their body."""
        if not self._ingestion_enabled:
            return self._error(503, "ingestion_disabled", "Completed-QSO ingestion is disabled.")
        if not self._authorized(headers):
            return self._error(
                401,
                "unauthorized",
                "A valid bearer token is required.",
                extra_headers=(("WWW-Authenticate", "Bearer"),),
            )
        return None

    def _authorized(self, headers: Mapping[str, str]) -> bool:
        authorization = self._header_value(headers, "Authorization")
        if authorization is None:
            return False
        scheme, separator, supplied = authorization.partition(" ")
        return (
            bool(separator)
            and scheme.lower() == "bearer"
            and bool(supplied)
            and compare_digest(supplied, self._bearer_token)
        )

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("completed-QSO ingestion clock must be timezone-aware")
        return value.astimezone(UTC)

    @staticmethod
    def _header_value(headers: Mapping[str, str], name: str) -> str | None:
        expected = name.lower()
        return next((value for key, value in headers.items() if key.lower() == expected), None)

    @staticmethod
    def _json(status_code: int, payload: object) -> CompletedQsoHttpResponse:
        body = dumps(payload, separators=(",", ":"), default=str).encode("utf-8")
        return CompletedQsoHttpResponse(
            status_code=status_code,
            headers=(
                ("Content-Type", _JSON_CONTENT_TYPE),
                ("Content-Length", str(len(body))),
                ("Cache-Control", "no-store"),
            ),
            body=body,
        )

    @classmethod
    def _error(
        cls,
        status_code: int,
        code: str,
        message: str,
        *,
        extra_headers: tuple[tuple[str, str], ...] = (),
    ) -> CompletedQsoHttpResponse:
        response = cls._json(status_code, {"error": {"code": code, "message": message}})
        return CompletedQsoHttpResponse(
            status_code=response.status_code,
            headers=response.headers + extra_headers,
            body=response.body,
        )


class _BoundedThreadingHttpServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False
    request_queue_size = 32

    def __init__(self, *args: object, max_connections: int, **kwargs: object) -> None:
        self._connection_slots = BoundedSemaphore(max_connections)
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]

    def process_request(self, request: object, client_address: object) -> None:
        self._connection_slots.acquire()
        try:
            super().process_request(request, client_address)  # type: ignore[arg-type]
        except BaseException:
            self._connection_slots.release()
            raise

    def shutdown_request(self, request: object) -> None:
        try:
            super().shutdown_request(request)  # type: ignore[arg-type]
        finally:
            self._connection_slots.release()


def make_completed_qso_request_handler(
    application: CompletedQsoIngestionApiApplication,
    *,
    request_timeout_s: float,
    logger: logging.Logger | None = None,
) -> type[BaseHTTPRequestHandler]:
    """Create a size- and time-bounded request handler."""
    request_logger = logger or _LOGGER

    class CompletedQsoRequestHandler(BaseHTTPRequestHandler):
        server_version = "RollingThunderPropagationQso/1"
        protocol_version = "HTTP/1.1"

        def setup(self) -> None:
            super().setup()
            self.connection.settimeout(request_timeout_s)

        def do_GET(self) -> None:
            self._dispatch()

        def do_HEAD(self) -> None:
            self._dispatch()

        def do_POST(self) -> None:
            self._dispatch()

        def do_PUT(self) -> None:
            self._dispatch()

        def do_DELETE(self) -> None:
            self._dispatch()

        def _dispatch(self) -> None:
            body: bytes | None = None
            request_path = self.path.split("?", 1)[0].rstrip("/")
            if self.command == "POST" and request_path == _INGESTION_PATH:
                request_headers = {name: value for name, value in self.headers.items()}
                preflight_error = application.preflight_upload(request_headers)
                if preflight_error is not None:
                    self.close_connection = True
                    self._send_response(preflight_error)
                    return
                body_or_error = self._read_body()
                if isinstance(body_or_error, CompletedQsoHttpResponse):
                    self._send_response(body_or_error)
                    return
                body = body_or_error
            elif self.command in {"POST", "PUT", "DELETE"}:
                # Never leave an unconsumed body on a reusable connection for an
                # unsupported route or method.
                self.close_connection = True
            response = application.handle(
                self.command,
                self.path,
                headers={name: value for name, value in self.headers.items()},
                body=body,
            )
            self._send_response(response)

        def _read_body(self) -> bytes | CompletedQsoHttpResponse:
            raw_length = self.headers.get("Content-Length")
            if raw_length is None:
                return application._error(
                    411, "length_required", "Completed-QSO uploads require Content-Length."
                )
            try:
                length = int(raw_length, 10)
            except ValueError:
                self.close_connection = True
                return application._error(
                    400, "invalid_content_length", "Content-Length must be non-negative."
                )
            if length < 0:
                self.close_connection = True
                return application._error(
                    400, "invalid_content_length", "Content-Length must be non-negative."
                )
            if length > MAX_COMPLETED_QSO_PAYLOAD_BYTES:
                self.close_connection = True
                return application._error(
                    413, "payload_too_large", "Completed-QSO upload is too large."
                )
            try:
                return self.rfile.read(length)
            except TimeoutError:
                self.close_connection = True
                return application._error(408, "request_timeout", "Request body timed out.")

        def _send_response(self, response: CompletedQsoHttpResponse) -> None:
            self.send_response(response.status_code)
            for name, value in response.headers:
                self.send_header(name, value)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(response.body)

        def log_message(self, format_string: str, *args: object) -> None:
            request_logger.info("%s - %s", self.address_string(), format_string % args)

    return CompletedQsoRequestHandler


class CompletedQsoHttpServer:
    """Lifecycle wrapper around the private bounded ingestion server."""

    def __init__(
        self,
        bind_host: str,
        bind_port: int,
        application: CompletedQsoIngestionApiApplication,
        *,
        request_timeout_s: float,
        max_connections: int,
        logger: logging.Logger | None = None,
    ) -> None:
        handler = make_completed_qso_request_handler(
            application,
            request_timeout_s=request_timeout_s,
            logger=logger,
        )
        self._server = _BoundedThreadingHttpServer(
            (bind_host, bind_port), handler, max_connections=max_connections
        )

    @property
    def server_address(self) -> tuple[str, int]:
        host, port = self._server.server_address[:2]
        return str(host), int(port)

    def serve_forever(self) -> None:
        self._server.serve_forever(poll_interval=0.5)

    def shutdown(self) -> None:
        self._server.shutdown()

    def close(self) -> None:
        self._server.server_close()
