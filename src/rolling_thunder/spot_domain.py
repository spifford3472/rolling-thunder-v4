"""Provider-neutral spot domain models and deterministic canonicalization."""

from collections.abc import Iterable
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal, TypeAlias

from pydantic import Field, field_validator, model_validator

from rolling_thunder.domain import DomainModel, Frequency, RadioMode
from rolling_thunder.radio import RadioBand
from rolling_thunder.radio_band import RadioBandResolutionError, resolve_radio_band
from rolling_thunder.value_types import Callsign, MaidenheadGrid, PotaReference

UNKNOWN_SPOT_VALUE = "<UNKNOWN>"


class SpotProvider(StrEnum):
    """Supported provider families for shared operating spots."""

    POTA = "pota"
    DX = "dx"


class SpotSourceMetadataItem(DomainModel):
    """One immutable provider-specific metadata entry."""

    key: str = Field(min_length=1, max_length=100)
    value: str = Field(min_length=1, max_length=500)

    @field_validator("key")
    @classmethod
    def normalize_key(cls, value: str) -> str:
        """Normalize metadata keys for deterministic uniqueness."""
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized

    @field_validator("value")
    @classmethod
    def normalize_value(cls, value: str) -> str:
        """Trim metadata values and reject blank text."""
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized


class PotaSpotIdentity(DomainModel):
    """Stable POTA identity independent of activator callsign or list position."""

    provider: Literal[SpotProvider.POTA] = SpotProvider.POTA
    park_reference: PotaReference
    frequency: Frequency

    @property
    def stable_key(self) -> str:
        """Return a deterministic serialized identity key."""
        return f"{self.provider.value}:{self.park_reference}:{self.frequency.hz}"


class DxSpotIdentity(DomainModel):
    """Stable DX identity independent of provider arrival order."""

    provider: Literal[SpotProvider.DX] = SpotProvider.DX
    callsign: Callsign
    frequency: Frequency

    @property
    def stable_key(self) -> str:
        """Return a deterministic serialized identity key."""
        return f"{self.provider.value}:{self.callsign}:{self.frequency.hz}"


SpotIdentity: TypeAlias = PotaSpotIdentity | DxSpotIdentity


class PotaSpotMetadata(DomainModel):
    """Optional POTA-only park metadata attached to a shared spot."""

    park_reference: PotaReference
    park_name: str | None = Field(default=None, max_length=200)
    location_code: str | None = Field(default=None, max_length=100)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)

    @field_validator("park_name", "location_code")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        """Trim optional text and convert blank values to None."""
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def validate_coordinates(self) -> "PotaSpotMetadata":
        """Require latitude and longitude to be supplied together."""
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("POTA latitude and longitude must both be provided or both be absent")
        return self


