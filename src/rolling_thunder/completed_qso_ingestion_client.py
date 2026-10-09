"""Typed producer client for the Forge completed-QSO ingestion contract."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from json import JSONDecodeError, dumps, loads
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from uuid import UUID

from pydantic import Field, ValidationError, field_validator

from rolling_thunder.domain import Contact, DomainModel
from rolling_thunder.forge_propagation_qso_ingestion import CompletedQsoEnqueueResult


class CompletedQsoProducerError(RuntimeError):
    """Raised when a completed QSO cannot be durably handed to Forge."""


class CompletedQsoIngestionResult(DomainModel):
    """Validated acknowledgement from the durable Forge inbox."""

    schema_version: str = Field(pattern=r"^1$")
    contact_id: UUID
    disposition: CompletedQsoEnqueueResult
    received_at_utc: datetime

    @field_validator("received_at_utc")
    @classmethod
    def normalize_received_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("must include timezone information")
        return value.astimezone(UTC)


class CompletedQsoHttpResponse(Protocol):
    @property
    def status_code(self) -> int: ...

    @property
    def body(self) -> bytes: ...


class CompletedQsoHttpTransport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout_s: float,
    ) -> CompletedQsoHttpResponse: ...


class _UrllibResponse:
    def __init__(self, status_code: int, body: bytes) -> None:
        self.status_code = status_code
        self.body = body


class UrllibCompletedQsoHttpTransport:
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout_s: float,
    ) -> _UrllibResponse:
        request = Request(url=url, data=body, headers=dict(headers), method=method)
        try:
            with urlopen(request, timeout=timeout_s) as response:
                return _UrllibResponse(response.status, response.read())
        except HTTPError as error:
            return _UrllibResponse(error.code, error.read())


class HttpCompletedQsoIngestionClient:
    """Send immutable contacts to the authenticated UUID-idempotent Forge API."""

    def __init__(
        self,
        base_url: str,
        *,
        bearer_token: str,
        timeout_s: float = 5.0,
        transport: CompletedQsoHttpTransport | None = None,
    ) -> None:
        parsed = urlparse(base_url.rstrip("/"))
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("completed-QSO ingestion base URL must be absolute HTTP(S)")
        if parsed.query or parsed.fragment:
            raise ValueError("completed-QSO ingestion base URL must not include query or fragment")
        if len(bearer_token) < 32:
            raise ValueError("completed-QSO ingestion bearer token must be at least 32 characters")
        if timeout_s <= 0:
            raise ValueError("completed-QSO ingestion timeout must be positive")
        self._base_url = base_url.rstrip("/")
        self._bearer_token = bearer_token
        self._timeout_s = timeout_s
        self._transport = transport or UrllibCompletedQsoHttpTransport()

    def enqueue(self, contact: Contact) -> CompletedQsoIngestionResult:
        """Perform one bounded authenticated delivery; callers own durable retry."""
        body = dumps(contact.model_dump(mode="json"), separators=(",", ":")).encode("utf-8")
        try:
            response = self._transport.request(
                "POST",
                f"{self._base_url}/api/v1/completed-qsos",
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {self._bearer_token}",
                    "Content-Type": "application/json",
                    "Idempotency-Key": str(contact.contact_id),
                },
                body=body,
                timeout_s=self._timeout_s,
            )
        except (TimeoutError, URLError, OSError) as error:
            raise CompletedQsoProducerError(
                "completed-QSO ingestion service could not be reached"
            ) from error
        if response.status_code not in {200, 202}:
            raise CompletedQsoProducerError(
                f"completed-QSO ingestion returned HTTP {response.status_code}"
            )
        try:
            payload = loads(response.body.decode("utf-8"))
            result = CompletedQsoIngestionResult.model_validate(payload)
        except (UnicodeDecodeError, JSONDecodeError, ValidationError) as error:
            raise CompletedQsoProducerError(
                "completed-QSO ingestion returned an invalid acknowledgement"
            ) from error
        if result.contact_id != contact.contact_id:
            raise CompletedQsoProducerError(
                "completed-QSO ingestion acknowledged a different contact ID"
            )
        return result
