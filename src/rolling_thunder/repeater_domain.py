"""Typed local six-meter repeater domain and canonical catalog state."""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import Field, field_validator, model_validator

from rolling_thunder.domain import DomainModel, Frequency
from rolling_thunder.radio import RadioBand
from rolling_thunder.radio_band import RadioBandResolutionError, resolve_radio_band


class RepeaterChannelType(StrEnum):
    """Supported source repeater channel types."""

    ANALOGUE = "Analogue"


class RepeaterShiftDirection(StrEnum):
    """Transmit shift relative to the repeater receive frequency."""

    MINUS = "minus"
    SIMPLEX = "simplex"
    PLUS = "plus"


class RepeaterIdentity(DomainModel):
    """Stable repeater identity independent of CSV row position."""

    name: str = Field(min_length=1, max_length=200)
    rx_frequency: Frequency

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        """Collapse surrounding/repeated whitespace without changing display case."""
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("repeater name must not be blank")
        return normalized

    @property
    def stable_key(self) -> str:
        """Return a deterministic SQLite-safe serialized identity."""
        return f"6m:{self.rx_frequency.hz}:{self.name.casefold()}"


class RepeaterLocation(DomainModel):
    """Validated fixed repeater latitude/longitude."""

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class RepeaterRecord(DomainModel):
    """One immutable six-meter repeater record from approved local source data."""

    identity: RepeaterIdentity
    name: str = Field(min_length=1, max_length=200)
    callsign: str = Field(min_length=1, max_length=32)
    channel_type: RepeaterChannelType
    rx_frequency: Frequency
    tx_frequency: Frequency
    bandwidth_khz: Decimal = Field(gt=0)
    rx_tone_hz: Decimal | None = Field(default=None, gt=0)
    tx_tone_hz: Decimal | None = Field(default=None, gt=0)
    location: RepeaterLocation
    band_m: Literal[6] = 6
    source_active: bool

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("repeater name must not be blank")
        return normalized

    @field_validator("callsign")
    @classmethod
    def normalize_callsign(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("repeater callsign must not be blank")
        return normalized

    @model_validator(mode="after")
    def validate_identity_and_band(self) -> RepeaterRecord:
        """Fail closed when identity or action-critical frequencies are inconsistent."""
        if self.identity.name != self.name:
            raise ValueError("repeater identity name must match record name")
        if self.identity.rx_frequency != self.rx_frequency:
            raise ValueError("repeater identity frequency must match RX frequency")

        for label, frequency in (
            ("RX", self.rx_frequency),
            ("TX", self.tx_frequency),
        ):
            try:
                band = resolve_radio_band(frequency)
            except RadioBandResolutionError as error:
                raise ValueError(f"repeater {label} frequency must be in the 6 m band") from error
            if band is not RadioBand.BAND_6M:
                raise ValueError(f"repeater {label} frequency must be in the 6 m band")
        return self

    @property
    def stable_key(self) -> str:
        """Return the stable serialized repeater identity."""
        return self.identity.stable_key

    @property
    def shift_direction(self) -> RepeaterShiftDirection:
        """Return TX shift direction relative to RX."""
        if self.tx_frequency.hz < self.rx_frequency.hz:
            return RepeaterShiftDirection.MINUS
        if self.tx_frequency.hz > self.rx_frequency.hz:
            return RepeaterShiftDirection.PLUS
        return RepeaterShiftDirection.SIMPLEX

    @property
    def offset_hz(self) -> int:
        """Return absolute TX/RX offset magnitude in integer hertz."""
        return abs(self.tx_frequency.hz - self.rx_frequency.hz)


def repeater_order_key(repeater: RepeaterRecord) -> tuple[int, str, str]:
    """Return deterministic source-order-independent catalog ordering."""
    return (
        repeater.rx_frequency.hz,
        repeater.name.casefold(),
        repeater.stable_key,
    )


def canonicalize_repeaters(
    repeaters: Iterable[RepeaterRecord],
) -> tuple[RepeaterRecord, ...]:
    """Sort repeaters canonically while rejecting duplicate stable identities."""
    records = tuple(repeaters)
    stable_keys = [record.stable_key for record in records]
    if len(stable_keys) != len(set(stable_keys)):
        raise ValueError("repeater stable identities must be unique")
    return tuple(sorted(records, key=repeater_order_key))


class RepeaterCatalog(DomainModel):
    """Canonical immutable repeater catalog plus source provenance fingerprint."""

    source_filename: str = Field(min_length=1, max_length=255)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    repeaters: tuple[RepeaterRecord, ...] = ()

    @model_validator(mode="after")
    def validate_canonical_order(self) -> RepeaterCatalog:
        canonical = canonicalize_repeaters(self.repeaters)
        if canonical != self.repeaters:
            raise ValueError("repeaters must be unique and in canonical order")
        return self

    @classmethod
    def from_repeaters(
        cls,
        *,
        source_filename: str,
        source_sha256: str,
        repeaters: Iterable[RepeaterRecord],
    ) -> RepeaterCatalog:
        """Build one canonical catalog from arbitrary CSV row order."""
        return cls(
            source_filename=source_filename,
            source_sha256=source_sha256,
            repeaters=canonicalize_repeaters(repeaters),
        )
