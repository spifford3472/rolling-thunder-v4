"""Typed Raspberry Pi client for complete Forge shared-spot snapshots."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from json import JSONDecodeError, loads
from typing import Annotated, Literal
from urllib.error import URLError
from urllib.parse import urlparse

from pydantic import Field, ValidationError, field_validator, model_validator

from rolling_thunder.domain import DomainModel, Frequency, RadioMode
from rolling_thunder.http_home_platform import (
    HttpResponse,
    HttpTransport,
    UrllibHttpTransport,
)
from rolling_thunder.spot_domain import (
    DxSpotIdentity,
    PotaSpotIdentity,
    PotaSpotMetadata,
    SpotProvider,
    SpotRecord,
    SpotSnapshot,
    SpotSourceMetadataItem,
)
from rolling_thunder.value_types import Callsign, MaidenheadGrid, PotaReference

_JSON_ACCEPT = "application/json"
_USER_AGENT = "RollingThunder-v4.1"
_MAX_ERROR_LENGTH = 500
_MAX_FREQUENCY_HZ = 300_000_000_000


class ForgeClientError(Exception):
    """Base exception for Pi-side Forge client failures."""


class ForgeClientConnectionError(ForgeClientError):
    """Raised when the configured Forge service cannot be reached."""


class ForgeClientResponseError(ForgeClientError):
    """Raised when Forge returns an unusable HTTP or JSON response."""


class ForgeClientValidationError(ForgeClientError):
    """Raised when a Forge response violates the shared snapshot contract."""


class ForgeRemoteProviderStatus(StrEnum):
    """Provider-health states serialized by Forge API version 1."""

    STARTING = "starting"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class ForgeRemoteProviderHealth(DomainModel):
    """Validated upstream provider health retained with one Pi snapshot."""

    provider: SpotProvider
    status: ForgeRemoteProviderStatus
    active_spot_count: int = Field(ge=0, strict=True)
    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error: str | None = Field(default=None, max_length=_MAX_ERROR_LENGTH)

    @field_validator("last_attempt_at", "last_success_at")
    @classmethod
    def normalize_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("provider timestamps must include timezone information")
        return value.astimezone(UTC)

    @field_validator("last_error")
    @classmethod
    def normalize_error(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def validate_status_consistency(self) -> ForgeRemoteProviderHealth:
        if self.status is ForgeRemoteProviderStatus.STARTING:
            if self.last_attempt_at is not None or self.last_error is not None:
                raise ValueError("starting provider health cannot contain attempt data")
        elif self.status is ForgeRemoteProviderStatus.HEALTHY:
            if self.last_attempt_at is None or self.last_success_at is None:
                raise ValueError("healthy provider health requires attempt and success timestamps")
            if self.last_error is not None:
                raise ValueError("healthy provider health cannot contain an error")
        elif self.status is ForgeRemoteProviderStatus.DEGRADED:
            if self.last_success_at is None or self.last_error is None:
                raise ValueError("degraded provider health requires retained success and an error")
        elif self.last_attempt_at is None or self.last_error is None:
            raise ValueError("unavailable provider health requires attempt data and an error")
        return self


class _ForgeWirePotaIdentity(DomainModel):
    provider: Literal["pota"]
    park_reference: PotaReference
    frequency: int = Field(gt=0, le=_MAX_FREQUENCY_HZ, strict=True)


class _ForgeWireDxIdentity(DomainModel):
    provider: Literal["dx"]
    callsign: Callsign
    frequency: int = Field(gt=0, le=_MAX_FREQUENCY_HZ, strict=True)


SpotWireIdentity = Annotated[
    _ForgeWirePotaIdentity | _ForgeWireDxIdentity,
    Field(discriminator="provider"),
]


class _ForgeWireSpotRecord(DomainModel):
    """Wire DTO matching Forge's integer-hertz JSON representation."""

    identity: SpotWireIdentity
    callsign: Callsign
    operator_name: str | None = Field(default=None, max_length=200)
    grid: MaidenheadGrid | None = None
    frequency: int = Field(gt=0, le=_MAX_FREQUENCY_HZ, strict=True)
    mode: RadioMode
    display_mode: str = Field(min_length=1, max_length=40)
    spotted_at: datetime
    source_metadata: tuple[SpotSourceMetadataItem, ...] = ()
    pota: PotaSpotMetadata | None = None

    def to_domain(self) -> SpotRecord:
        """Rebuild the canonical shared domain record with full validation."""
        frequency = Frequency(hz=self.frequency)
        if isinstance(self.identity, _ForgeWirePotaIdentity):
            identity = PotaSpotIdentity(
                park_reference=self.identity.park_reference,
                frequency=Frequency(hz=self.identity.frequency),
            )
        else:
            identity = DxSpotIdentity(
                callsign=self.identity.callsign,
                frequency=Frequency(hz=self.identity.frequency),
            )
        return SpotRecord(
            identity=identity,
            callsign=self.callsign,
            operator_name=self.operator_name,
            grid=self.grid,
            frequency=frequency,
            mode=self.mode,
            display_mode=self.display_mode,
            spotted_at=self.spotted_at,
            source_metadata=self.source_metadata,
            pota=self.pota,
        )


