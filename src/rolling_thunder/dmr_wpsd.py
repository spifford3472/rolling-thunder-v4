"""UI-independent parsing for WPSD DMR history and hotspot radio information."""

import html
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Mapping

from rolling_thunder.dmr_activity import DmrActivitySource

_DMR_MODE = re.compile(r"^DMR\s+(?:Slot|TS)\s*(?P<slot>[12])$", re.IGNORECASE)
_TALKGROUP = re.compile(r"\bTG\s+(?P<talkgroup>\d+)\b", re.IGNORECASE)
_HTML_TAG = re.compile(r"<[^>]+>")
_HEADER_CELL = re.compile(
    r"<div\b[^>]*class=[\"'][^\"']*\bdivTableHeadCell\b[^\"']*[\"'][^>]*>"
    r"(?P<value>.*?)</div>",
    re.IGNORECASE | re.DOTALL,
)
_DATA_CELL = re.compile(
    r"<div\b[^>]*class=[\"'][^\"']*\bdivTableCell\b[^\"']*[\"'][^>]*>"
    r"(?P<value>.*?)</div>",
    re.IGNORECASE | re.DOTALL,
)
_FREQUENCY_MHZ = re.compile(r"(?P<value>[0-9][0-9.,]*)\s*MHz", re.IGNORECASE)


class WpsdPayloadError(ValueError):
    """Raised when a WPSD payload does not contain the required DMR information."""


@dataclass(frozen=True, slots=True)
class WpsdDmrHistoryIdentity:
    """Stable identity for one completed WPSD DMR activity row."""

    occurred_at: datetime
    callsign: str
    slot: int
    talkgroup: int
    source: DmrActivitySource


@dataclass(frozen=True, slots=True)
class WpsdDmrHistoryRecord:
    """Normalized completed DMR activity returned by the WPSD JSON API."""

    identity: WpsdDmrHistoryIdentity
    name: str | None
    country: str | None
    callsign_suffix: str | None
    target: str
    duration_s: float
    packet_loss_percent: float

    @property
    def occurred_at(self) -> datetime:
        """Return the completed activity timestamp in UTC."""
        return self.identity.occurred_at

    @property
    def callsign(self) -> str:
        """Return the normalized base callsign."""
        return self.identity.callsign

    @property
    def slot(self) -> int:
        """Return the DMR timeslot."""
        return self.identity.slot

    @property
    def talkgroup(self) -> int:
        """Return the numeric DMR talkgroup."""
        return self.identity.talkgroup

    @property
    def source(self) -> DmrActivitySource:
        """Return whether the activity originated from network or RF."""
        return self.identity.source


@dataclass(frozen=True, slots=True)
class WpsdRadioInfo:
    """Hotspot RF configuration parsed from WPSD radioinfo.php."""

    status: str
    mode: str
    hotspot_tx_hz: int
    hotspot_rx_hz: int

    @property
    def radio_rx_hz(self) -> int:
        """Frequency on which the operator radio receives the hotspot."""
        return self.hotspot_tx_hz

    @property
    def radio_tx_hz(self) -> int:
        """Frequency on which the operator radio transmits to the hotspot."""
        return self.hotspot_rx_hz


def _clean_text(value: str) -> str:
    """Strip HTML and normalize whitespace from one WPSD table value."""
    without_tags = _HTML_TAG.sub(" ", value)
    return " ".join(html.unescape(without_tags).split())


