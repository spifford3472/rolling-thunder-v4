"""HTTP transport implementation for the Home Station Platform boundary."""

import os
from collections.abc import Mapping
from datetime import UTC, datetime
from json import JSONDecodeError, dumps, loads
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from uuid import UUID

from pydantic import ValidationError

from rolling_thunder.ft8.hardware_transmit import FT8TransmitPeriodTelemetry
from rolling_thunder.ft8.performance import (
    FT8PerformanceAttempt,
    FT8PerformanceUploadResult,
)
from rolling_thunder.home_platform import (
    ContactUploadRequest,
    ContactUploadResult,
    HomePlatformAvailability,
    HomePlatformClient,
    HomePlatformConnectionError,
    HomePlatformState,
    HomePlatformUploadError,
)

_JSON_CONTENT_TYPE = "application/json"


class HttpResponse(Protocol):
    """Minimal HTTP response boundary consumed by the platform client."""

    @property
    def status_code(self) -> int:
        """Return the numeric HTTP response status."""
        ...

    @property
    def body(self) -> bytes:
        """Return the complete response body."""
        ...


class HttpTransport(Protocol):
    """Injectable synchronous HTTP request boundary."""

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout_s: float,
    ) -> HttpResponse:
        """Perform one request or raise a transport-specific exception."""
        ...


class UrllibHttpResponse:
    """Immutable response returned by the standard-library transport."""

    def __init__(self, status_code: int, body: bytes) -> None:
        self._status_code = status_code
        self._body = body

    @property
    def status_code(self) -> int:
        return self._status_code

    @property
    def body(self) -> bytes:
        return self._body


class UrllibHttpTransport:
    """Production synchronous HTTP transport implemented with urllib."""

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout_s: float,
    ) -> UrllibHttpResponse:
        request = Request(
            url=url,
            data=body,
            headers=dict(headers),
            method=method,
        )
        try:
            with urlopen(request, timeout=timeout_s) as response:
                return UrllibHttpResponse(response.status, response.read())
        except HTTPError as error:
            return UrllibHttpResponse(error.code, error.read())


