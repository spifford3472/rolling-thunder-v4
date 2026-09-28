"""Typed POTA spot domain models and deterministic filtering."""

from datetime import UTC, datetime, timedelta
from enum import StrEnum

from pydantic import Field, field_validator

from rolling_thunder.domain import DomainModel, Frequency, RadioMode
from rolling_thunder.value_types import Callsign, PotaReference


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


class PotaModeFilter(StrEnum):
    """Operator-facing POTA mode groups."""

    SSB_PHONE = "SSB"
    CW = "CW"
    FT4 = "FT4"
    FT8 = "FT8"
    DATA = "DATA"
    ALL = "ALL"


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

_DATA_SPOT_MODES = frozenset(
    {
        "DATA",
        "DIGITAL",
        "HELL",
        "JS8",
        "JT65",
        "JT9",
        "MFSK",
        "OLIVIA",
        "PACKET",
        "PSK",
        "PSK31",
        "RTTY",
        "SSTV",
    }
)


class ParkReference(DomainModel):
    """Normalized Parks on the Air program reference and location metadata."""

    reference: PotaReference
    name: str | None = Field(default=None, max_length=200)
    location_code: str | None = Field(default=None, max_length=100)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)

    @field_validator("name", "location_code")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        """Trim optional park text and convert blank text to None."""
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
    spot_mode: str | None = Field(default=None, max_length=20)
    comments: str | None = Field(default=None, max_length=500)

    @field_validator("mode", mode="before")
    @classmethod
    def normalize_mode(cls, value: object) -> object:
        """Normalize string mode values to the existing radio-mode contract."""
        if isinstance(value, str):
            return value.strip().upper()
        return value

    @field_validator("spot_mode")
    @classmethod
    def normalize_spot_mode(cls, value: str | None) -> str | None:
        """Preserve the normalized POTA mode used for operator filtering."""
        if value is None:
            return None
        normalized = value.strip().upper()
        return normalized or None

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

    @property
    def display_mode(self) -> str:
        """Return the POTA source mode, falling back to the radio mode."""
        if self.spot_mode is not None:
            return self.spot_mode
        if self.mode in {RadioMode.LSB, RadioMode.USB}:
            return "SSB"
        return self.mode.value


def frequency_band(frequency: Frequency) -> AmateurBand | None:
    """Return the supported amateur band containing a frequency."""
    for band, (lower_hz, upper_hz) in _BAND_LIMITS_HZ.items():
        if lower_hz <= frequency.hz <= upper_hz:
            return band
    return None


def _matches_mode_filter(spot: PotaSpot, mode_filter: PotaModeFilter) -> bool:
    """Return whether one spot belongs to an operator-facing mode group."""
    if mode_filter is PotaModeFilter.ALL:
        return True

    mode = spot.display_mode
    if mode_filter is PotaModeFilter.SSB_PHONE:
        return mode in {"SSB", "PHONE", "LSB", "USB"}
    if mode_filter is PotaModeFilter.CW:
        return mode == "CW"
    if mode_filter is PotaModeFilter.FT4:
        return mode == "FT4"
    if mode_filter is PotaModeFilter.FT8:
        return mode == "FT8"
    return mode in _DATA_SPOT_MODES


def filter_pota_spots(
    spots: list[PotaSpot],
    *,
    band: AmateurBand | None = None,
    mode: RadioMode | None = None,
    mode_filter: PotaModeFilter = PotaModeFilter.ALL,
    reference_time: datetime | None = None,
    maximum_age: timedelta | None = None,
) -> list[PotaSpot]:
    """Filter spots deterministically while preserving source order."""
    if maximum_age is not None:
        if maximum_age < timedelta(0):
            raise ValueError("POTA maximum spot age must not be negative.")
        if reference_time is None:
            raise ValueError("POTA freshness filtering requires a reference time.")

    if reference_time is not None:
        if reference_time.tzinfo is None or reference_time.utcoffset() is None:
            raise ValueError("POTA filter reference time must be timezone-aware.")
        reference_time = reference_time.astimezone(UTC)

    filtered: list[PotaSpot] = []
    for spot in spots:
        if band is not None and frequency_band(spot.frequency) is not band:
            continue
        if mode is not None and spot.mode is not mode:
            continue
        if not _matches_mode_filter(spot, mode_filter):
            continue
        if maximum_age is not None and reference_time is not None:
            age = reference_time - spot.spotted_at
            if age > maximum_age:
                continue
        filtered.append(spot)
    return filtered
