"""Private Forge HTTP API implementing the existing Home Platform contact contract."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from json import JSONDecodeError, dumps, loads
from typing import Final
from uuid import UUID

from pydantic import ValidationError

from rolling_thunder.domain import Contact
from rolling_thunder.forge_contact_sync import (
    ForgeContactPayloadConflictError,
    ForgeContactSyncService,
    ForgeContactSyncStorageError,
)
from rolling_thunder.forge_ft8_performance import (
    ForgeFT8PerformanceConflictError,
    ForgeFT8PerformanceService,
    ForgeFT8PerformanceStorageError,
)
from rolling_thunder.ft8.performance import FT8PerformanceAttempt
from rolling_thunder.wavelog import WavelogError

_JSON_CONTENT_TYPE = "application/json; charset=utf-8"
MAX_CONTACT_PAYLOAD_BYTES: Final = 32_768
_LOGGER = logging.getLogger("rolling_thunder.forge_contact_sync")


@dataclass(frozen=True, slots=True)
class ForgeContactHttpResponse:
    """Transport-independent complete HTTP response."""

    status_code: int
    headers: tuple[tuple[str, str], ...]
    body: bytes


class ForgeContactSyncApiApplication:
    """Small deterministic router over the Forge Wavelog synchronization service."""

    def __init__(
        self,
        service: ForgeContactSyncService,
        *,
        ft8_performance_service: ForgeFT8PerformanceService | None = None,
    ) -> None:
        self._service = service
        self._ft8_performance_service = ft8_performance_service

    def handle(
        self,
        method: str,
        target: str,
        *,
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
    ) -> ForgeContactHttpResponse:
        normalized_method = method.strip().upper()
        normalized_target = target.split("?", 1)[0].rstrip("/") or "/"
        request_headers = headers or {}

        if normalized_target == "/health":
            if normalized_method not in {"GET", "HEAD"}:
                return self._error(405, "method_not_allowed", "Only GET is supported.")
            state = self._service.health()
            return self._json(200, state.model_dump(mode="json"))

        if normalized_target == "/ft8-performance":
            return self._handle_ft8_performance(
                normalized_method,
                request_headers,
                body,
            )

        if normalized_target != "/contacts":
            return self._error(404, "not_found", "The requested contact-sync path does not exist.")
        if normalized_method != "POST":
            return self._error(405, "method_not_allowed", "Only POST is supported.")

        content_type = self._header_value(request_headers, "Content-Type")
        if (
            content_type is None
            or content_type.split(";", 1)[0].strip().lower() != "application/json"
        ):
            return self._error(
                415,
                "unsupported_media_type",
                "Contact uploads require application/json.",
            )
        if body is None:
            return self._error(411, "length_required", "Contact uploads require a request body.")
        if len(body) > MAX_CONTACT_PAYLOAD_BYTES:
            return self._error(413, "payload_too_large", "Contact upload exceeds 32768 bytes.")
        if not body:
            return self._error(400, "malformed_json", "Contact upload body must contain JSON.")

        try:
            payload = loads(body.decode("utf-8"))
        except (UnicodeDecodeError, JSONDecodeError):
            return self._error(400, "malformed_json", "Contact upload is not valid UTF-8 JSON.")
        if not isinstance(payload, dict):
            return self._error(400, "invalid_payload", "Contact upload JSON root must be an object.")

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
                "Contact uploads require Idempotency-Key.",
            )
        try:
            idempotency_key = UUID(idempotency_header.strip())
        except ValueError:
            return self._error(
                400,
                "invalid_idempotency_key",
                "Idempotency-Key must be a UUID.",
            )
        if idempotency_key != contact.contact_id:
            return self._error(
                409,
                "idempotency_key_mismatch",
                "Idempotency-Key must match contact_id.",
            )

        try:
            result = self._service.synchronize(contact)
        except ForgeContactPayloadConflictError as error:
            return self._error(409, "idempotency_conflict", str(error))
        except ForgeContactSyncStorageError:
            return self._error(
                503,
                "sync_ledger_unavailable",
                "Forge could not durably update the contact synchronization ledger.",
            )
        except WavelogError as error:
            return self._error(503, "wavelog_unavailable", str(error))

        return self._json(200, result.model_dump(mode="json"))

    def _handle_ft8_performance(
        self,
        method: str,
        headers: Mapping[str, str],
        body: bytes | None,
    ) -> ForgeContactHttpResponse:
        service = self._ft8_performance_service
        if service is None:
            return self._error(
                503,
                "ft8_performance_unavailable",
                "Forge FT8 performance persistence is not configured.",
            )
        if method != "POST":
            return self._error(405, "method_not_allowed", "Only POST is supported.")

        content_type = self._header_value(headers, "Content-Type")
        if (
            content_type is None
            or content_type.split(";", 1)[0].strip().lower() != "application/json"
        ):
            return self._error(
                415,
                "unsupported_media_type",
                "FT8 performance uploads require application/json.",
            )
        if body is None:
            return self._error(
                411,
                "length_required",
                "FT8 performance uploads require a request body.",
            )
        if len(body) > MAX_CONTACT_PAYLOAD_BYTES:
            return self._error(
                413,
                "payload_too_large",
                "FT8 performance upload exceeds 32768 bytes.",
            )
        if not body:
            return self._error(
                400,
                "malformed_json",
                "FT8 performance upload body must contain JSON.",
            )

        try:
            payload = loads(body.decode("utf-8"))
        except (UnicodeDecodeError, JSONDecodeError):
            return self._error(
                400,
                "malformed_json",
                "FT8 performance upload is not valid UTF-8 JSON.",
            )
        if not isinstance(payload, dict):
            return self._error(
                400,
                "invalid_payload",
                "FT8 performance JSON root must be an object.",
            )

        try:
            attempt = FT8PerformanceAttempt.model_validate(payload)
        except ValidationError as error:
            first = error.errors(include_url=False)[0]
            location = ".".join(str(part) for part in first["loc"]) or "payload"
            return self._error(
                422,
                "invalid_ft8_performance",
                f"Invalid FT8 performance field {location}: {first['msg']}"[:500],
            )

        idempotency_header = self._header_value(headers, "Idempotency-Key")
        if idempotency_header is None:
            return self._error(
                400,
                "missing_idempotency_key",
                "FT8 performance uploads require Idempotency-Key.",
            )
        try:
            idempotency_key = UUID(idempotency_header.strip())
        except ValueError:
            return self._error(
                400,
                "invalid_idempotency_key",
                "Idempotency-Key must be a UUID.",
            )
        if idempotency_key != attempt.attempt_id:
            return self._error(
                409,
                "idempotency_key_mismatch",
                "Idempotency-Key must match attempt_id.",
            )

        try:
            result = service.persist(attempt)
        except ForgeFT8PerformanceConflictError as error:
            return self._error(409, "idempotency_conflict", str(error))
        except ForgeFT8PerformanceStorageError:
            return self._error(
                503,
                "ft8_performance_storage_unavailable",
                "Forge could not durably store FT8 performance telemetry.",
            )
        return self._json(200, result.model_dump(mode="json"))

    @classmethod
    def _error(
        cls,
        status_code: int,
        error: str,
        message: str,
    ) -> ForgeContactHttpResponse:
        return cls._json(
            status_code,
            {"error": error, "message": message[:500]},
        )

    @staticmethod
    def _json(status_code: int, payload: object) -> ForgeContactHttpResponse:
        body = dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return ForgeContactHttpResponse(
            status_code=status_code,
            headers=(
                ("Content-Type", _JSON_CONTENT_TYPE),
                ("Content-Length", str(len(body))),
                ("Cache-Control", "no-store"),
            ),
            body=body,
        )

    @staticmethod
    def _header_value(headers: Mapping[str, str], name: str) -> str | None:
        wanted = name.casefold()
        for header_name, value in headers.items():
            if header_name.casefold() == wanted:
                return value
        return None


def make_forge_contact_request_handler(
    application: ForgeContactSyncApiApplication,
    *,
    logger: logging.Logger | None = None,
) -> type[BaseHTTPRequestHandler]:
    """Create a bounded request handler for the private contact-sync API."""
    request_logger = logger or _LOGGER

    class ForgeContactRequestHandler(BaseHTTPRequestHandler):
        server_version = "RollingThunderForgeContact/1"
        protocol_version = "HTTP/1.1"

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
            upload_path = self.path.split("?", 1)[0].rstrip("/")
            if self.command == "POST" and upload_path in {"/contacts", "/ft8-performance"}:
                body_or_error = self._read_upload_body(upload_path)
                if isinstance(body_or_error, ForgeContactHttpResponse):
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

        def _read_upload_body(
            self,
            upload_path: str,
        ) -> bytes | ForgeContactHttpResponse:
            raw_length = self.headers.get("Content-Length")
            if raw_length is None:
                return application._error(
                    411,
                    "length_required",
                    (
                        "Contact uploads require Content-Length."
                        if upload_path == "/contacts"
                        else "FT8 performance uploads require Content-Length."
                    ),
                )
            try:
                length = int(raw_length, 10)
            except ValueError:
                self.close_connection = True
                return application._error(
                    400,
                    "invalid_content_length",
                    "Content-Length must be a non-negative decimal integer.",
                )
            if length < 0:
                self.close_connection = True
                return application._error(
                    400,
                    "invalid_content_length",
                    "Content-Length must be a non-negative decimal integer.",
                )
            if length > MAX_CONTACT_PAYLOAD_BYTES:
                self.close_connection = True
                return application._error(
                    413,
                    "payload_too_large",
                    (
                        "Contact upload exceeds 32768 bytes."
                        if upload_path == "/contacts"
                        else "FT8 performance upload exceeds 32768 bytes."
                    ),
                )
            return self.rfile.read(length)

        def _send_response(self, response: ForgeContactHttpResponse) -> None:
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

    return ForgeContactRequestHandler


class ForgeContactHttpServer:
    """Lifecycle wrapper around the private threaded contact-sync server."""

    def __init__(
        self,
        bind_host: str,
        bind_port: int,
        application: ForgeContactSyncApiApplication,
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        handler = make_forge_contact_request_handler(application, logger=logger)
        self._server = ThreadingHTTPServer((bind_host, bind_port), handler)
        self._server.daemon_threads = True

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
