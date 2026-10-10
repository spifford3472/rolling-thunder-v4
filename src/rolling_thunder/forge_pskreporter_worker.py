"""Authenticated ingestion, scheduling, and diagnostics for PSK Reporter analysis."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hmac import compare_digest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from json import JSONDecodeError, dumps, loads
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Literal, Protocol
from uuid import UUID, uuid4

from pydantic import ValidationError, field_validator

from rolling_thunder.domain import DomainModel
from rolling_thunder.forge_propagation_history import PropagationHistoryStorageError
from rolling_thunder.forge_pskreporter_orchestration import (
    CompletedFt8EventConflict,
    CompletedFt8QsoEvent,
    CompletedFt8QsoEventSink,
    PskReporterOrchestrationError,
    PskReporterOrchestrationHealth,
    PskReporterOrchestrationRepository,
    PskReporterWorkerResult,
)

_JSON_CONTENT_TYPE = "application/json; charset=utf-8"
_EVENT_PATH = "/api/v1/completed-ft8-events"
_HEALTH_PATH = "/api/v1/health"
_LOGGER = logging.getLogger("rolling_thunder.forge_pskreporter_worker")


class ForgePskReporterWorkerSnapshot(DomainModel):
    """Versioned, non-secret state from one independently scheduled cycle."""

    schema_version: Literal["1"] = "1"
    service: Literal["forge-pskreporter-worker"] = "forge-pskreporter-worker"
    observed_at_utc: datetime
    ingestion_enabled: bool
    provider_enabled: bool
    result: PskReporterWorkerResult | None = None
    health: PskReporterOrchestrationHealth | None = None
    runtime_error: str | None = None

    @field_validator("observed_at_utc")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("worker status time must be timezone-aware")
        return value.astimezone(UTC)


class PskReporterWorkerStatusPublisher(Protocol):
    def publish(self, snapshot: ForgePskReporterWorkerSnapshot) -> None: ...


class ScheduledPskReporterWorker(Protocol):
    def run_once(self, *, now_utc: datetime) -> PskReporterWorkerResult: ...


class JsonFilePskReporterWorkerStatusPublisher:
    """Atomically publish provider-free diagnostics without secrets or event bodies."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def publish(self, snapshot: ForgePskReporterWorkerSnapshot) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_name(f".{self._path.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_text(snapshot.model_dump_json(indent=2) + "\n", encoding="utf-8")
            os.replace(temporary, self._path)
        finally:
            temporary.unlink(missing_ok=True)


class ForgePskReporterWorkerRuntime:
    """Run one bounded worker cycle and publish its durable queue health."""

    def __init__(
        self,
        worker: ScheduledPskReporterWorker,
        repository: PskReporterOrchestrationRepository,
        *,
        ingestion_enabled: bool,
        provider_enabled: bool,
        minimum_interval: timedelta,
        publisher: PskReporterWorkerStatusPublisher,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._worker = worker
        self._repository = repository
        self._ingestion_enabled = ingestion_enabled
        self._provider_enabled = provider_enabled
        self._minimum_interval = minimum_interval
        self._publisher = publisher
        self._clock = clock
        self._latest: ForgePskReporterWorkerSnapshot | None = None
        self._lock = Lock()

    def run_once(self) -> ForgePskReporterWorkerSnapshot:
        now = self._clock()
        result = self._worker.run_once(now_utc=now)
        health = self._repository.health(
            now_utc=now,
            enabled=self._provider_enabled,
            minimum_interval=self._minimum_interval,
        )
        snapshot = ForgePskReporterWorkerSnapshot(
            observed_at_utc=now,
            ingestion_enabled=self._ingestion_enabled,
            provider_enabled=self._provider_enabled,
            result=result,
            health=health,
        )
        self._publish(snapshot)
        return snapshot

    def publish_failure(self, error: BaseException) -> ForgePskReporterWorkerSnapshot:
        """Publish a bounded scheduler error while preserving last durable health if readable."""
        now = self._clock()
        try:
            health = self._repository.health(
                now_utc=now,
                enabled=self._provider_enabled,
                minimum_interval=self._minimum_interval,
            )
        except (OSError, ValueError, PskReporterOrchestrationError):
            health = None
        snapshot = ForgePskReporterWorkerSnapshot(
            observed_at_utc=now,
            ingestion_enabled=self._ingestion_enabled,
            provider_enabled=self._provider_enabled,
            health=health,
            runtime_error=_bounded_error(error),
        )
        self._publish(snapshot)
        return snapshot

    def latest(self) -> ForgePskReporterWorkerSnapshot | None:
        with self._lock:
            return self._latest

    def _publish(self, snapshot: ForgePskReporterWorkerSnapshot) -> None:
        self._publisher.publish(snapshot)
        with self._lock:
            self._latest = snapshot


class ForgePskReporterScheduler:
    """Own one stoppable scheduler thread; exceptions degrade status, not the API."""

    def __init__(
        self,
        runtime: ForgePskReporterWorkerRuntime,
        *,
        interval_s: float,
        logger: logging.Logger | None = None,
    ) -> None:
        if interval_s <= 0:
            raise ValueError("scheduler interval must be positive")
        self._runtime = runtime
        self._interval_s = interval_s
        self._logger = logger or _LOGGER
        self._stop = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("PSK Reporter scheduler is already running")
        self._stop.clear()
        self._thread = Thread(target=self._run, name="forge-pskreporter-worker", daemon=False)
        self._thread.start()

    def stop(self) -> None:
        thread = self._thread
        if thread is None:
            return
        self._stop.set()
        thread.join(timeout=max(5.0, self._interval_s + 1.0))
        if thread.is_alive():
            raise RuntimeError("PSK Reporter scheduler did not stop")
        self._thread = None

    def is_running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                snapshot = self._runtime.run_once()
                self._logger.info(
                    "cycle=%s pending=%s due=%s completed=%s expired=%s",
                    snapshot.result.disposition.value if snapshot.result else "unknown",
                    snapshot.health.pending_count if snapshot.health else "unknown",
                    snapshot.health.due_count if snapshot.health else "unknown",
                    snapshot.health.completed_count if snapshot.health else "unknown",
                    snapshot.health.expired_count if snapshot.health else "unknown",
                )
            except (
                OSError,
                ValueError,
                PskReporterOrchestrationError,
                PropagationHistoryStorageError,
            ) as error:
                try:
                    self._runtime.publish_failure(error)
                except (OSError, ValueError, PskReporterOrchestrationError) as status_error:
                    self._logger.error(
                        "PSK Reporter status publication failed: %s",
                        _bounded_error(status_error),
                    )
                self._logger.error("PSK Reporter worker cycle failed: %s", _bounded_error(error))
            if self._stop.wait(self._interval_s):
                return


@dataclass(frozen=True, slots=True)
class ForgePskReporterHttpResponse:
    status_code: int
    headers: tuple[tuple[str, str], ...]
    body: bytes


class ForgePskReporterApiApplication:
    """Bounded private API for one authenticated, authority-owning producer."""

    def __init__(
        self,
        sink: CompletedFt8QsoEventSink,
        health_provider: Callable[[], ForgePskReporterWorkerSnapshot],
        *,
        ingestion_enabled: bool,
        bearer_token: str | None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if ingestion_enabled and (
            bearer_token is None
            or len(bearer_token) < 32
            or any(character.isspace() for character in bearer_token)
        ):
            raise ValueError("enabled ingestion requires a bearer token of at least 32 characters")
        self._sink = sink
        self._health_provider = health_provider
        self._ingestion_enabled = ingestion_enabled
        self._bearer_token = bearer_token
        self._clock = clock

    def handle(
        self,
        method: str,
        target: str,
        *,
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
    ) -> ForgePskReporterHttpResponse:
        normalized_method = method.strip().upper()
        normalized_target = target.split("?", 1)[0].rstrip("/") or "/"
        request_headers = headers or {}
        if normalized_target == _HEALTH_PATH:
            if normalized_method not in {"GET", "HEAD"}:
                return self._error(405, "method_not_allowed", "Only GET is supported.")
            try:
                snapshot = self._health_provider()
            except (OSError, ValueError, PskReporterOrchestrationError):
                return self._error(503, "health_unavailable", "Worker health is unavailable.")
            return self._json(200, snapshot.model_dump(mode="json"))
        if normalized_target != _EVENT_PATH:
            return self._error(404, "not_found", "The requested PSK worker path does not exist.")
        if normalized_method != "POST":
            return self._error(405, "method_not_allowed", "Only POST is supported.")
        if not self._ingestion_enabled:
            return self._error(503, "ingestion_disabled", "Completed-FT8 ingestion is disabled.")
        if not self._authorized(request_headers):
            return self._error(401, "unauthorized", "Valid bearer authentication is required.")
        content_type = _header_value(request_headers, "Content-Type")
        if content_type is None or content_type.split(";", 1)[0].strip().lower() != "application/json":
            return self._error(415, "unsupported_media_type", "Events require application/json.")
        if body is None:
            return self._error(411, "length_required", "Events require a request body.")
        if not body:
            return self._error(400, "malformed_json", "Event body must contain JSON.")
        try:
            payload = loads(body.decode("utf-8"))
        except (UnicodeDecodeError, JSONDecodeError):
            return self._error(400, "malformed_json", "Event is not valid UTF-8 JSON.")
        if not isinstance(payload, dict):
            return self._error(400, "invalid_payload", "Event JSON root must be an object.")
        try:
            event = CompletedFt8QsoEvent.model_validate(payload)
        except ValidationError as error:
            first = error.errors(include_url=False)[0]
            location = ".".join(str(part) for part in first["loc"]) or "payload"
            return self._error(
                422,
                "invalid_completed_ft8_event",
                f"Invalid completed-FT8 event field {location}: {first['msg']}"[:500],
            )
        idempotency_header = _header_value(request_headers, "Idempotency-Key")
        if idempotency_header is None:
            return self._error(400, "missing_idempotency_key", "Events require Idempotency-Key.")
        try:
            idempotency_key = UUID(idempotency_header.strip())
        except ValueError:
            return self._error(400, "invalid_idempotency_key", "Idempotency-Key must be a UUID.")
        if idempotency_key != event.contact.contact_id:
            return self._error(
                409,
                "idempotency_key_mismatch",
                "Idempotency-Key must match the contact and attempt UUID.",
            )
        try:
            disposition = self._sink.enqueue(event, received_at_utc=self._clock())
        except CompletedFt8EventConflict as error:
            return self._error(409, "event_conflict", str(error))
        except (OSError, ValueError, PskReporterOrchestrationError):
            return self._error(503, "event_store_unavailable", "Event could not be durably stored.")
        return self._json(
            202,
            {
                "schema_version": "1",
                "contact_id": str(event.contact.contact_id),
                "disposition": disposition.value,
            },
        )

    def _authorized(self, headers: Mapping[str, str]) -> bool:
        authorization = _header_value(headers, "Authorization")
        if authorization is None or self._bearer_token is None:
            return False
        scheme, separator, credential = authorization.partition(" ")
        return bool(
            separator
            and scheme.lower() == "bearer"
            and credential
            and compare_digest(credential, self._bearer_token)
        )

    @staticmethod
    def _json(status_code: int, payload: object) -> ForgePskReporterHttpResponse:
        body = dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return ForgePskReporterHttpResponse(
            status_code,
            (("Content-Type", _JSON_CONTENT_TYPE), ("Content-Length", str(len(body)))),
            body,
        )

    @classmethod
    def _error(cls, status_code: int, code: str, message: str) -> ForgePskReporterHttpResponse:
        return cls._json(status_code, {"error": {"code": code, "message": message}})


def make_forge_pskreporter_request_handler(
    application: ForgePskReporterApiApplication,
    *,
    maximum_event_bytes: int,
    logger: logging.Logger | None = None,
) -> type[BaseHTTPRequestHandler]:
    """Create a request handler that bounds bodies before allocating or parsing them."""
    request_logger = logger or _LOGGER

    class Handler(BaseHTTPRequestHandler):
        server_version = "RollingThunderForgePskReporter/1"
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
            normalized_path = self.path.split("?", 1)[0].rstrip("/")
            if self.command == "POST" and normalized_path == _EVENT_PATH:
                body_or_error = self._read_event_body()
                if isinstance(body_or_error, ForgePskReporterHttpResponse):
                    self._send(body_or_error)
                    return
                body = body_or_error
            response = application.handle(
                self.command,
                self.path,
                headers={name: value for name, value in self.headers.items()},
                body=body,
            )
            self._send(response)

        def _read_event_body(self) -> bytes | ForgePskReporterHttpResponse:
            raw_length = self.headers.get("Content-Length")
            if raw_length is None:
                return application._error(411, "length_required", "Events require Content-Length.")
            try:
                length = int(raw_length, 10)
            except ValueError:
                self.close_connection = True
                return application._error(
                    400, "invalid_content_length", "Content-Length must be a non-negative integer."
                )
            if length < 0:
                self.close_connection = True
                return application._error(
                    400, "invalid_content_length", "Content-Length must be a non-negative integer."
                )
            if length > maximum_event_bytes:
                self.close_connection = True
                return application._error(413, "payload_too_large", "Event exceeds configured limit.")
            return self.rfile.read(length)

        def _send(self, response: ForgePskReporterHttpResponse) -> None:
            self.send_response(response.status_code)
            for name, value in response.headers:
                self.send_header(name, value)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(response.body)

        def log_message(self, format_string: str, *args: object) -> None:
            request_logger.info("%s - %s", self.address_string(), format_string % args)

    return Handler


class ForgePskReporterHttpServer:
    def __init__(
        self,
        bind_host: str,
        bind_port: int,
        application: ForgePskReporterApiApplication,
        *,
        maximum_event_bytes: int,
        logger: logging.Logger | None = None,
    ) -> None:
        handler = make_forge_pskreporter_request_handler(
            application,
            maximum_event_bytes=maximum_event_bytes,
            logger=logger,
        )
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


def _header_value(headers: Mapping[str, str], name: str) -> str | None:
    target = name.casefold()
    return next((value for key, value in headers.items() if key.casefold() == target), None)


def _bounded_error(error: BaseException) -> str:
    text = f"{type(error).__name__}: {error}".replace("\r", " ").replace("\n", " ")
    return text[:500]
