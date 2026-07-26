"""Typed transport-independent boundary for retrieving POTA spots."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from pydantic import Field, field_validator, model_validator

from rolling_thunder.domain import DomainModel
from rolling_thunder.pota_spots import PotaSpot


class PotaSpotSourceError(Exception):
    """Base exception for POTA spot-source operations."""


class PotaSpotSourceConnectionError(PotaSpotSourceError):
    """Raised when the configured POTA spot source cannot be reached."""


class PotaSpotSourceResponseError(PotaSpotSourceError):
    """Raised when a POTA spot source returns an unusable response."""


class PotaSpotSourceAvailability(StrEnum):
    """Availability state reported for one POTA spot retrieval attempt."""

    UNKNOWN = "unknown"
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class PotaSpotFetchResult(DomainModel):
    """Immutable result of one transport-independent POTA spot fetch."""

    availability: PotaSpotSourceAvailability
    spots: tuple[PotaSpot, ...] = ()
    fetched_at: datetime
    last_error: str | None = Field(default=None, max_length=500)

    @field_validator("availability", mode="before")
    @classmethod
    def normalize_availability(cls, value: object) -> object:
        """Normalize string availability values."""
        if isinstance(value, str):
            return value.strip().lower()
        return value

    @field_validator("fetched_at")
    @classmethod
    def normalize_fetched_at(cls, value: datetime) -> datetime:
        """Require an aware timestamp and normalize it to UTC."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("must include timezone information")
        return value.astimezone(UTC)

    @field_validator("last_error")
    @classmethod
    def normalize_last_error(cls, value: str | None) -> str | None:
        """Trim optional errors and convert blank text to None."""
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def validate_consistency(self) -> "PotaSpotFetchResult":
        """Keep availability, spots, and error text internally consistent."""
        if self.availability is PotaSpotSourceAvailability.UNAVAILABLE:
            if self.last_error is None:
                raise ValueError("unavailable POTA spot result requires last_error")
            if self.spots:
                raise ValueError("unavailable POTA spot result cannot contain spots")
        elif self.last_error is not None:
            raise ValueError("available or unknown POTA spot result cannot contain last_error")
        return self


class PotaSpotSource(Protocol):
    """Transport-independent POTA spot source consumed by application services."""

    def fetch_spots(self) -> PotaSpotFetchResult:
        """Fetch one immutable spot snapshot or raise a typed source error."""
        ...


class MockPotaSpotSource:
    """Deterministic in-memory POTA spot source for tests and development."""

    def __init__(
        self,
        result: PotaSpotFetchResult,
        *,
        error: PotaSpotSourceError | None = None,
    ) -> None:
        self._result = result
        self._error = error
        self.fetch_count = 0

    def set_result(self, result: PotaSpotFetchResult) -> None:
        """Replace the next deterministic result."""
        self._result = result
        self._error = None

    def set_error(self, error: PotaSpotSourceError) -> None:
        """Configure a typed error for subsequent fetches."""
        self._error = error

    def fetch_spots(self) -> PotaSpotFetchResult:
        """Return the configured result or raise the configured typed error."""
        self.fetch_count += 1
        if self._error is not None:
            raise self._error
        return self._result
