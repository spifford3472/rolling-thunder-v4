"""Typed Pi-side HTTP client for publishing mobile GPS locations to Forge."""

from __future__ import annotations

from json import JSONDecodeError, dumps, loads
from typing import Literal
from urllib.error import URLError
from urllib.parse import urlparse

from pydantic import Field, ValidationError

from rolling_thunder.domain import DomainModel
from rolling_thunder.forge_mobile_location import MobileLocationRecord
from rolling_thunder.http_home_platform import HttpTransport, UrllibHttpTransport

_JSON_CONTENT_TYPE = "application/json"
_USER_AGENT = "RollingThunder-v4.1"
_MAX_RESPONSE_BYTES = 4_096
_MAX_ERROR_LENGTH = 500


class ForgeLocationClientError(Exception):
    """Base exception for Pi-side Forge location publication failures."""


class ForgeLocationConnectionError(ForgeLocationClientError):
    """Raised when the Forge location endpoint cannot be reached."""


class ForgeLocationResponseError(ForgeLocationClientError):
    """Raised when Forge returns an unusable response."""


class ForgeLocationStaleError(ForgeLocationClientError):
    """Raised when Forge rejects a location because it is not newer."""


class ForgeLocationPublishReceipt(DomainModel):
    """Validated acknowledgement for one durably retained location."""

    api_schema_version: Literal["1"]
    revision: int = Field(ge=1, strict=True)
    location: MobileLocationRecord


class HttpForgeLocationClient:
    """Synchronous location publisher intended only for background-worker use."""

    def __init__(
        self,
        api_url: str,
        *,
        timeout_s: float = 5.0,
        transport: HttpTransport | None = None,
    ) -> None:
        self._api_url = self._validate_api_url(api_url)
        if timeout_s <= 0:
            raise ValueError("Forge location HTTP timeout must be positive.")
        self._timeout_s = timeout_s
        self._transport = transport or UrllibHttpTransport()

    def publish(self, location: MobileLocationRecord) -> ForgeLocationPublishReceipt:
        """Publish one validated mobile location and validate Forge's acknowledgement."""
        payload = {
            "api_schema_version": "1",
            "location": location.model_dump(mode="json"),
        }
        body = dumps(payload, separators=(",", ":")).encode("utf-8")
        if len(body) > _MAX_RESPONSE_BYTES:
            raise ValueError("Forge mobile-location request exceeded 4096 bytes.")

        try:
            response = self._transport.request(
                "PUT",
                f"{self._api_url}/api/v1/mobile-location",
                headers={
                    "Accept": _JSON_CONTENT_TYPE,
                    "Content-Type": _JSON_CONTENT_TYPE,
                    "User-Agent": _USER_AGENT,
                },
                body=body,
                timeout_s=self._timeout_s,
            )
        except (TimeoutError, URLError, OSError) as error:
            raise ForgeLocationConnectionError(
                "Forge mobile-location request could not be completed."
            ) from error

        if len(response.body) > _MAX_RESPONSE_BYTES:
            raise ForgeLocationResponseError(
                "Forge mobile-location response exceeded 4096 bytes."
            )

        if response.status_code == 409:
            raise ForgeLocationStaleError(self._error_message(response.body, 409))
        if not 200 <= response.status_code < 300:
            raise ForgeLocationResponseError(
                self._error_message(response.body, response.status_code)
            )

        try:
            raw = loads(response.body)
        except (JSONDecodeError, UnicodeDecodeError) as error:
            raise ForgeLocationResponseError(
                "Forge mobile-location response was not valid UTF-8 JSON."
            ) from error
        if not isinstance(raw, dict):
            raise ForgeLocationResponseError(
                "Forge mobile-location response JSON must contain an object."
            )

        try:
            receipt = ForgeLocationPublishReceipt.model_validate(raw)
        except ValidationError as error:
            details = "; ".join(
                f"{'.'.join(str(part) for part in item['loc']) or '<response>'}: "
                f"{item['msg']}"
                for item in error.errors(include_url=False)
            )
            raise ForgeLocationResponseError(
                (details or "Forge mobile-location response validation failed")[
                    :_MAX_ERROR_LENGTH
                ]
            ) from error

        if receipt.location != location:
            raise ForgeLocationResponseError(
                "Forge mobile-location acknowledgement did not match the submitted location."
            )
        return receipt

    @staticmethod
    def _validate_api_url(value: str) -> str:
        normalized = value.strip().rstrip("/")
        parsed = urlparse(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Forge API URL must be an absolute HTTP or HTTPS URL.")
        if parsed.query or parsed.fragment:
            raise ValueError("Forge API URL must not contain a query string or fragment.")
        return normalized

    @staticmethod
    def _error_message(body: bytes, status_code: int) -> str:
        fallback = f"Forge mobile-location request returned HTTP {status_code}."
        try:
            raw = loads(body)
        except (JSONDecodeError, UnicodeDecodeError):
            return fallback
        if not isinstance(raw, dict):
            return fallback
        message = raw.get("message")
        if not isinstance(message, str) or not message.strip():
            return fallback
        return message.strip()[:_MAX_ERROR_LENGTH]
