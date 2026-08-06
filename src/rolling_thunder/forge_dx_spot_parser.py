"""Deterministic parsing and mode resolution for DXSpider realtime spots."""

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from re import IGNORECASE, compile as compile_pattern
from typing import Literal

from pydantic import TypeAdapter, ValidationError

from rolling_thunder.domain import Frequency, RadioMode
from rolling_thunder.radio import RadioBand
from rolling_thunder.radio_band import RadioBandResolutionError, resolve_radio_band
from rolling_thunder.spot_domain import (
    DxSpotIdentity,
    SpotRecord,
    SpotSourceMetadataItem,
)
from rolling_thunder.value_types import MaidenheadGrid

_DX_LINE_PATTERN = compile_pattern(
    r"^\s*DX\s+de\s+(?P<spotter>[^:\s]+):\s+"
    r"(?P<frequency>\d+(?:\.\d+)?)\s+"
    r"(?P<callsign>\S+)"
    r"(?:\s+(?P<body>.*?))?"
    r"\s+(?P<hhmm>\d{4})Z\s*$",
    IGNORECASE,
)
_MODE_TOKEN_PATTERN = compile_pattern(
    r"(?<![A-Z0-9])"
    r"(?P<token>FT8|FT4|RTTY|PSK(?:31|63|125)?|JT65|JS8|DATA|LSB|USB|SSB|CW|AM|FM)"
    r"(?![A-Z0-9])",
    IGNORECASE,
)
_GRID_TOKEN_PATTERN = compile_pattern(
    r"(?<![A-Z0-9])([A-R]{2}[0-9]{2}(?:[A-X]{2}(?:[0-9]{2})?)?)(?![A-Z0-9])",
    IGNORECASE,
)
_GRID_ADAPTER = TypeAdapter(MaidenheadGrid)
_FUTURE_TOLERANCE = timedelta(minutes=5)
_MAX_METADATA_VALUE_LENGTH = 500

_DIGITAL_MODE_TOKENS = frozenset({"FT8", "FT4", "RTTY", "PSK", "JT65", "JS8", "DATA"})
_CW_EDGE_HZ: dict[RadioBand, int] = {
    RadioBand.BAND_160M: 1_840_000,
    RadioBand.BAND_80M: 3_600_000,
    RadioBand.BAND_40M: 7_125_000,
    RadioBand.BAND_20M: 14_150_000,
    RadioBand.BAND_17M: 18_110_000,
    RadioBand.BAND_15M: 21_200_000,
    RadioBand.BAND_12M: 24_930_000,
    RadioBand.BAND_10M: 28_300_000,
    RadioBand.BAND_6M: 50_100_000,
}


class DxSpotLineError(ValueError):
    """Raised when one spot-like DXSpider line cannot be normalized safely."""


@dataclass(frozen=True, slots=True)
class DxModeResolution:
    """Normalized radio mode plus provider-facing display provenance."""

    mode: RadioMode
    display_mode: str
    source: Literal["explicit", "fallback"]


def is_dx_spot_line(line: str) -> bool:
    """Return whether text looks like one DXSpider realtime spot line."""
    return line.lstrip().upper().startswith("DX DE ")


def parse_dx_frequency(value: str) -> Frequency:
    """Convert decimal DX-cluster kilohertz exactly into integer hertz."""
    try:
        kilohertz = Decimal(value)
    except InvalidOperation as error:
        raise DxSpotLineError("DX spot frequency is not valid decimal kilohertz.") from error

    hertz = kilohertz * 1_000
    if not hertz.is_finite() or hertz != hertz.to_integral_value():
        raise DxSpotLineError("DX spot frequency must resolve exactly to integer hertz.")

    try:
        return Frequency(hz=int(hertz))
    except ValidationError as error:
        raise DxSpotLineError("DX spot frequency is outside the supported range.") from error


def reconstruct_dx_timestamp(hhmm: str, *, fetched_at: datetime) -> datetime:
    """Reconstruct a UTC spot timestamp with deterministic midnight rollover."""
    if fetched_at.tzinfo is None or fetched_at.utcoffset() is None:
        raise ValueError("fetched_at must include timezone information")
    if len(hhmm) != 4 or not hhmm.isdigit():
        raise DxSpotLineError("DX spot time must use HHMMZ format.")

    hour = int(hhmm[:2])
    minute = int(hhmm[2:])
    if hour > 23 or minute > 59:
        raise DxSpotLineError("DX spot time contains an invalid UTC hour or minute.")

    fetched_utc = fetched_at.astimezone(UTC)
    candidate = datetime.combine(
        fetched_utc.date(),
        time(hour=hour, minute=minute, tzinfo=UTC),
    )
    if candidate > fetched_utc + _FUTURE_TOLERANCE:
        candidate -= timedelta(days=1)
    return candidate


