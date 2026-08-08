"""Typed retained mobile-location domain and publication service for Forge."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from threading import RLock
from typing import Final, Protocol

from pydantic import Field, field_validator, model_validator

from rolling_thunder.domain import DomainModel

_MAX_ERROR_LENGTH: Final = 500
_MAX_FIX_TO_RECEIVE_AGE_S: Final = 30.0
_MAX_RECEIVED_AGE_S: Final = 120.0
_MAX_FUTURE_SKEW_S: Final = 30.0
_MAX_SPEED_M_S: Final = 100.0
Clock = Callable[[], datetime]


class ForgeMobileLocationStorageError(Exception):
    """Raised when retained mobile-location persistence cannot be used safely."""


class StaleMobileLocationError(Exception):
    """Raised when a candidate location is not newer than retained state."""


class InvalidMobileLocationTimingError(Exception):
    """Raised when an otherwise valid location is stale or implausibly future-dated."""


class MobileLocationRecord(DomainModel):
    """Provider-neutral latest vehicle location accepted by Forge."""

    latitude: float = Field(ge=-90.0, le=90.0, allow_inf_nan=False)
    longitude: float = Field(ge=-180.0, le=180.0, allow_inf_nan=False)
    fix_at: datetime
    received_at: datetime
    speed_m_s: float | None = Field(
        default=None,
        ge=0.0,
        le=_MAX_SPEED_M_S,
        allow_inf_nan=False,
    )
    heading_degrees: float | None = Field(
        default=None,
        ge=0.0,
        lt=360.0,
        allow_inf_nan=False,
    )

    @field_validator("fix_at", "received_at")
    @classmethod
    def normalize_timestamp(cls, value: datetime) -> datetime:
        """Require timezone-aware timestamps and normalize them to UTC."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("must include timezone information")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_fix_timing(self) -> MobileLocationRecord:
        """Reject impossible ordering and excessively old fixes wrapped as fresh input."""
        if self.fix_at > self.received_at:
            raise ValueError("fix_at must not be later than received_at")
        fix_age_s = (self.received_at - self.fix_at).total_seconds()
        if fix_age_s > _MAX_FIX_TO_RECEIVE_AGE_S:
            raise ValueError(
                "fix_at must be no more than 30 seconds older than received_at"
            )
        return self


class MobileLocationState(DomainModel):
    """Immutable retained Forge mobile-location publication state."""

    revision: int = Field(ge=0)
    location: MobileLocationRecord | None = None
    startup_storage_error: str | None = Field(default=None, max_length=_MAX_ERROR_LENGTH)
    persistence_error: str | None = Field(default=None, max_length=_MAX_ERROR_LENGTH)

    @field_validator("startup_storage_error", "persistence_error")
    @classmethod
    def normalize_error(cls, value: str | None) -> str | None:
        """Trim and bound optional storage diagnostics."""
        if value is None:
            return None
        normalized = value.strip()
        return normalized[:_MAX_ERROR_LENGTH] or None


class ForgeMobileLocationRepository(Protocol):
    """Durable singleton-location boundary consumed by the publication service."""

    def load(self) -> MobileLocationState | None:
        """Load and revalidate the latest retained location, when present."""
        ...

    def replace(self, location: MobileLocationRecord) -> MobileLocationState:
        """Transactionally replace retained state only with a newer location."""
        ...


class ForgeMobileLocationService:
    """Validate request timing, persist first, then publish immutable state."""

    def __init__(
        self,
        repository: ForgeMobileLocationRepository,
        *,
        now: Clock | None = None,
    ) -> None:
        self._repository = repository
        self._now = now or (lambda: datetime.now(UTC))
        self._lock = RLock()

        try:
            stored = repository.load()
        except ForgeMobileLocationStorageError as error:
            stored = None
            startup_error = self._bounded_error(error)
        else:
            startup_error = None

        self._state = stored or MobileLocationState(
            revision=0,
            startup_storage_error=startup_error,
        )

    def get_state(self) -> MobileLocationState:
        """Return the current immutable retained location without external work."""
        with self._lock:
            return self._state

    def publish(self, location: MobileLocationRecord) -> MobileLocationState:
        """Accept one current location only after successful durable persistence."""
        now = self._aware_now()
        if location.received_at > now + timedelta(seconds=_MAX_FUTURE_SKEW_S):
            raise InvalidMobileLocationTimingError(
                "received_at is more than 30 seconds ahead of Forge UTC"
            )
        if now - location.received_at > timedelta(seconds=_MAX_RECEIVED_AGE_S):
            raise InvalidMobileLocationTimingError(
                "received_at is more than 120 seconds old"
            )

        with self._lock:
            previous = self._state
            try:
                stored = self._repository.replace(location)
            except StaleMobileLocationError:
                raise
            except ForgeMobileLocationStorageError as error:
                self._state = previous.model_copy(
                    update={"persistence_error": self._bounded_error(error)}
                )
                raise

            self._state = stored.model_copy(
                update={
                    "startup_storage_error": None,
                    "persistence_error": None,
                }
            )
            return self._state

    def _aware_now(self) -> datetime:
        value = self._now()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Forge mobile-location clock must be timezone-aware")
        return value.astimezone(UTC)

    @staticmethod
    def _bounded_error(error: BaseException) -> str:
        text = str(error).strip() or error.__class__.__name__
        return text[:_MAX_ERROR_LENGTH]
