"""Typed producer client for the Forge completed-FT8 PSK ingestion contract."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from json import JSONDecodeError, dumps, loads
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from uuid import UUID

from pydantic import Field, ValidationError

from rolling_thunder.domain import DomainModel
from rolling_thunder.forge_pskreporter_orchestration import CompletedFt8QsoEvent


class CompletedFt8IngestionError(RuntimeError):
    """Raised when a completed-FT8 event is not durably acknowledged by Forge."""


class CompletedFt8IngestionDisposition(StrEnum):
    ACCEPTED = "accepted"
    REPLAYED = "replayed"


class CompletedFt8IngestionResult(DomainModel):
    """Validated acknowledgement from the durable PSK event inbox."""

    schema_version: str = Field(pattern=r"^1$")
    contact_id: UUID
    disposition: CompletedFt8IngestionDisposition


class CompletedFt8HttpResponse(Protocol):
    @property
    def status_code(self) -> int: ...

    @property
    def body(self) -> bytes: ...


class CompletedFt8HttpTransport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout_s: float,
    ) -> CompletedFt8HttpResponse: ...


class _UrllibResponse:
    def __init__(self, status_code: int, body: bytes) -> None:
        self.status_code = status_code
        self.body = body


class UrllibCompletedFt8HttpTransport:
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


class HttpCompletedFt8IngestionClient:
    """Send immutable completed-FT8 events to the authenticated Forge API."""

    def __init__(
        self,
        base_url: str,
        *,
        bearer_token: str,
        timeout_s: float = 5.0,
        transport: CompletedFt8HttpTransport | None = None,
    ) -> None:
        parsed = urlparse(base_url.rstrip("/"))
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("completed-FT8 ingestion base URL must be absolute HTTP(S)")
        if parsed.query or parsed.fragment:
            raise ValueError(
                "completed-FT8 ingestion base URL must not include query or fragment"
            )
        if len(bearer_token) < 32 or any(
            character.isspace() for character in bearer_token
        ):
            raise ValueError(
                "completed-FT8 ingestion bearer token must be at least 32 characters "
                "with no whitespace"
            )
        if timeout_s <= 0:
            raise ValueError("completed-FT8 ingestion timeout must be positive")
        self._base_url = base_url.rstrip("/")
        self._bearer_token = bearer_token
        self._timeout_s = timeout_s
        self._transport = transport or UrllibCompletedFt8HttpTransport()

    def enqueue(self, event: CompletedFt8QsoEvent) -> CompletedFt8IngestionResult:
        """Perform one bounded authenticated delivery; callers own durable retry."""
        contact_id = event.contact.contact_id
        body = dumps(event.model_dump(mode="json"), separators=(",", ":")).encode()
        try:
            response = self._transport.request(
                "POST",
                f"{self._base_url}/api/v1/completed-ft8-events",
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {self._bearer_token}",
                    "Content-Type": "application/json",
                    "Idempotency-Key": str(contact_id),
                },
                body=body,
                timeout_s=self._timeout_s,
            )
        except (TimeoutError, URLError, OSError) as error:
            raise CompletedFt8IngestionError(
                "completed-FT8 ingestion service could not be reached"
            ) from error
        if response.status_code not in {200, 202}:
            raise CompletedFt8IngestionError(
                f"completed-FT8 ingestion returned HTTP {response.status_code}"
            )
        try:
            payload = loads(response.body.decode("utf-8"))
            result = CompletedFt8IngestionResult.model_validate(payload)
        except (UnicodeDecodeError, JSONDecodeError, ValidationError) as error:
            raise CompletedFt8IngestionError(
                "completed-FT8 ingestion returned an invalid acknowledgement"
            ) from error
        if result.contact_id != contact_id:
            raise CompletedFt8IngestionError(
                "completed-FT8 ingestion acknowledged a different contact ID"
            )
        return result