class HttpHomePlatformClient(HomePlatformClient):
    """Typed HTTP client for health checks and idempotent contact uploads."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout_s: float = 5.0,
        transport: HttpTransport | None = None,
    ) -> None:
        self._base_url = self._validate_base_url(base_url)
        if timeout_s <= 0:
            raise ValueError("Home platform HTTP timeout must be positive.")
        self._timeout_s = timeout_s
        self._transport = transport or UrllibHttpTransport()
        self._state = HomePlatformState(
            availability=HomePlatformAvailability.UNKNOWN,
            checked_at=datetime.now(UTC),
        )

    def get_state(self) -> HomePlatformState:
        """Return the latest immutable platform state without performing I/O."""
        return self._state

    def check_health(self) -> HomePlatformState:
        """Fetch and validate the remote health snapshot."""
        response = self._request(
            "GET",
            "/health",
            headers={"Accept": _JSON_CONTENT_TYPE},
            body=None,
            operation="health check",
        )
        if not 200 <= response.status_code < 300:
            raise HomePlatformConnectionError(
                f"Home Station Platform health check returned HTTP "
                f"{response.status_code}."
            )

        response_payload = self._decode_json(response.body, operation="health check")
        try:
            state = HomePlatformState.model_validate(response_payload)
        except ValidationError as error:
            raise HomePlatformConnectionError(
                "Home Station Platform health response did not match the expected schema."
            ) from error

        self._state = state
        return state

    def upload_contact(self, request: ContactUploadRequest) -> ContactUploadResult:
        """Upload one contact with UUID-based idempotency and validate the result."""
        request_payload = request.contact.model_dump(mode="json")
        response = self._request(
            "POST",
            "/contacts",
            headers={
                "Accept": _JSON_CONTENT_TYPE,
                "Content-Type": _JSON_CONTENT_TYPE,
                "Idempotency-Key": str(request.idempotency_key),
            },
            body=dumps(request_payload, separators=(",", ":")).encode("utf-8"),
            operation="contact upload",
        )
        if not 200 <= response.status_code < 300:
            raise HomePlatformUploadError(
                f"Home Station Platform contact upload returned HTTP "
                f"{response.status_code}."
            )

        response_payload = self._decode_json(response.body, operation="contact upload")
        try:
            result = ContactUploadResult.model_validate(response_payload)
        except ValidationError as error:
            raise HomePlatformUploadError(
                "Home Station Platform upload response did not match the expected schema."
            ) from error

        if result.contact_id != request.contact.contact_id:
            raise HomePlatformUploadError(
                "Home Station Platform upload response returned a different contact ID."
            )
        return result

    def upload_ft8_period(
        self, qso_id: UUID, emission_index: int, record: FT8TransmitPeriodTelemetry
    ) -> None:
        """Send one immutable FT8 emission through the private Forge upload path."""
        from dataclasses import asdict

        obj = asdict(record)
        if record.transmit_audio_offset_hz is None:
            obj.pop("transmit_audio_offset_hz")
        obj["qso_id"] = str(record.qso_id)
        obj["started_at_utc"] = record.started_at_utc.isoformat()
        obj["ended_at_utc"] = record.ended_at_utc.isoformat()
        token = os.environ.get("ROLLING_THUNDER_FT8_PERIOD_TOKEN")
        if not token:
            raise HomePlatformUploadError("FT8 period upload not configured")
        response = self._request(
            "POST", "/ft8-period",
            headers={
                "Accept": _JSON_CONTENT_TYPE, "Content-Type": _JSON_CONTENT_TYPE,
                "Idempotency-Key": f"{qso_id}:{emission_index}",
                "Authorization": f"Bearer {token}",
            },
            body=dumps({"qso_id": str(qso_id), "emission_index": emission_index, "record": obj},
                       separators=(",", ":")).encode("utf-8"),
            operation="FT8 transmission period upload",
        )
        if response.status_code != 200:
            raise HomePlatformUploadError(
                f"FT8 emission upload returned HTTP {response.status_code}"
            )
        payload = self._decode_json(response.body, operation="FT8 period upload")
        if not isinstance(payload, dict) or payload.get("status") not in {
            "accepted", "already_exists"
        }:
            raise HomePlatformUploadError("FT8 emission upload acknowledgement invalid")

    def upload_ft8_performance(
        self,
        attempt: FT8PerformanceAttempt,
    ) -> FT8PerformanceUploadResult:
        """Upload one FT8 performance attempt idempotently to Forge."""
        response = self._request(
            "POST",
            "/ft8-performance",
            headers={
                "Accept": _JSON_CONTENT_TYPE,
                "Content-Type": _JSON_CONTENT_TYPE,
                "Idempotency-Key": str(attempt.attempt_id),
            },
            body=dumps(
                attempt.model_dump(mode="json"),
                separators=(",", ":"),
            ).encode("utf-8"),
            operation="FT8 performance upload",
        )
        if not 200 <= response.status_code < 300:
            raise HomePlatformUploadError(
                "Home Station Platform FT8 performance upload returned HTTP "
                f"{response.status_code}."
            )

        response_payload = self._decode_json(
            response.body,
            operation="FT8 performance upload",
        )
        try:
            result = FT8PerformanceUploadResult.model_validate(response_payload)
        except ValidationError as error:
            raise HomePlatformUploadError(
                "Home Station Platform FT8 performance response did not match "
                "the expected schema."
            ) from error
        if result.attempt_id != attempt.attempt_id:
            raise HomePlatformUploadError(
                "Home Station Platform FT8 performance response returned "
                "a different attempt ID."
            )
        return result

    def _request(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None,
        operation: str,
    ) -> HttpResponse:
        try:
            return self._transport.request(
                method,
                f"{self._base_url}{path}",
                headers=headers,
                body=body,
                timeout_s=self._timeout_s,
            )
        except (TimeoutError, URLError, OSError) as error:
            raise HomePlatformConnectionError(
                f"Home Station Platform {operation} could not reach the remote service: "
                f"{error}"
            ) from error

    @staticmethod
    def _decode_json(body: bytes, *, operation: str) -> object:
        try:
            return loads(body.decode("utf-8"))
        except (UnicodeDecodeError, JSONDecodeError) as error:
            error_type = (
                HomePlatformConnectionError
                if operation == "health check"
                else HomePlatformUploadError
            )
            raise error_type(
                f"Home Station Platform {operation} returned invalid JSON."
            ) from error

    @staticmethod
    def _validate_base_url(base_url: str) -> str:
        normalized = base_url.strip().rstrip("/")
        parsed = urlparse(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(
                "Home platform base URL must be an absolute http or https URL."
            )
        if parsed.params or parsed.query or parsed.fragment:
            raise ValueError(
                "Home platform base URL must not contain parameters, a query, or a fragment."
            )
        return normalized
