"""Strict parser for immutable local six-meter repeater CSV deployment data."""

from __future__ import annotations

import csv
import hashlib
import io
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Final

from pydantic import ValidationError

from rolling_thunder.domain import Frequency
from rolling_thunder.repeater_domain import (
    RepeaterCatalog,
    RepeaterChannelType,
    RepeaterIdentity,
    RepeaterLocation,
    RepeaterRecord,
)

DEFAULT_REPEATER_CSV_PATH: Final = Path("data/repeaters/6m_repeaters.csv")
EXPECTED_REPEATER_CSV_HEADERS: Final[tuple[str, ...]] = (
    "Channel Name",
    "Channel Type",
    "Rx Frequency",
    "Tx Frequency",
    "Bandwidth (kHz)",
    "RX Tone",
    "TX Tone",
    "Latitude",
    "Longitude",
    "Band",
    "Active",
)


class RepeaterCsvError(Exception):
    """Base error for local repeater source parsing."""


class RepeaterCsvSchemaError(RepeaterCsvError):
    """Raised when the CSV columns do not match the approved source schema."""


class RepeaterCsvRowError(RepeaterCsvError):
    """Raised when one source row contains malformed action-critical data."""


def _required_text(row: dict[str | None, str | list[str] | None], column: str) -> str:
    value = row.get(column)
    if value is None:
        raise ValueError(f"{column} is missing")
    if not isinstance(value, str):
        raise TypeError(f"{column} must be text")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{column} must not be blank")
    return normalized


def _parse_decimal(raw: str, column: str) -> Decimal:
    try:
        value = Decimal(raw)
    except InvalidOperation as error:
        raise ValueError(f"{column} must be numeric") from error
    if not value.is_finite():
        raise ValueError(f"{column} must be finite")
    return value


def _parse_frequency_mhz(raw: str, column: str) -> Frequency:
    mhz = _parse_decimal(raw, column)
    hz = mhz * Decimal(1_000_000)
    integral_hz = hz.to_integral_value()
    if hz != integral_hz:
        raise ValueError(f"{column} must resolve exactly to integer hertz")
    return Frequency(hz=int(integral_hz))


def _parse_optional_tone(raw: object, column: str) -> Decimal | None:
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise TypeError(f"{column} must be text")
    normalized = raw.strip()
    if not normalized:
        return None
    value = _parse_decimal(normalized, column)
    if value <= 0:
        raise ValueError(f"{column} must be positive when supplied")
    return value


def _parse_active(raw: str) -> bool:
    normalized = raw.strip().casefold()
    if normalized == "yes":
        return True
    if normalized == "no":
        return False
    raise ValueError("Active must be Yes or No")


def _parse_row(
    row: dict[str | None, str | list[str] | None],
) -> RepeaterRecord:
    if row.get(None):
        raise ValueError("row contains unexpected extra CSV fields")

    name = _required_text(row, "Channel Name")
    callsign = name.split(maxsplit=1)[0]
    channel_type = _required_text(row, "Channel Type")
    if channel_type.casefold() != RepeaterChannelType.ANALOGUE.value.casefold():
        raise ValueError("Channel Type must be Analogue")

    rx_frequency = _parse_frequency_mhz(
        _required_text(row, "Rx Frequency"),
        "Rx Frequency",
    )
    tx_frequency = _parse_frequency_mhz(
        _required_text(row, "Tx Frequency"),
        "Tx Frequency",
    )
    bandwidth_khz = _parse_decimal(
        _required_text(row, "Bandwidth (kHz)"),
        "Bandwidth (kHz)",
    )
    if bandwidth_khz <= 0:
        raise ValueError("Bandwidth (kHz) must be positive")

    latitude = float(_parse_decimal(_required_text(row, "Latitude"), "Latitude"))
    longitude = float(_parse_decimal(_required_text(row, "Longitude"), "Longitude"))

    band = _required_text(row, "Band")
    if band != "6":
        raise ValueError("Band must be 6")

    return RepeaterRecord(
        identity=RepeaterIdentity(name=name, rx_frequency=rx_frequency),
        name=name,
        callsign=callsign,
        channel_type=RepeaterChannelType.ANALOGUE,
        rx_frequency=rx_frequency,
        tx_frequency=tx_frequency,
        bandwidth_khz=bandwidth_khz,
        rx_tone_hz=_parse_optional_tone(row.get("RX Tone"), "RX Tone"),
        tx_tone_hz=_parse_optional_tone(row.get("TX Tone"), "TX Tone"),
        location=RepeaterLocation(latitude=latitude, longitude=longitude),
        band_m=6,
        source_active=_parse_active(_required_text(row, "Active")),
    )


def load_repeater_csv(path: Path = DEFAULT_REPEATER_CSV_PATH) -> RepeaterCatalog:
    """Load, fingerprint, validate, and canonicalize the immutable repeater CSV."""
    try:
        source_bytes = path.read_bytes()
    except OSError as error:
        raise RepeaterCsvError(f"Repeater CSV could not be read: {path}: {error}") from error

    source_sha256 = hashlib.sha256(source_bytes).hexdigest()

    try:
        text = source_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise RepeaterCsvError(f"Repeater CSV must be UTF-8 text: {path}") from error

    reader = csv.DictReader(io.StringIO(text, newline=""))
    headers = tuple(reader.fieldnames or ())
    if headers != EXPECTED_REPEATER_CSV_HEADERS:
        raise RepeaterCsvSchemaError(
            "Repeater CSV headers do not match the approved schema: "
            f"expected {EXPECTED_REPEATER_CSV_HEADERS!r}, got {headers!r}"
        )

    repeaters: list[RepeaterRecord] = []
    for line_number, row in enumerate(reader, start=2):
        try:
            repeaters.append(_parse_row(row))
        except (TypeError, ValueError, ValidationError) as error:
            raise RepeaterCsvRowError(
                f"Repeater CSV row {line_number} is invalid: {error}"
            ) from error

    try:
        return RepeaterCatalog.from_repeaters(
            source_filename=path.name,
            source_sha256=source_sha256,
            repeaters=repeaters,
        )
    except ValueError as error:
        raise RepeaterCsvRowError(f"Repeater CSV catalog is invalid: {error}") from error
