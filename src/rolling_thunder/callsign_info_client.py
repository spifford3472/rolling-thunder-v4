"""Typed Pi HTTP client for the Forge callsign-info service."""

from __future__ import annotations

from json import JSONDecodeError, loads
from urllib.error import URLError
from urllib.parse import urlencode, urlparse

from pydantic import ValidationError

from rolling_thunder.callsign_info import CallsignInfoFailure, CallsignInfoResponse
from rolling_thunder.http_home_platform import HttpTransport, UrllibHttpTransport


class CallsignInfoClientError(OSError):
    """Raised with a non-sensitive category when callsign info is unavailable."""

    def __init__(self, failure: CallsignInfoFailure) -> None:
        super().__init__(failure.value)
        self.failure = failure


class HttpCallsignInfoClient:
    """Synchronous client intended only for a background worker."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout_s: float = 5.0,
        max_response_bytes: int = 65_536,
        transport: HttpTransport | None = None,
    ) -> None:
        normalized = base_url.strip().rstrip("/")
        parsed = urlparse(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Callsign-info base URL must be absolute HTTP(S).")
        if timeout_s <= 0:
            raise ValueError("Callsign-info timeout must be positive.")
        if max_response_bytes < 1:
            raise ValueError("Callsign-info response bound must be positive.")
        self._base_url = normalized
        self._timeout_s = timeout_s
        self._max_response_bytes = max_response_bytes
        self._transport = transport or UrllibHttpTransport()

    def lookup(
        self,
        callsign: str,
        *,
        pota_latitude: float | None = None,
        pota_longitude: float | None = None,
    ) -> CallsignInfoResponse:
        normalized = callsign.strip().upper()
        if not normalized:
            raise ValueError("Callsign must not be blank.")

        query: dict[str, object] = {}
        if pota_latitude is not None and pota_longitude is not None:
            query = {
                "latitude": pota_latitude,
                "longitude": pota_longitude,
                "source": "pota",
            }
        suffix = f"?{urlencode(query)}" if query else ""
        try:
            response = self._transport.request(
                "GET",
                f"{self._base_url}/api/v1/contact-intelligence/{normalized}{suffix}",
                headers={"Accept": "application/json"},
                body=None,
                timeout_s=self._timeout_s,
            )
        except (TimeoutError, URLError, OSError) as error:
            raise CallsignInfoClientError(
                CallsignInfoFailure.FORGE_UNREACHABLE
            ) from error

        if response.status_code >= 500:
            raise CallsignInfoClientError(
                CallsignInfoFailure.FORGE_UNREACHABLE
            )
        if not 200 <= response.status_code < 300:
            raise CallsignInfoClientError(CallsignInfoFailure.SERVICE_UNAVAILABLE)
        if len(response.body) > self._max_response_bytes:
            raise CallsignInfoClientError(CallsignInfoFailure.SERVICE_UNAVAILABLE)

        try:
            raw = loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, JSONDecodeError) as error:
            raise CallsignInfoClientError(
                CallsignInfoFailure.SERVICE_UNAVAILABLE
            ) from error
        try:
            result = CallsignInfoResponse.model_validate(raw)
        except ValidationError as error:
            raise CallsignInfoClientError(
                CallsignInfoFailure.SERVICE_UNAVAILABLE
            ) from error
        if result.callsign.strip().upper() != normalized:
            raise CallsignInfoClientError(CallsignInfoFailure.SERVICE_UNAVAILABLE)
        return result