class SpotRecord(DomainModel):
    """Immutable provider-neutral operating spot."""

    identity: SpotIdentity
    callsign: Callsign
    operator_name: str | None = Field(default=None, max_length=200)
    grid: MaidenheadGrid | None = None
    frequency: Frequency
    mode: RadioMode
    display_mode: str = Field(min_length=1, max_length=40)
    spotted_at: datetime
    source_metadata: tuple[SpotSourceMetadataItem, ...] = ()
    pota: PotaSpotMetadata | None = None

    @field_validator("operator_name")
    @classmethod
    def normalize_operator_name(cls, value: str | None) -> str | None:
        """Trim optional operator names and convert blank values to None."""
        if value is None:
            return None
        normalized = " ".join(value.split())
        return normalized or None

    @field_validator("mode", mode="before")
    @classmethod
    def normalize_mode(cls, value: object) -> object:
        """Normalize string radio modes before enum validation."""
        if isinstance(value, str):
            return value.strip().upper()
        return value

    @field_validator("display_mode", mode="before")
    @classmethod
    def normalize_display_mode(cls, value: object) -> object:
        """Normalize provider display modes for stable presentation."""
        if isinstance(value, str):
            return value.strip().upper()
        return value

    @field_validator("spotted_at")
    @classmethod
    def normalize_spotted_at(cls, value: datetime) -> datetime:
        """Require an aware source timestamp and normalize it to UTC."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("spotted_at must include timezone information")
        return value.astimezone(UTC)

    @field_validator("source_metadata")
    @classmethod
    def normalize_source_metadata(
        cls,
        value: tuple[SpotSourceMetadataItem, ...],
    ) -> tuple[SpotSourceMetadataItem, ...]:
        """Sort metadata and reject duplicate keys deterministically."""
        ordered = tuple(sorted(value, key=lambda item: (item.key, item.value)))
        keys = [item.key for item in ordered]
        if len(keys) != len(set(keys)):
            raise ValueError("source metadata keys must be unique")
        return ordered

    @model_validator(mode="after")
    def validate_identity_consistency(self) -> "SpotRecord":
        """Require identity, frequency, provider metadata, and callsign to agree."""
        if self.identity.frequency != self.frequency:
            raise ValueError("spot frequency must match identity frequency")

        if isinstance(self.identity, PotaSpotIdentity):
            if self.pota is None:
                raise ValueError("POTA spots require POTA park metadata")
            if self.pota.park_reference != self.identity.park_reference:
                raise ValueError("POTA metadata must match the stable identity")
        else:
            if self.pota is not None:
                raise ValueError("DX spots cannot contain POTA park metadata")
            if self.callsign != self.identity.callsign:
                raise ValueError("DX callsign must match the stable identity")

        return self

    @property
    def provider(self) -> SpotProvider:
        """Return the provider encoded by the stable identity."""
        return self.identity.provider

    @property
    def stable_key(self) -> str:
        """Return the serialized stable identity key."""
        return self.identity.stable_key


_BAND_RANK: dict[RadioBand, int] = {
    RadioBand.BAND_160M: 0,
    RadioBand.BAND_80M: 1,
    RadioBand.BAND_60M: 2,
    RadioBand.BAND_40M: 3,
    RadioBand.BAND_30M: 4,
    RadioBand.BAND_20M: 5,
    RadioBand.BAND_17M: 6,
    RadioBand.BAND_15M: 7,
    RadioBand.BAND_12M: 8,
    RadioBand.BAND_10M: 9,
    RadioBand.BAND_6M: 10,
    RadioBand.BAND_2M: 11,
    RadioBand.BAND_70CM: 12,
}

_PROVIDER_RANK: dict[SpotProvider, int] = {
    SpotProvider.POTA: 0,
    SpotProvider.DX: 1,
}


def format_optional_spot_value(value: str | None) -> str:
    """Format unknown optional spot text only at the presentation boundary."""
    return value if value is not None else UNKNOWN_SPOT_VALUE


def amateur_band_rank(frequency: Frequency) -> int:
    """Return the explicit shared-panel rank for one amateur frequency."""
    try:
        band = resolve_radio_band(frequency)
    except RadioBandResolutionError:
        return len(_BAND_RANK)
    return _BAND_RANK[band]


def spot_order_key(spot: SpotRecord) -> tuple[int, int, int, str, str, str, str]:
    """Return a provider-arrival-independent ordering key."""
    return (
        amateur_band_rank(spot.frequency),
        spot.frequency.hz,
        _PROVIDER_RANK[spot.provider],
        spot.stable_key,
        str(spot.callsign),
        spot.mode.value,
        spot.display_mode,
    )


def _metadata_key(
    metadata: tuple[SpotSourceMetadataItem, ...],
) -> tuple[tuple[str, str], ...]:
    return tuple((item.key, item.value) for item in metadata)


def _pota_metadata_key(
    metadata: PotaSpotMetadata | None,
) -> tuple[str, str, str, float, float]:
    if metadata is None:
        return ("", "", "", -91.0, -181.0)
    return (
        str(metadata.park_reference),
        metadata.park_name or "",
        metadata.location_code or "",
        metadata.latitude if metadata.latitude is not None else -91.0,
        metadata.longitude if metadata.longitude is not None else -181.0,
    )


def _duplicate_preference_key(
    spot: SpotRecord,
) -> tuple[
    int,
    str,
    str,
    str,
    str,
    str,
    tuple[tuple[str, str], ...],
    tuple[str, str, str, float, float],
]:
    """Prefer newest data, then deterministic normalized content."""
    timestamp_us = int(spot.spotted_at.timestamp() * 1_000_000)
    return (
        -timestamp_us,
        str(spot.callsign),
        spot.mode.value,
        spot.display_mode,
        spot.operator_name or "",
        str(spot.grid or ""),
        _metadata_key(spot.source_metadata),
        _pota_metadata_key(spot.pota),
    )


def collapse_duplicate_spots(
    spots: Iterable[SpotRecord],
) -> tuple[SpotRecord, ...]:
    """Collapse duplicate stable identities without using arrival order."""
    grouped: dict[str, list[SpotRecord]] = {}
    for spot in spots:
        grouped.setdefault(spot.stable_key, []).append(spot)

    winners = (min(group, key=_duplicate_preference_key) for _, group in sorted(grouped.items()))
    return tuple(winners)


def canonicalize_spots(
    spots: Iterable[SpotRecord],
) -> tuple[SpotRecord, ...]:
    """Collapse duplicates and apply the explicit shared ordering."""
    return tuple(sorted(collapse_duplicate_spots(spots), key=spot_order_key))


class SpotSnapshot(DomainModel):
    """Canonical immutable provider-neutral spot snapshot."""

    generated_at: datetime
    spots: tuple[SpotRecord, ...] = ()

    @field_validator("generated_at")
    @classmethod
    def normalize_generated_at(cls, value: datetime) -> datetime:
        """Require an aware snapshot timestamp and normalize it to UTC."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("generated_at must include timezone information")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_canonical_order(self) -> "SpotSnapshot":
        """Reject duplicate or noncanonical spot tuples."""
        canonical = canonicalize_spots(self.spots)
        if canonical != self.spots:
            raise ValueError("spots must be duplicate-free and in canonical shared order")
        return self

    @classmethod
    def from_spots(
        cls,
        *,
        generated_at: datetime,
        spots: Iterable[SpotRecord],
    ) -> "SpotSnapshot":
        """Build a canonical snapshot from arbitrary provider input order."""
        return cls(
            generated_at=generated_at,
            spots=canonicalize_spots(spots),
        )

    @classmethod
    def empty(cls, *, generated_at: datetime) -> "SpotSnapshot":
        """Build an empty canonical snapshot."""
        return cls(generated_at=generated_at)

    def index_of(self, identity: SpotIdentity) -> int | None:
        """Return the current index of one stable identity."""
        for index, spot in enumerate(self.spots):
            if spot.identity == identity:
                return index
        return None

    def get(self, identity: SpotIdentity) -> SpotRecord | None:
        """Return the current record for one stable identity."""
        index = self.index_of(identity)
        return self.spots[index] if index is not None else None
