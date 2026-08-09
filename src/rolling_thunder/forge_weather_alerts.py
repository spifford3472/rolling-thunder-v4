"""Provider-neutral retained severe-weather alert domain for Forge."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from threading import RLock
from typing import Final, Protocol

from pydantic import Field, field_validator, model_validator

from rolling_thunder.domain import DomainModel
from rolling_thunder.forge_mobile_location import (
    ForgeMobileLocationService,
    MobileLocationRecord,
)

_MAX_ERROR_LENGTH: Final = 500
Clock = Callable[[], datetime]


class ForgeWeatherAlertProviderError(Exception):
    """Raised when the configured alert provider cannot return a valid set."""


class ForgeWeatherAlertStorageError(Exception):
    """Raised when retained Forge alert persistence cannot be used safely."""


class WeatherAlertSeverity(StrEnum):
    """Provider-neutral CAP severity semantics used by Rolling Thunder."""

    EXTREME = "extreme"
    SEVERE = "severe"
    MODERATE = "moderate"
    MINOR = "minor"
    UNKNOWN = "unknown"


class WeatherAlertUrgency(StrEnum):
    """Provider-neutral CAP urgency semantics used by Rolling Thunder."""

    IMMEDIATE = "immediate"
    EXPECTED = "expected"
    FUTURE = "future"
    PAST = "past"
    UNKNOWN = "unknown"


class WeatherAlertCertainty(StrEnum):
    """Provider-neutral CAP certainty semantics used by Rolling Thunder."""

    OBSERVED = "observed"
    LIKELY = "likely"
    POSSIBLE = "possible"
    UNLIKELY = "unlikely"
    UNKNOWN = "unknown"


class WeatherAlertProviderStatus(StrEnum):
    """Health of the Forge alert-provider refresh path."""

    STARTING = "starting"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class WeatherAlertApplicability(StrEnum):
    """Whether retained alert applicability is verified for the current vehicle point."""

    VERIFIED_CURRENT = "verified_current"
    RETAINED_UNVERIFIED = "retained_unverified"
    UNAVAILABLE = "unavailable"


class WeatherAlertSourceMetadata(DomainModel):
    """Provider attribution retained with each complete alert snapshot."""

    provider_id: str = Field(min_length=1, max_length=64)
    provider_name: str = Field(min_length=1, max_length=128)
    attribution_text: str = Field(min_length=1, max_length=256)
    attribution_url: str = Field(min_length=1, max_length=512)


class WeatherAlertRecord(DomainModel):
    """One provider-neutral active alert applicable to a queried point."""

    alert_id: str = Field(min_length=1, max_length=512)
    event: str = Field(min_length=1, max_length=160)
    severity: WeatherAlertSeverity
    urgency: WeatherAlertUrgency
    certainty: WeatherAlertCertainty
    headline: str = Field(min_length=1, max_length=512)
    area_description: str | None = Field(default=None, max_length=1_024)
    sent_at: datetime
    effective_at: datetime
    onset_at: datetime | None = None
    ends_at: datetime | None = None
    expires_at: datetime

    @field_validator(
        "sent_at",
        "effective_at",
        "onset_at",
        "ends_at",
        "expires_at",
    )
    @classmethod
    def normalize_timestamp(cls, value: datetime | None) -> datetime | None:
        """Require timezone-aware timestamps and normalize them to UTC."""
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("weather alert timestamps must include timezone information")
        return value.astimezone(UTC)

    @field_validator("alert_id", "event", "headline", "area_description")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        """Trim provider text while preserving optional absence."""
        if value is None:
            return None
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("weather alert text must not be blank")
        return normalized

    @model_validator(mode="after")
    def validate_lifecycle(self) -> WeatherAlertRecord:
        """Reject impossible alert lifecycle ordering."""
        if self.expires_at < self.effective_at:
            raise ValueError("expires_at must not be earlier than effective_at")
        if self.ends_at is not None and self.ends_at < self.effective_at:
            raise ValueError("ends_at must not be earlier than effective_at")
        return self


class WeatherAlertSnapshot(DomainModel):
    """Complete active-alert set returned for one exact trusted vehicle point."""

    latitude: float = Field(ge=-90.0, le=90.0, allow_inf_nan=False)
    longitude: float = Field(ge=-180.0, le=180.0, allow_inf_nan=False)
    fetched_at: datetime
    alerts: tuple[WeatherAlertRecord, ...] = ()
    source: WeatherAlertSourceMetadata

    @field_validator("fetched_at")
    @classmethod
    def normalize_fetched_at(cls, value: datetime) -> datetime:
        """Require a timezone-aware provider-fetch timestamp."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("fetched_at must include timezone information")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_unique_alert_ids(self) -> WeatherAlertSnapshot:
        """Reject ambiguous duplicate stable provider identifiers."""
        alert_ids = [alert.alert_id for alert in self.alerts]
        if len(alert_ids) != len(set(alert_ids)):
            raise ValueError("weather alert identifiers must be unique within a snapshot")
        return self


