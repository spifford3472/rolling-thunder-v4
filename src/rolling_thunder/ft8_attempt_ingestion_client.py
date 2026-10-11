"""Bounded authenticated client for the Forge FT8-attempt inbox."""

from __future__ import annotations

from collections.abc import Mapping
from json import JSONDecodeError, loads
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from uuid import UUID

from rolling_thunder.ft8.attempt_ledger import FT8AttemptEvent


class AttemptHttpResponse(Protocol):
    status_code: int
    body: bytes


class AttemptHttpTransport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout_s: float,
    ) -> AttemptHttpResponse: ...


class _Response:
    def __init__(self, status_code: int, body: bytes) -> None:
        self.status_code = status_code
        self.body = body


class UrllibAttemptHttpTransport:
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout_s: float,
    ) -> _Response:
        request = Request(url, data=body, headers=dict(headers), method=method)
        try:
            with urlopen(request, timeout=timeout_s) as response:
                return _Response(response.status, response.read())
        except HTTPError as error:
            return _Response(error.code, error.read())


class HttpFT8AttemptIngestionClient:
    def __init__(
        self,
        base_url: str,
        *,
        bearer_token: str,
        timeout_s: float = 5.0,
        transport: AttemptHttpTransport | None = None,
    ) -> None:
        parsed = urlparse(base_url.rstrip("/"))
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("attempt ingestion base URL must be absolute HTTP(S)")
        if parsed.query or parsed.fragment:
            raise ValueError("attempt ingestion base URL must not include query or fragment")
        if len(bearer_token) < 32 or any(char.isspace() for char in bearer_token):
            raise ValueError("attempt ingestion bearer token is invalid")
        if timeout_s <= 0:
            raise ValueError("attempt ingestion timeout must be positive")
        self._base_url = base_url.rstrip("/")
        self._token = bearer_token
        self._timeout_s = timeout_s
        self._transport = transport or UrllibAttemptHttpTransport()

    def deliver(self, event: FT8AttemptEvent) -> UUID:
        try:
            response = self._transport.request(
                "POST",
                f"{self._base_url}/api/v1/ft8-attempts",
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {self._token}",
                    "Content-Type": "application/json",
                    "Idempotency-Key": str(event.attempt_uuid),
                },
                body=event.model_dump_json().encode(),
                timeout_s=self._timeout_s,
            )
        except (OSError, TimeoutError, URLError) as error:
            raise RuntimeError("attempt ingestion service could not be reached") from error
        if response.status_code not in {200, 202}:
            raise RuntimeError(f"attempt ingestion returned HTTP {response.status_code}")
        try:
            payload = loads(response.body)
            acknowledged = UUID(str(payload["attempt_uuid"]))
        except (JSONDecodeError, KeyError, TypeError, ValueError) as error:
            raise RuntimeError("attempt ingestion returned an invalid acknowledgement") from error
        if acknowledged != event.attempt_uuid:
            raise RuntimeError("attempt ingestion acknowledged a different UUID")
        return acknowledged
