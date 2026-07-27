"""Operator-created POTA tune intent with no radio side effects."""

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import field_validator

from rolling_thunder.domain import DomainModel, Frequency, RadioMode
from rolling_thunder.value_types import Callsign


class PotaTuneIntentStatus(StrEnum):
    """Lifecycle states before any radio command is permitted."""

    PENDING_CONFIRMATION = "pending_confirmation"
    CANCELLED = "cancelled"


class PotaTuneIntent(DomainModel):
    """Immutable operator intent derived from one explicitly selected spot."""

    status: PotaTuneIntentStatus
    activator: Callsign
    park_reference: str
    frequency: Frequency
    mode: RadioMode
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def normalize_created_at(cls, value: datetime) -> datetime:
        """Require an aware timestamp and normalize it to UTC."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must include timezone information")
        return value.astimezone(UTC)

    def cancel(self) -> "PotaTuneIntent":
        """Return a cancelled copy without performing any external action."""
        return self.model_copy(
            update={"status": PotaTuneIntentStatus.CANCELLED}
        )