def _optional_text(value: object) -> str | None:
    """Normalize an optional JSON string value."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise WpsdPayloadError("WPSD optional text field must be a string or null.")
    normalized = value.strip()
    return normalized or None


def _required_text(row: Mapping[object, object], key: str) -> str:
    """Return one required non-blank JSON string field."""
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise WpsdPayloadError(f"WPSD history row is missing required field {key!r}.")
    return value.strip()


def _parse_history_timestamp(value: str) -> datetime:
    """Parse the UTC timestamp emitted by the WPSD JSON API."""
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")  # noqa: DTZ007
    except ValueError as error:
        raise WpsdPayloadError(f"Invalid WPSD UTC timestamp: {value!r}.") from error
    return parsed.replace(tzinfo=UTC)


def _parse_source(value: str) -> DmrActivitySource:
    """Normalize WPSD source labels to the shared DMR activity source enum."""
    normalized = value.strip().lower()
    if normalized in {"net", "network"}:
        return DmrActivitySource.NETWORK
    if normalized == "rf":
        return DmrActivitySource.RF
    raise WpsdPayloadError(f"Unsupported WPSD DMR source: {value!r}.")


def _parse_percentage(value: str, field_name: str) -> float:
    """Parse WPSD percentage text such as ``0%``."""
    normalized = value.strip()
    if normalized.endswith("%"):
        normalized = normalized[:-1].strip()
    try:
        result = float(normalized)
    except ValueError as error:
        raise WpsdPayloadError(f"Invalid WPSD {field_name}: {value!r}.") from error
    if result < 0:
        raise WpsdPayloadError(f"WPSD {field_name} cannot be negative.")
    return result


def _parse_positive_float(value: str, field_name: str) -> float:
    """Parse a non-negative decimal number from WPSD text."""
    try:
        result = float(value.strip())
    except ValueError as error:
        raise WpsdPayloadError(f"Invalid WPSD {field_name}: {value!r}.") from error
    if result < 0:
        raise WpsdPayloadError(f"WPSD {field_name} cannot be negative.")
    return result


def parse_wpsd_dmr_history(payload: str | bytes) -> tuple[WpsdDmrHistoryRecord, ...]:
    """Parse DMR rows from WPSD's ``/api/?limit=...`` JSON response."""
    try:
        decoded: object = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise WpsdPayloadError("WPSD history response is not valid JSON.") from error

    if not isinstance(decoded, list):
        raise WpsdPayloadError("WPSD history response must be a JSON array.")

    records: list[WpsdDmrHistoryRecord] = []

    for raw_row in decoded:
        if not isinstance(raw_row, dict):
            raise WpsdPayloadError("WPSD history array contains a non-object row.")

        row: Mapping[object, object] = raw_row
        mode = _required_text(row, "mode")
        mode_match = _DMR_MODE.fullmatch(mode)
        if mode_match is None:
            continue

        target = _required_text(row, "target")
        target_match = _TALKGROUP.search(target)
        if target_match is None:
            raise WpsdPayloadError(f"DMR history target does not contain a talkgroup: {target!r}.")

        callsign = _required_text(row, "callsign").upper()
        source = _parse_source(_required_text(row, "src"))
        occurred_at = _parse_history_timestamp(_required_text(row, "time_utc"))
        duration_s = _parse_positive_float(_required_text(row, "duration"), "duration")
        packet_loss = _parse_percentage(_required_text(row, "loss"), "packet loss")

        name = _optional_text(row.get("name"))
        country = _optional_text(row.get("country"))
        callsign_suffix = _optional_text(row.get("callsign_suffix"))

        records.append(
            WpsdDmrHistoryRecord(
                identity=WpsdDmrHistoryIdentity(
                    occurred_at=occurred_at,
                    callsign=callsign,
                    slot=int(mode_match.group("slot")),
                    talkgroup=int(target_match.group("talkgroup")),
                    source=source,
                ),
                name=name,
                country=country,
                callsign_suffix=callsign_suffix,
                target=target,
                duration_s=duration_s,
                packet_loss_percent=packet_loss,
            )
        )

    return tuple(records)


def _parse_mhz_frequency(value: str) -> int:
    """Parse WPSD MHz text, including grouped ``434.537.500 MHz`` format."""
    match = _FREQUENCY_MHZ.search(value)
    if match is None:
        raise WpsdPayloadError(f"WPSD frequency is not recognizable: {value!r}.")

    numeric = match.group("value").replace(",", "")
    if numeric.count(".") >= 2:
        digits = numeric.replace(".", "")
        if not digits.isdigit():
            raise WpsdPayloadError(f"WPSD frequency is not recognizable: {value!r}.")
        result = int(digits)
    else:
        try:
            result = round(float(numeric) * 1_000_000)
        except ValueError as error:
            raise WpsdPayloadError(f"WPSD frequency is not recognizable: {value!r}.") from error

    if result <= 0:
        raise WpsdPayloadError("WPSD frequency must be positive.")
    return result


def parse_wpsd_radio_info(payload: str) -> WpsdRadioInfo:
    """Parse the RF pair and status from WPSD ``radioinfo.php`` HTML."""
    headers = [_clean_text(match.group("value")) for match in _HEADER_CELL.finditer(payload)]
    values = [_clean_text(match.group("value")) for match in _DATA_CELL.finditer(payload)]

    if not headers or len(headers) != len(values):
        raise WpsdPayloadError("WPSD radio info table shape is not recognizable.")

    fields = dict(zip(headers, values, strict=True))

    try:
        status = fields["Radio Status"]
        tx_text = fields["TX Freq."]
        rx_text = fields["RX Freq."]
        mode = fields["Radio Mode"]
    except KeyError as error:
        raise WpsdPayloadError(f"WPSD radio info is missing field {error.args[0]!r}.") from error

    if not status or not mode:
        raise WpsdPayloadError("WPSD radio status and radio mode must not be blank.")

    return WpsdRadioInfo(
        status=status,
        mode=mode,
        hotspot_tx_hz=_parse_mhz_frequency(tx_text),
        hotspot_rx_hz=_parse_mhz_frequency(rx_text),
    )