def resolve_dx_mode(frequency: Frequency, comment: str) -> DxModeResolution:
    """Resolve explicit mode tokens first, then deterministic band fallback."""
    match = _MODE_TOKEN_PATTERN.search(comment)
    if match is not None:
        display_token = match.group("token").upper()
        normalized_token = "PSK" if display_token.startswith("PSK") else display_token
        if normalized_token in _DIGITAL_MODE_TOKENS:
            mode = RadioMode.DATA
        elif normalized_token == "SSB":
            mode = _sideband_for_frequency(frequency)
        else:
            mode = RadioMode(normalized_token)
        return DxModeResolution(
            mode=mode,
            display_mode=display_token,
            source="explicit",
        )

    mode = _fallback_mode(frequency)
    return DxModeResolution(
        mode=mode,
        display_mode=mode.value,
        source="fallback",
    )


def parse_dx_spot_line(line: str, *, fetched_at: datetime) -> SpotRecord:
    """Parse one canonical DXSpider realtime line into a shared spot record."""
    match = _DX_LINE_PATTERN.fullmatch(line)
    if match is None:
        raise DxSpotLineError("DX spot line does not match realtime DXSpider format.")

    frequency = parse_dx_frequency(match.group("frequency"))
    callsign = match.group("callsign").strip().upper()
    spotter = _bounded_text(match.group("spotter"))
    comment = " ".join((match.group("body") or "").split())
    timestamp = reconstruct_dx_timestamp(match.group("hhmm"), fetched_at=fetched_at)
    resolution = resolve_dx_mode(frequency, comment)
    grid = _extract_provider_grid(comment)

    metadata = [
        SpotSourceMetadataItem(key="mode_source", value=resolution.source),
        SpotSourceMetadataItem(key="spotter", value=spotter),
    ]
    if comment:
        metadata.append(
            SpotSourceMetadataItem(
                key="comment",
                value=_bounded_text(comment),
            )
        )

    try:
        identity = DxSpotIdentity(callsign=callsign, frequency=frequency)
        return SpotRecord(
            identity=identity,
            callsign=callsign,
            operator_name=None,
            grid=grid,
            frequency=frequency,
            mode=resolution.mode,
            display_mode=resolution.display_mode,
            spotted_at=timestamp,
            source_metadata=tuple(metadata),
            pota=None,
        )
    except ValidationError as error:
        raise DxSpotLineError("DX spot line contains invalid normalized values.") from error


def _extract_provider_grid(comment: str) -> MaidenheadGrid | None:
    """Return the last valid Maidenhead locator supplied by the provider."""
    matches = list(_GRID_TOKEN_PATTERN.finditer(comment))
    for match in reversed(matches):
        try:
            return _GRID_ADAPTER.validate_python(match.group(1))
        except ValidationError:
            continue
    return None


def _fallback_mode(frequency: Frequency) -> RadioMode:
    """Apply a documented deterministic lower-sub-band mode convention."""
    try:
        band = resolve_radio_band(frequency)
    except RadioBandResolutionError:
        return _sideband_for_frequency(frequency)

    if band is RadioBand.BAND_60M:
        return RadioMode.USB
    if band is RadioBand.BAND_30M:
        return RadioMode.CW if frequency.hz < 10_130_000 else RadioMode.DATA

    cw_edge = _CW_EDGE_HZ.get(band)
    if cw_edge is not None and frequency.hz < cw_edge:
        return RadioMode.CW
    return _sideband_for_frequency(frequency)


def _sideband_for_frequency(frequency: Frequency) -> RadioMode:
    """Apply the conventional LSB-below-10-MHz, USB-above rule."""
    return RadioMode.LSB if frequency.hz < 10_000_000 else RadioMode.USB


def _bounded_text(value: str) -> str:
    """Normalize and bound provider-derived metadata without logging payloads."""
    normalized = " ".join(value.split())
    return normalized[:_MAX_METADATA_VALUE_LENGTH]
