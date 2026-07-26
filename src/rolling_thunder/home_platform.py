"""Typed transport-independent boundary for the Home Station Platform."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from pydantic import Field, field_serializer, field_validator, model_validator

from rolling_thunder.domain import Contact, DomainModel


class HomePlatformError(Exception):
    """Base exception for Home Station Platform operations."""


class HomePlatformConnectionError(HomePlatformError):
    """Raised when the Home Station Platform cannot be reached."""


class HomePlatformUploadError(HomePlatformError):
    """Raised when a contact upload cannot be completed."""


class HomePlatformAvailability(StrEnum):
    """Current reachability state of the Home Station Platform."""

    UNKNOWN = "unknown"
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class ContactUploadDisposition(StrEnum):
    """Idempotent outcome returned for a contact upload request."""

    ACCEPTED = "accepted"
    ALREADY_EXISTS = "already_exists"


class HomePlatformState(DomainModel):
    """Immutable health and reachability snapshot for the remote platform."""

    availability: HomePlatformAvailability
    checked_at: datetime
    last_error: str | None = Field(default=None, max_length=500)

    @field_validator("availability", mode="before")
    @classmethod
    def normalize_availability(cls, value: object) -> object:
        """Normalize string availability values."""
        if isinstance(value, str):
            return value.strip().lower()
        return value

    @field_validator("checked_at")
    @classmethod
    def normalize_checked_at(cls, value: datetime) -> datetime:
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
    def validate_state_consistency(self) -> "HomePlatformState":
        """Require an explanation whenever the platform is unavailable."""
        if (
            self.availability is HomePlatformAvailability.UNAVAILABLE
            and self.last_error is None
        ):
            raise ValueError("unavailable platform state requires last_error")
        return self

    @field_serializer("checked_at")
    def serialize_checked_at(self, value: datetime) -> str:
        """Serialize timestamps as unambiguous UTC ISO-8601 values."""
        return value.isoformat().replace("+00:00", "Z")


class ContactUploadRequest(DomainModel):
    """Transport-neutral request to synchronize one locally stored contact."""

    contact: Contact

    @property
    def idempotency_key(self) -> UUID:
        """Use the immutable local contact ID as the remote idempotency key."""
        return self.contact.contact_id


class ContactUploadResult(DomainModel):
    """Typed result of an idempotent contact upload."""

    contact_id: UUID
    disposition: ContactUploadDisposition
    received_at: datetime

    @field_validator("disposition", mode="before")
    @classmethod
    def normalize_disposition(cls, value: object) -> object:
        """Normalize string upload dispositions."""
        if isinstance(value, str):
            return value.strip().lower()
        return value

    @field_validator("received_at")
    @classmethod
    def normalize_received_at(cls, value: datetime) -> datetime:
        """Require an aware timestamp and normalize it to UTC."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("must include timezone information")
        return value.astimezone(UTC)

    @field_serializer("received_at")
    def serialize_received_at(self, value: datetime) -> str:
        """Serialize timestamps as unambiguous UTC ISO-8601 values."""
        return value.isoformat().replace("+00:00", "Z")


class HomePlatformClient(Protocol):
    """Transport-independent client boundary consumed by application services."""

    def get_state(self) -> HomePlatformState:
        """Return the latest immutable platform state without performing I/O."""
        ...

    def check_health(self) -> HomePlatformState:
        """Refresh and return current platform reachability."""
        ...

    def upload_contact(self, request: ContactUploadRequest) -> ContactUploadResult:
        """Upload one contact idempotently or raise a typed platform error."""
        ...