class _ForgeWireSpotsResponse(DomainModel):
    """Strict version-1 Forge spots response before publication on the Pi."""

    api_schema_version: Literal["1"]
    snapshot_revision: int = Field(ge=0, strict=True)
    generated_at: datetime
    spots: tuple[_ForgeWireSpotRecord, ...] = ()
    providers: tuple[ForgeRemoteProviderHealth, ...] = Field(min_length=1)

    @field_validator("generated_at")
    @classmethod
    def normalize_generated_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("generated_at must include timezone information")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_complete_contract(self) -> _ForgeWireSpotsResponse:
        provider_ids = tuple(item.provider for item in self.providers)
        expected_provider_ids = tuple(sorted(provider_ids, key=lambda item: item.value))
        if provider_ids != expected_provider_ids:
            raise ValueError("providers must be in deterministic provider order")
        if len(provider_ids) != len(set(provider_ids)):
            raise ValueError("providers must not contain duplicate provider families")

        domain_spots = tuple(item.to_domain() for item in self.spots)
        snapshot = SpotSnapshot(generated_at=self.generated_at, spots=domain_spots)
        represented = {spot.provider for spot in snapshot.spots}
        if not represented.issubset(set(provider_ids)):
            raise ValueError("spot provider is missing corresponding provider health")

        counts = {
            provider: sum(spot.provider is provider for spot in snapshot.spots)
            for provider in provider_ids
        }
        for health in self.providers:
            if health.active_spot_count != counts[health.provider]:
                raise ValueError("provider active spot count does not match snapshot")
        return self

    def to_result(self, *, received_at: datetime) -> ForgeSpotClientResult:
        snapshot = SpotSnapshot(
            generated_at=self.generated_at,
            spots=tuple(item.to_domain() for item in self.spots),
        )
        return ForgeSpotClientResult(
            snapshot_revision=self.snapshot_revision,
            snapshot=snapshot,
            providers=self.providers,
            received_at=received_at,
        )


class ForgeSpotClientResult(DomainModel):
    """One complete validated Forge snapshot received by the Pi."""

    snapshot_revision: int = Field(ge=0, strict=True)
    snapshot: SpotSnapshot
    providers: tuple[ForgeRemoteProviderHealth, ...]
    received_at: datetime

    @field_validator("received_at")
    @classmethod
    def normalize_received_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("received_at must include timezone information")
        return value.astimezone(UTC)


class HttpForgeSpotClient:
    """Synchronous Forge client intended only for background-worker use."""

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
            raise ValueError("Forge HTTP timeout must be positive.")
        if max_response_bytes <= 0:
            raise ValueError("Forge maximum response bytes must be positive.")
        self._timeout_s = timeout_s
        self._max_response_bytes = max_response_bytes
        self._transport = transport or UrllibHttpTransport()
        self._clock = clock or (lambda: datetime.now(UTC))

    def fetch_spots(self) -> ForgeSpotClientResult:
        """Fetch and validate one complete versioned Forge spot snapshot."""
        response = self._request_spots()
        if len(response.body) > self._max_response_bytes:
            raise ForgeClientResponseError(
                "Forge spots response exceeded the configured byte limit."
            )

        try:
            payload = loads(response.body)
        except (JSONDecodeError, UnicodeDecodeError) as error:
            raise ForgeClientResponseError(
                "Forge spots response was not valid UTF-8 JSON."
            ) from error
        if not isinstance(payload, dict):
            raise ForgeClientResponseError(
                "Forge spots response JSON must contain an object at the document root."
            )

        try:
            wire = _ForgeWireSpotsResponse.model_validate(payload)
        except ValidationError as error:
            raise ForgeClientValidationError(self._validation_message(error)) from error

        received_at = self._clock()
        if received_at.tzinfo is None or received_at.utcoffset() is None:
            raise ValueError("Forge client clock must return an aware datetime.")
        return wire.to_result(received_at=received_at.astimezone(UTC))

    def _request_spots(self) -> HttpResponse:
        url = f"{self._api_url}/api/v1/spots"
        try:
            response = self._transport.request(
                "GET",
                url,
                headers={"Accept": _JSON_ACCEPT, "User-Agent": _USER_AGENT},
                body=None,
                timeout_s=self._timeout_s,
            )
        except (TimeoutError, URLError, OSError) as error:
            raise ForgeClientConnectionError(
                "Forge spots request could not be completed."
            ) from error

        if not 200 <= response.status_code < 300:
            raise ForgeClientConnectionError(
                f"Forge spots request returned HTTP {response.status_code}."
            )
        return response

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
    def _validation_message(error: ValidationError) -> str:
        details: list[str] = []
        for item in error.errors(include_url=False):
            location = ".".join(str(part) for part in item["loc"]) or "<response>"
            details.append(f"{location}: {item['msg']}")
        text = "; ".join(details) or "Forge response validation failed"
        return text[:_MAX_ERROR_LENGTH]