class ForgeWeatherAlertState(DomainModel):
    """Immutable retained Forge alert state with truthful applicability health."""

    revision: int = Field(ge=0)
    snapshot: WeatherAlertSnapshot | None = None
    provider_status: WeatherAlertProviderStatus = WeatherAlertProviderStatus.STARTING
    applicability: WeatherAlertApplicability = WeatherAlertApplicability.UNAVAILABLE
    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error: str | None = Field(default=None, max_length=_MAX_ERROR_LENGTH)
    startup_storage_error: str | None = Field(default=None, max_length=_MAX_ERROR_LENGTH)
    persistence_error: str | None = Field(default=None, max_length=_MAX_ERROR_LENGTH)

    @field_validator("last_attempt_at", "last_success_at")
    @classmethod
    def normalize_optional_timestamp(cls, value: datetime | None) -> datetime | None:
        """Normalize optional health timestamps to UTC."""
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("weather alert health timestamps must include timezone information")
        return value.astimezone(UTC)

    @field_validator("last_error", "startup_storage_error", "persistence_error")
    @classmethod
    def normalize_optional_error(cls, value: str | None) -> str | None:
        """Trim and bound optional diagnostic strings."""
        if value is None:
            return None
        normalized = value.strip()
        return normalized[:_MAX_ERROR_LENGTH] or None

    @model_validator(mode="after")
    def validate_retained_state(self) -> ForgeWeatherAlertState:
        """Keep revision, snapshot presence, and applicability consistent."""
        if self.revision == 0 and self.snapshot is not None:
            raise ValueError("revision 0 cannot contain a weather alert snapshot")
        if self.revision > 0 and self.snapshot is None:
            raise ValueError("positive alert revision requires a retained snapshot")
        if (
            self.applicability is WeatherAlertApplicability.VERIFIED_CURRENT
            and self.snapshot is None
        ):
            raise ValueError("verified_current applicability requires a snapshot")
        return self


class WeatherAlertProvider(Protocol):
    """Synchronous alert provider executed only by the Forge alert worker."""

    def fetch_alerts(self, location: MobileLocationRecord) -> WeatherAlertSnapshot:
        """Return the complete active alert set for one trusted point."""
        ...


class ForgeWeatherAlertRepository(Protocol):
    """Durable singleton alert-snapshot boundary consumed by the alert service."""

    def load(self) -> ForgeWeatherAlertState | None:
        """Load and revalidate the latest retained alert snapshot."""
        ...

    def replace(self, snapshot: WeatherAlertSnapshot) -> ForgeWeatherAlertState:
        """Transactionally replace the complete retained alert snapshot."""
        ...


