"""Presentation-neutral, bounded known-callsign directory contracts."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from rolling_thunder.value_types import Callsign

MAX_KNOWN_CALLSIGNS = 4096
MAX_LOOKUP_CALLSIGNS = 128
_CALLSIGN = TypeAdapter(Callsign)


def normalize_known_callsign(value: str) -> str:
    """Use the shared station-call validation, preserving portable suffixes."""
    return _CALLSIGN.validate_python(value)


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class KnownCallsignInput(_Model):
    """Private administration input; never a client response."""

    callsign: Callsign
    display_name: str = Field(default="", max_length=160)
    comment: str = Field(default="", max_length=4000)
    active: bool = Field(default=True, strict=True)


class KnownCallsignStatus(_Model):
    callsign: Callsign
    known: bool = Field(strict=True)
    relationship: Literal["friend"] | None = None

    @model_validator(mode="after")
    def consistent_relationship(self) -> Self:
        if self.known != (self.relationship == "friend"):
            raise ValueError("known and relationship must agree")
        return self


class KnownCallsignBatch(_Model):
    callsigns: tuple[Callsign, ...] = Field(min_length=1, max_length=MAX_LOOKUP_CALLSIGNS)


class KnownCallsignLookup(_Model):
    api_schema_version: Literal["1"] = "1"
    results: tuple[KnownCallsignStatus, ...] = Field(max_length=MAX_LOOKUP_CALLSIGNS)


class KnownCallsignSnapshot(_Model):
    api_schema_version: Literal["1"] = "1"
    entries: tuple[KnownCallsignStatus, ...] = Field(max_length=MAX_KNOWN_CALLSIGNS)

    @model_validator(mode="after")
    def active_unique_entries(self) -> Self:
        if any(not entry.known for entry in self.entries):
            raise ValueError("snapshot must contain only active known callsigns")
        if len({entry.callsign for entry in self.entries}) != len(self.entries):
            raise ValueError("snapshot callsigns must be unique")
        return self
