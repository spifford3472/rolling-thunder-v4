"""Transport-independent authenticated FT8-attempt ingestion and diagnostics API."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from hmac import compare_digest
from json import JSONDecodeError, dumps, loads
from uuid import UUID

from pydantic import ValidationError

from rolling_thunder.forge_ft8_attempt_correlation import (
    AttemptInboxConflict,
    AttemptInboxRepository,
    VoacapAttemptHistoryRepository,
)
from rolling_thunder.ft8.attempt_ledger import FT8AttemptEvent

MAX_ATTEMPT_PAYLOAD_BYTES = 131_072


@dataclass(frozen=True, slots=True)
class AttemptApiResponse:
    status_code: int
    body: bytes
    headers: tuple[tuple[str, str], ...] = ()


class FT8AttemptApiApplication:
    def __init__(
        self,
        inbox: AttemptInboxRepository,
        history: VoacapAttemptHistoryRepository,
        *,
        bearer_token: str,
        ingestion_enabled: bool,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if len(bearer_token) < 32 or any(char.isspace() for char in bearer_token):
            raise ValueError("attempt API bearer token must be at least 32 characters")
        self._inbox = inbox
        self._history = history
        self._token = bearer_token
        self._enabled = ingestion_enabled
        self._clock = clock

    def handle(
        self,
        method: str,
        target: str,
        *,
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
    ) -> AttemptApiResponse:
        method = method.upper()
        path = target.split("?", 1)[0].rstrip("/") or "/"
        request_headers = headers or {}
        preflight = self.preflight(request_headers, require_enabled=method == "POST")
        if preflight is not None:
            return preflight
        diagnostics_prefix = "/api/v1/ft8-attempts/"
        if method == "GET" and path.startswith(diagnostics_prefix):
            try:
                attempt_uuid = UUID(path.removeprefix(diagnostics_prefix))
            except ValueError:
                return self._json(400, {"error": "invalid_attempt_uuid"})
            inbox = self._inbox.snapshot(attempt_uuid)
            if inbox is None:
                return self._json(404, {"error": "not_found"})
            return self._json(
                200,
                {
                    "attempt": inbox,
                    "voacap": self._history.diagnostics(attempt_uuid),
                },
            )
        if path != "/api/v1/ft8-attempts":
            return self._json(404, {"error": "not_found"})
        if method != "POST":
            return self._json(405, {"error": "method_not_allowed"})
        if body is None or not body:
            return self._json(400, {"error": "missing_body"})
        if len(body) > MAX_ATTEMPT_PAYLOAD_BYTES:
            return self._json(413, {"error": "payload_too_large"})
        if (_header(request_headers, "Content-Type") or "").split(";", 1)[
            0
        ].lower() != "application/json":
            return self._json(415, {"error": "unsupported_media_type"})
        try:
            payload = loads(body)
            event = FT8AttemptEvent.model_validate(payload)
        except (JSONDecodeError, UnicodeDecodeError, ValidationError):
            return self._json(422, {"error": "invalid_event"})
        supplied_key = _header(request_headers, "Idempotency-Key")
        try:
            key = UUID(supplied_key or "")
        except ValueError:
            return self._json(400, {"error": "invalid_idempotency_key"})
        if key != event.attempt_uuid:
            return self._json(409, {"error": "idempotency_key_mismatch"})
        now = self._now()
        try:
            accepted = self._inbox.enqueue(event, received_at_utc=now)
        except AttemptInboxConflict:
            return self._json(409, {"error": "idempotency_conflict"})
        return self._json(
            202 if accepted else 200,
            {
                "schema_version": "1",
                "attempt_uuid": str(event.attempt_uuid),
                "disposition": "accepted" if accepted else "replayed",
                "received_at_utc": now,
            },
        )

    def preflight(
        self, headers: Mapping[str, str], *, require_enabled: bool
    ) -> AttemptApiResponse | None:
        """Authenticate before a server reads the bounded request body."""
        if require_enabled and not self._enabled:
            return self._json(503, {"error": "ingestion_disabled"})
        if not self._authorized(headers):
            return self._json(401, {"error": "unauthorized"})
        return None

    def health(self, *, now_utc: datetime) -> dict[str, object]:
        """Provider-free health extension for the shared private listener."""
        return {
            "ingestion_enabled": self._enabled,
            "queue": self._inbox.observe(now_utc=now_utc),
        }

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("attempt API clock must be timezone-aware")
        return value.astimezone(UTC)

    def _authorized(self, headers: Mapping[str, str]) -> bool:
        value = _header(headers, "Authorization") or ""
        scheme, separator, supplied = value.partition(" ")
        return (
            bool(separator) and scheme.lower() == "bearer" and compare_digest(supplied, self._token)
        )

    @staticmethod
    def _json(status: int, payload: object) -> AttemptApiResponse:
        body = dumps(payload, separators=(",", ":"), default=str).encode()
        return AttemptApiResponse(
            status,
            body,
            (
                ("Content-Type", "application/json; charset=utf-8"),
                ("Content-Length", str(len(body))),
                ("Cache-Control", "no-store"),
            ),
        )


def _header(headers: Mapping[str, str], name: str) -> str | None:
    expected = name.lower()
    return next((value for key, value in headers.items() if key.lower() == expected), None)