class ForgeWeatherAlertService:
    """Refresh alerts only from a current trusted vehicle location."""

    def __init__(
        self,
        provider: WeatherAlertProvider,
        repository: ForgeWeatherAlertRepository,
        mobile_location: ForgeMobileLocationService,
        *,
        now: Clock | None = None,
        location_max_age_s: float = 120.0,
    ) -> None:
        if location_max_age_s <= 0:
            raise ValueError("Weather alert location maximum age must be positive.")
        self._provider = provider
        self._repository = repository
        self._mobile_location = mobile_location
        self._now = now or (lambda: datetime.now(UTC))
        self._location_max_age_s = location_max_age_s
        self._lock = RLock()

        startup_error: str | None
        try:
            stored = repository.load()
        except ForgeWeatherAlertStorageError as error:
            stored = None
            startup_error = self._bounded_error(error)
        else:
            startup_error = None

        if stored is None:
            self._state = ForgeWeatherAlertState(
                revision=0,
                provider_status=(
                    WeatherAlertProviderStatus.UNAVAILABLE
                    if startup_error is not None
                    else WeatherAlertProviderStatus.STARTING
                ),
                applicability=WeatherAlertApplicability.UNAVAILABLE,
                startup_storage_error=startup_error,
            )
        else:
            self._state = stored.model_copy(
                update={
                    "provider_status": WeatherAlertProviderStatus.STARTING,
                    "applicability": WeatherAlertApplicability.RETAINED_UNVERIFIED,
                    "startup_storage_error": startup_error,
                    "persistence_error": None,
                    "last_error": None,
                }
            )

    def get_state(self) -> ForgeWeatherAlertState:
        """Return already-published alert state without provider or storage I/O."""
        with self._lock:
            return self._state

    def refresh(self) -> ForgeWeatherAlertState:
        """Query active alerts for the latest trusted current mobile location."""
        now = self._aware_now()
        location = self._mobile_location.get_state().location
        with self._lock:
            previous = self._state

        if location is None:
            return self._publish_unverified(
                previous,
                "No retained mobile location is available for weather alerts.",
            )

        age = now - location.received_at
        if age < timedelta(0):
            return self._publish_unverified(
                previous,
                "Retained mobile location is future-dated relative to Forge UTC.",
            )
        if age > timedelta(seconds=self._location_max_age_s):
            return self._publish_unverified(
                previous,
                "Retained mobile location is too old to verify weather alert applicability.",
            )

        try:
            candidate = self._provider.fetch_alerts(location)
        except (ForgeWeatherAlertProviderError, ValueError) as error:
            return self._publish_failed_attempt(previous, now, error)

        if (
            abs(candidate.latitude - location.latitude) > 1e-4
            or abs(candidate.longitude - location.longitude) > 1e-4
        ):
            return self._publish_failed_attempt(
                previous,
                now,
                ForgeWeatherAlertProviderError(
                    "Weather alert provider returned a snapshot for a different point."
                ),
            )

        try:
            stored = self._repository.replace(candidate)
        except ForgeWeatherAlertStorageError as error:
            applicability = (
                WeatherAlertApplicability.RETAINED_UNVERIFIED
                if previous.snapshot is not None
                else WeatherAlertApplicability.UNAVAILABLE
            )
            status = (
                WeatherAlertProviderStatus.DEGRADED
                if previous.snapshot is not None
                else WeatherAlertProviderStatus.UNAVAILABLE
            )
            return self._publish_state(
                previous.model_copy(
                    update={
                        "provider_status": status,
                        "applicability": applicability,
                        "last_attempt_at": now,
                        "persistence_error": self._bounded_error(error),
                    }
                )
            )

        return self._publish_state(
            stored.model_copy(
                update={
                    "provider_status": WeatherAlertProviderStatus.HEALTHY,
                    "applicability": WeatherAlertApplicability.VERIFIED_CURRENT,
                    "last_attempt_at": now,
                    "last_success_at": now,
                    "last_error": None,
                    "startup_storage_error": None,
                    "persistence_error": None,
                }
            )
        )

    def _publish_unverified(
        self,
        previous: ForgeWeatherAlertState,
        message: str,
    ) -> ForgeWeatherAlertState:
        applicability = (
            WeatherAlertApplicability.RETAINED_UNVERIFIED
            if previous.snapshot is not None
            else WeatherAlertApplicability.UNAVAILABLE
        )
        status = (
            WeatherAlertProviderStatus.DEGRADED
            if previous.snapshot is not None
            else WeatherAlertProviderStatus.UNAVAILABLE
        )
        return self._publish_state(
            previous.model_copy(
                update={
                    "provider_status": status,
                    "applicability": applicability,
                    "last_error": message,
                }
            )
        )

    def _publish_failed_attempt(
        self,
        previous: ForgeWeatherAlertState,
        now: datetime,
        error: BaseException,
    ) -> ForgeWeatherAlertState:
        applicability = (
            WeatherAlertApplicability.RETAINED_UNVERIFIED
            if previous.snapshot is not None
            else WeatherAlertApplicability.UNAVAILABLE
        )
        status = (
            WeatherAlertProviderStatus.DEGRADED
            if previous.snapshot is not None
            else WeatherAlertProviderStatus.UNAVAILABLE
        )
        return self._publish_state(
            previous.model_copy(
                update={
                    "provider_status": status,
                    "applicability": applicability,
                    "last_attempt_at": now,
                    "last_error": self._bounded_error(error),
                }
            )
        )

    def _publish_state(self, state: ForgeWeatherAlertState) -> ForgeWeatherAlertState:
        with self._lock:
            self._state = state
            return self._state

    def _aware_now(self) -> datetime:
        value = self._now()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Forge weather alert clock must be timezone-aware")
        return value.astimezone(UTC)

    @staticmethod
    def _bounded_error(error: BaseException) -> str:
        text = str(error).strip() or error.__class__.__name__
        return text[:_MAX_ERROR_LENGTH]
