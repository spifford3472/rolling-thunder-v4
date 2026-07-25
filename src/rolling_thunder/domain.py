"""Core domain models for Rolling Thunder contacts."""

import re
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
)

_CALLSIGN_PATTERN = re.compile(
    r"^[A-Z0-9]{1,3}[0-9][A-Z0-9]{1,4}(?:/[A-Z0-9]{1,4})?$"
)
_GRID_PATTERN = re.compile(
    r"^[A-R]{2}[0-9]{2}(?:[A-X]{2}(?:[0-9]{2})?)?$",
    re.IGNORECASE,
)
_SIGNAL_REPORT_PATTERN = re.compile(r"^(?:[1-5][1-9][1-9]?|[+-]?[0-9]{1,2})$")


class RadioMode(StrEnum):
    """Supported radio operating modes."""

    AM = "AM"
    CW = "CW"
    DATA = "DATA"
    FM = "FM"
    LSB = "LSB"
    USB = "USB"


class SynchronizationState(StrEnum):
    """Remote synchronization state for a locally stored contact."""

    PENDING = "pending"
    SYNCHRONIZED = "synchronized"
    FAILED = "failed"


class DomainModel(BaseModel):
    """Base model shared by immutable Rolling Thunder domain objects."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        use_enum_values=False,
    )


class Contact(DomainModel):
    """A completed amateur-radio contact."""

    contact_id: UUID = Field(default_factory=uuid4)
    callsign: str
    frequency_hz: int = Field(gt=0, le=300_000_000_000)
    mode: RadioMode
    started_at: datetime
    rst_sent: str
    rst_received: str
    grid: str | None = None
    notes: str | None = Field(default=None, max_length=2_000)
    synchronization_state: SynchronizationState = SynchronizationState.PENDING

    @field_validator("callsign")
    @classmethod
    def validate_callsign(cls, value: str) -> str:
        """Normalize and validate the contacted station's callsign."""
        normalized = value.strip().upper()

        if not _CALLSIGN_PATTERN.fullmatch(normalized):
            raise ValueError(
                "must be a valid amateur-radio callsign, such as KI5VNB or KI5VNB/P"
            )

        return normalized

    @field_validator("mode", mode="before")
    @classmethod
    def normalize_mode(cls, value: object) -> object:
        """Normalize string mode values before enum validation."""
        if isinstance(value, str):
            return value.strip().upper()

        return value

    @field_validator("started_at")
    @classmethod
    def validate_started_at(cls, value: datetime) -> datetime:
        """Require a timezone-aware timestamp and normalize it to UTC."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("must include timezone information")

        return value.astimezone(UTC)

    @field_validator("rst_sent", "rst_received")
    @classmethod
    def validate_signal_report(cls, value: str) -> str:
        """Validate conventional voice, CW, and digital signal reports."""
        normalized = value.strip()

        if not _SIGNAL_REPORT_PATTERN.fullmatch(normalized):
            raise ValueError(
                "must be a conventional report such as 59, 599, or -10"
            )

        return normalized

    @field_validator("grid")
    @classmethod
    def validate_grid(cls, value: str | None) -> str | None:
        """Normalize and validate an optional Maidenhead grid locator."""
        if value is None:
            return None

        normalized = value.strip()

        if not _GRID_PATTERN.fullmatch(normalized):
            raise ValueError(
                "must be a 4-, 6-, or 8-character Maidenhead grid, such as EM79xm"
            )

        if len(normalized) == 4:
            return normalized[:2].upper() + normalized[2:]

        return (
            normalized[:2].upper()
            + normalized[2:4]
            + normalized[4:6].lower()
            + normalized[6:]
        )

    @field_validator("notes")
    @classmethod
    def normalize_notes(cls, value: str | None) -> str | None:
        """Trim optional notes and convert blank notes to None."""
        if value is None:
            return None

        normalized = value.strip()
        return normalized or None

    @field_serializer("started_at")
    def serialize_started_at(self, value: datetime) -> str:
        """Serialize timestamps as an unambiguous UTC ISO-8601 value."""
        return value.isoformat().replace("+00:00", "Z")
