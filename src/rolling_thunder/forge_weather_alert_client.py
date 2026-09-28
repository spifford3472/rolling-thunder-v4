"""Typed Pi client for retained Forge location-aware weather alerts."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from json import JSONDecodeError, loads
from typing import Literal
from urllib.error import URLError
from urllib.parse import urlparse

from pydantic import Field, ValidationError, field_validator, model_validator

from rolling_thunder.domain import DomainModel
from rolling_thunder.forge_weather_alerts import (
    WeatherAlertApplicability,
    WeatherAlertProviderStatus,
    WeatherAlertSnapshot,
)
from rolling_thunder.http_home_platform import (
    HttpResponse,
    HttpTransport,
    UrllibHttpTransport,
)

_JSON_ACCEPT = "application/json"
_USER_AGENT = "RollingThunder-v4.1"
_MAX_ERROR_LENGTH = 500


class ForgeWeatherAlertClientError(Exception):
    """Base Pi-side Forge weather-alert client failure."""


class ForgeWeatherAlertClientTransportError(
    ForgeWeatherAlertClientError
):
    """Raised when the private Forge alert endpoint cannot be reached."""


class ForgeWeatherAlertClientValidationError(
    ForgeWeatherAlertClientError
):
    """Raised when Forge violates the versioned alert response contract."""


class ForgeRemoteWeatherAlertHealth(DomainModel):
    """Validated Forge alert health accompanying one response."""

    status: WeatherAlertProviderStatus
    applicability: WeatherAlertApplicability
    revision: int = Field(ge=0, strict=True)
    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error: str | None = Field(
        default=None,
        max_length=_MAX_ERROR_LENGTH,
    )
    startup_storage_error: str | None = Field(
        default=None,
        max_length=_MAX_ERROR_LENGTH,
    )
    persistence_error: str | None = Field(
        default=None,
        max_length=_MAX_ERROR_LENGTH,
    )

    @field_validator("last_attempt_at", "last_success_at")
    @classmethod
    def normalize_timestamp(
        cls,
        value: datetime | None,
    ) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(
                "Forge weather-alert health timestamps must "
                "include timezone information"
            )
        return value.astimezone(UTC)

    @field_validator(
        "last_error",
        "startup_storage_error",
        "persistence_error",
    )
    @classmethod
    def normalize_error(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized[:_MAX_ERROR_LENGTH] or None


class ForgeWeatherAlertClientResult(DomainModel):
    """One complete validated Forge alert response received by the Pi."""

    revision: int = Field(ge=0, strict=True)
    snapshot: WeatherAlertSnapshot | None = None
    health: ForgeRemoteWeatherAlertHealth
    received_at: datetime

    @field_validator("received_at")
    @classmethod
    def normalize_received_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(
                "weather-alert received_at must include timezone information"
            )
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_result(self) -> ForgeWeatherAlertClientResult:
        if self.health.revision != self.revision:
            raise ValueError(
                "weather-alert health revision must match response revision"
            )
        if self.revision == 0 and self.snapshot is not None:
            raise ValueError(
                "weather-alert revision 0 cannot contain a snapshot"
            )
        if self.revision > 0 and self.snapshot is None:
            raise ValueError(
                "positive weather-alert revision requires a snapshot"
            )
        if (
            self.health.applicability
            is WeatherAlertApplicability.VERIFIED_CURRENT
            and self.snapshot is None
        ):
            raise ValueError(
                "verified-current alert applicability requires a snapshot"
            )
        return self


class _ForgeWireWeatherAlertResponse(DomainModel):
    """Strict version-1 Forge alert response before Pi publication."""

    api_schema_version: Literal["1"]
    revision: int = Field(ge=0, strict=True)
    snapshot: WeatherAlertSnapshot | None = None
    health: ForgeRemoteWeatherAlertHealth

    @model_validator(mode="after")
    def validate_wire(self) -> _ForgeWireWeatherAlertResponse:
        if self.health.revision != self.revision:
            raise ValueError(
                "weather-alert health revision must match response revision"
            )
        if self.revision == 0 and self.snapshot is not None:
            raise ValueError(
                "weather-alert revision 0 cannot contain a snapshot"
            )
        if self.revision > 0 and self.snapshot is None:
            raise ValueError(
                "positive weather-alert revision requires a snapshot"
            )
        if (
            self.health.applicability
            is WeatherAlertApplicability.VERIFIED_CURRENT
            and self.snapshot is None
        ):
            raise ValueError(
                "verified-current alert applicability requires a snapshot"
            )
        return self

    def to_result(
        self,
        *,
        received_at: datetime,
    ) -> ForgeWeatherAlertClientResult:
        return ForgeWeatherAlertClientResult(
            revision=self.revision,
            snapshot=self.snapshot,
            health=self.health,
            received_at=received_at,
        )


class HttpForgeWeatherAlertClient:
    """Synchronous Forge alert client for background-worker use only."""

    def __init__(
        self,
        api_url: str,
        *,
        timeout_s: float = 5.0,
        max_response_bytes: int = 1_048_576,
        transport: HttpTransport | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._api_url = self._validate_api_url(api_url)

        if timeout_s <= 0:
            raise ValueError(
                "Forge weather-alert HTTP timeout must be positive."
            )
        if max_response_bytes <= 0:
            raise ValueError(
                "Forge weather-alert maximum response bytes must be positive."
            )

        self._timeout_s = timeout_s
        self._max_response_bytes = max_response_bytes
        self._transport = transport or UrllibHttpTransport()
        self._clock = clock or (lambda: datetime.now(UTC))

    def fetch_alerts(self) -> ForgeWeatherAlertClientResult:
        """Fetch one complete versioned Forge weather-alert response."""
        response = self._request()

        if len(response.body) > self._max_response_bytes:
            raise ForgeWeatherAlertClientValidationError(
                "Forge weather-alert response exceeded the configured "
                "byte limit."
            )

        try:
            payload = loads(response.body)
        except (JSONDecodeError, UnicodeDecodeError) as error:
            raise ForgeWeatherAlertClientValidationError(
                "Forge weather-alert response was not valid UTF-8 JSON."
            ) from error

        if not isinstance(payload, dict):
            raise ForgeWeatherAlertClientValidationError(
                "Forge weather-alert response JSON must contain an object."
            )

        try:
            wire = _ForgeWireWeatherAlertResponse.model_validate(payload)
        except ValidationError as error:
            raise ForgeWeatherAlertClientValidationError(
                self._validation_message(error)
            ) from error

        received_at = self._clock()
        if (
            received_at.tzinfo is None
            or received_at.utcoffset() is None
        ):
            raise ValueError(
                "Forge weather-alert client clock must return "
                "an aware datetime."
            )

        return wire.to_result(
            received_at=received_at.astimezone(UTC)
        )

    def _request(self) -> HttpResponse:
        url = f"{self._api_url}/api/v1/weather-alerts"

        try:
            response = self._transport.request(
                "GET",
                url,
                headers={
                    "Accept": _JSON_ACCEPT,
                    "User-Agent": _USER_AGENT,
                },
                body=None,
                timeout_s=self._timeout_s,
            )
        except (TimeoutError, URLError, OSError) as error:
            raise ForgeWeatherAlertClientTransportError(
                "Forge weather-alert request could not be completed."
            ) from error

        if not 200 <= response.status_code < 300:
            raise ForgeWeatherAlertClientTransportError(
                "Forge weather-alert request returned "
                f"HTTP {response.status_code}."
            )

        return response

    @staticmethod
    def _validate_api_url(value: str) -> str:
        normalized = value.strip().rstrip("/")
        parsed = urlparse(normalized)

        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
        ):
            raise ValueError(
                "Forge API URL must be an absolute HTTP or HTTPS URL."
            )

        if parsed.query or parsed.fragment:
            raise ValueError(
                "Forge API URL must not contain a query string or fragment."
            )

        return normalized

    @staticmethod
    def _validation_message(error: ValidationError) -> str:
        details: list[str] = []

        for item in error.errors(include_url=False):
            location = ".".join(
                str(part) for part in item["loc"]
            ) or "<response>"
            details.append(
                f"{location}: {item['msg']}"
            )

        text = (
            "; ".join(details)
            or "Forge weather-alert response validation failed"
        )
        return text[:_MAX_ERROR_LENGTH]
