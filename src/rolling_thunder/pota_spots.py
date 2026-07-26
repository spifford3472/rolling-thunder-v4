"""Typed POTA spot domain models and deterministic filtering."""

import re
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import Field, field_validator

from rolling_thunder.domain import DomainModel, Frequency, RadioMode
from rolling_thunder.value_types import Callsign

_PARK_REFERENCE_PATTERN = re.compile(r"^[A-Z0-9]{1,4}-[0-9]{4,6}$")


class AmateurBand(StrEnum):
    """Amateur bands supported by the first POTA filtering slice."""

    BAND_160M = "160m"
    BAND_80M = "80m"
    BAND_60M = "60m"
    BAND_40M = "40m"
    BAND_30M = "30m"
    BAND_20M = "20m"
    BAND_17M = "17m"
    BAND_15M = "15m"
    BAND_12M = "12m"
    BAND_10M = "10m"
    BAND_6M = "6m"


_BAND_LIMITS_HZ: dict[AmateurBand, tuple[int, int]] = {
    AmateurBand.BAND_160M: (1_800_000, 2_000_000),
    AmateurBand.BAND_80M: (3_500_000, 4_000_000),
    AmateurBand.BAND_60M: (5_300_000, 5_500_000),
    AmateurBand.BAND_40M: (7_000_000, 7_300_000),
    AmateurBand.BAND_30M: (10_100_000, 10_150_000),
    AmateurBand.BAND_20M: (14_000_000, 14_350_000),
    AmateurBand.BAND_17M: (18_068_000, 18_168_000),
    AmateurBand.BAND_15M: (21_000_000, 21_450_000),
    AmateurBand.BAND_12M: (24_890_000, 24_990_000),
    AmateurBand.BAND_10M: (28_000_000, 29_700_000),
    AmateurBand.BAND_6M: (50_000_000, 54_000_000),
}


class ParkReference(DomainModel):
    """Normalized Parks on the Air program reference."""

    reference: str
    name: str | None = Field(default=None, max_length=200)

    @field_validator("reference", mode="before")
    @classmethod
    def normalize_reference(cls, value: object) -> object:
        """Normalize string references before structural validation."""
        if isinstance(value, str):
            return value.strip().upper()
        return value

    @field_validator("reference")
    @classmethod
    def validate_reference(cls, value: str) -> str:
        """Require a program prefix and four-to-six digit park number."""
        if not _PARK_REFERENCE_PATTERN.fullmatch(value):
            raise ValueError("must be a POTA reference such as US-1234")
        return value

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        """Trim an optional park name and convert blank text to None."""
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class PotaSpot(DomainModel):
    """Immutable transport-independent POTA activation spot."""

    activator: Callsign
    park: ParkReference
    frequency: Frequency
    mode: RadioMode
    spotted_at: datetime
    comments: str | None = Field(default=None, max_length=500)

    @field_validator("mode", mode="before")
    @classmethod
    def normalize_mode(cls, value: object) -> object:
        """Normalize string mode values to the existing radio-mode contract."""
        if isinstance(value, str):
            return value.strip().upper()
        return value

    @field_validator("spotted_at")
    @classmethod
    def normalize_spotted_at(cls, value: datetime) -> datetime:
        """Require an aware timestamp and normalize it to UTC."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("must include timezone information")
        return value.astimezone(UTC)

    @field_validator("comments")
    @classmethod
    def normalize_comments(cls, value: str | None) -> str | None:
        """Trim optional comments and convert blank text to None."""
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


def frequency_band(frequency: Frequency) -> AmateurBand | None:
    """Return the supported amateur band containing a frequency."""
    for band, (lower_hz, upper_hz) in _BAND_LIMITS_HZ.items():
        if lower_hz <= frequency.hz <= upper_hz:
            return band
    return None


def filter_pota_spots(
    spots: list[PotaSpot],
    *,
    band: AmateurBand | None = None,
    mode: RadioMode | None = None,
) -> list[PotaSpot]:
    """Filter spots by optional band and mode while preserving source order."""
    return [
        spot
        for spot in spots
        if (band is None or frequency_band(spot.frequency) is band)
        and (mode is None or spot.mode is mode)
    ]
