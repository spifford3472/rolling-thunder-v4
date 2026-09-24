"""UI-independent parsing and tracking for MMDVMHost DMR activity."""

import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum

_LOG_PREFIX = re.compile(
    r"^M: (?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}) "
    r"DMR Slot (?P<slot>[12]), (?P<body>.+)$"
)
_VOICE_START = re.compile(
    r"^received (?P<source>network|RF) voice header from "
    r"(?P<callsign>[A-Z0-9/]+) to (?P<target>.+)$",
    re.IGNORECASE,
)
_VOICE_END = re.compile(
    r"^received (?P<source>network|RF) end of voice transmission from "
    r"(?P<callsign>[A-Z0-9/]+) to (?P<target>.+), "
    r"(?P<duration>\d+(?:\.\d+)?) seconds, "
    r"(?P<loss>\d+(?:\.\d+)?)% packet loss, "
    r"BER: (?P<ber>\d+(?:\.\d+)?)%$",
    re.IGNORECASE,
)
_TALKER_ALIAS = re.compile(r'^Talker Alias "(?P<alias>.*)"


class DmrActivitySource(StrEnum):
    """Where MMDVMHost received a DMR transmission."""

    NETWORK = "network"
    RF = "rf"


class DmrEventKind(StrEnum):
    """Supported MMDVMHost DMR event types."""

    VOICE_START = "voice_start"
    TALKER_ALIAS = "talker_alias"
    VOICE_END = "voice_end"


@dataclass(frozen=True, slots=True)
class DmrLogEvent:
    """One normalized DMR event parsed from an MMDVMHost log line."""

    kind: DmrEventKind
    occurred_at: datetime
    slot: int
    source: DmrActivitySource | None = None
    callsign: str | None = None
    target: str | None = None
    talker_alias: str | None = None
    duration_s: float | None = None
    packet_loss_percent: float | None = None
    ber_percent: float | None = None


@dataclass(frozen=True, slots=True)
class DmrCallIdentity:
    """Stable identity for one DMR voice transmission."""

    started_at: datetime
    slot: int
    source: DmrActivitySource
    callsign: str
    target: str


@dataclass(frozen=True, slots=True)
class DmrCallSnapshot:
    """Immutable state for one active or completed DMR voice transmission."""

    identity: DmrCallIdentity
    talker_alias: str | None = None
    ended_at: datetime | None = None
    duration_s: float | None = None
    packet_loss_percent: float | None = None
    ber_percent: float | None = None

    @property
    def active(self) -> bool:
        """Return whether the transmission has not yet emitted an end event."""
        return self.ended_at is None


def _parse_timestamp(value: str) -> datetime:
    """Parse MMDVMHost timestamps, which are emitted in UTC on WPSD."""
    parsed = datetime.strptime(value, "%Y-%m-%d %H:%M:%S.%f")  # noqa: DTZ007
    return parsed.replace(tzinfo=UTC)


def _parse_source(value: str) -> DmrActivitySource:
    normalized = value.strip().lower()
    if normalized == "network":
        return DmrActivitySource.NETWORK
    return DmrActivitySource.RF


def dmr_talkgroup_from_target(target: str) -> int | None:
    """Return a numeric group-call talkgroup from one MMDVM target label."""
    match = _TALKGROUP_TARGET.search(target.strip())
    if match is None:
        return None
    return int(match.group("talkgroup"))


def parse_mmdvm_dmr_line(line: str) -> DmrLogEvent | None:
    """Parse one supported DMR line from an MMDVMHost log."""
    prefix = _LOG_PREFIX.fullmatch(line.strip())
    if prefix is None:
        return None

    occurred_at = _parse_timestamp(prefix.group("timestamp"))
    slot = int(prefix.group("slot"))
    body = prefix.group("body")

    start = _VOICE_START.fullmatch(body)
    if start is not None:
        return DmrLogEvent(
            kind=DmrEventKind.VOICE_START,
            occurred_at=occurred_at,
            slot=slot,
            source=_parse_source(start.group("source")),
            callsign=start.group("callsign").upper(),
            target=start.group("target").strip(),
        )

    end = _VOICE_END.fullmatch(body)
    if end is not None:
        return DmrLogEvent(
            kind=DmrEventKind.VOICE_END,
            occurred_at=occurred_at,
            slot=slot,
            source=_parse_source(end.group("source")),
            callsign=end.group("callsign").upper(),
            target=end.group("target").strip(),
            duration_s=float(end.group("duration")),
            packet_loss_percent=float(end.group("loss")),
            ber_percent=float(end.group("ber")),
        )

    alias = _TALKER_ALIAS.fullmatch(body)
    if alias is not None:
        normalized_alias = alias.group("alias").strip()
        return DmrLogEvent(
            kind=DmrEventKind.TALKER_ALIAS,
            occurred_at=occurred_at,
            slot=slot,
            talker_alias=normalized_alias or None,
        )

    return None


class DmrLiveCallTracker:
    """Track active DMR calls by timeslot using explicit start/end events."""

    def __init__(self) -> None:
        self._active_by_slot: dict[int, DmrCallSnapshot] = {}

    def active_for_slot(self, slot: int) -> DmrCallSnapshot | None:
        """Return the current call for one timeslot, if any."""
        return self._active_by_slot.get(slot)

    @property
    def active_calls(self) -> tuple[DmrCallSnapshot, ...]:
        """Return current calls in deterministic timeslot order."""
        return tuple(self._active_by_slot[slot] for slot in sorted(self._active_by_slot))

    def apply(self, event: DmrLogEvent) -> DmrCallSnapshot | None:
        """Apply one parsed event and return the affected call snapshot."""
        if event.kind is DmrEventKind.VOICE_START:
            if event.source is None or event.callsign is None or event.target is None:
                return None

            snapshot = DmrCallSnapshot(
                identity=DmrCallIdentity(
                    started_at=event.occurred_at,
                    slot=event.slot,
                    source=event.source,
                    callsign=event.callsign,
                    target=event.target,
                )
            )
            self._active_by_slot[event.slot] = snapshot
            return snapshot

        active = self._active_by_slot.get(event.slot)
        if active is None:
            return None

        if event.kind is DmrEventKind.TALKER_ALIAS:
            updated = replace(active, talker_alias=event.talker_alias)
            self._active_by_slot[event.slot] = updated
            return updated

        if event.kind is DmrEventKind.VOICE_END:
            identity = active.identity
            if (
                event.source is not identity.source
                or event.callsign != identity.callsign
                or event.target != identity.target
            ):
                return None

            completed = replace(
                active,
                ended_at=event.occurred_at,
                duration_s=event.duration_s,
                packet_loss_percent=event.packet_loss_percent,
                ber_percent=event.ber_percent,
            )
            del self._active_by_slot[event.slot]
            return completed

        return None
)
_TALKGROUP_TARGET = re.compile(r"\bTG\s+(?P<talkgroup>\d+)\b", re.IGNORECASE)


class DmrActivitySource(StrEnum):
    """Where MMDVMHost received a DMR transmission."""

    NETWORK = "network"
    RF = "rf"


class DmrEventKind(StrEnum):
    """Supported MMDVMHost DMR event types."""

    VOICE_START = "voice_start"
    TALKER_ALIAS = "talker_alias"
    VOICE_END = "voice_end"


@dataclass(frozen=True, slots=True)
class DmrLogEvent:
    """One normalized DMR event parsed from an MMDVMHost log line."""

    kind: DmrEventKind
    occurred_at: datetime
    slot: int
    source: DmrActivitySource | None = None
    callsign: str | None = None
    target: str | None = None
    talker_alias: str | None = None
    duration_s: float | None = None
    packet_loss_percent: float | None = None
    ber_percent: float | None = None


@dataclass(frozen=True, slots=True)
class DmrCallIdentity:
    """Stable identity for one DMR voice transmission."""

    started_at: datetime
    slot: int
    source: DmrActivitySource
    callsign: str
    target: str


@dataclass(frozen=True, slots=True)
class DmrCallSnapshot:
    """Immutable state for one active or completed DMR voice transmission."""

    identity: DmrCallIdentity
    talker_alias: str | None = None
    ended_at: datetime | None = None
    duration_s: float | None = None
    packet_loss_percent: float | None = None
    ber_percent: float | None = None

    @property
    def active(self) -> bool:
        """Return whether the transmission has not yet emitted an end event."""
        return self.ended_at is None


def _parse_timestamp(value: str) -> datetime:
    """Parse MMDVMHost timestamps, which are emitted in UTC on WPSD."""
    parsed = datetime.strptime(value, "%Y-%m-%d %H:%M:%S.%f")  # noqa: DTZ007
    return parsed.replace(tzinfo=UTC)


def _parse_source(value: str) -> DmrActivitySource:
    normalized = value.strip().lower()
    if normalized == "network":
        return DmrActivitySource.NETWORK
    return DmrActivitySource.RF


def parse_mmdvm_dmr_line(line: str) -> DmrLogEvent | None:
    """Parse one supported DMR line from an MMDVMHost log."""
    prefix = _LOG_PREFIX.fullmatch(line.strip())
    if prefix is None:
        return None

    occurred_at = _parse_timestamp(prefix.group("timestamp"))
    slot = int(prefix.group("slot"))
    body = prefix.group("body")

    start = _VOICE_START.fullmatch(body)
    if start is not None:
        return DmrLogEvent(
            kind=DmrEventKind.VOICE_START,
            occurred_at=occurred_at,
            slot=slot,
            source=_parse_source(start.group("source")),
            callsign=start.group("callsign").upper(),
            target=start.group("target").strip(),
        )

    end = _VOICE_END.fullmatch(body)
    if end is not None:
        return DmrLogEvent(
            kind=DmrEventKind.VOICE_END,
            occurred_at=occurred_at,
            slot=slot,
            source=_parse_source(end.group("source")),
            callsign=end.group("callsign").upper(),
            target=end.group("target").strip(),
            duration_s=float(end.group("duration")),
            packet_loss_percent=float(end.group("loss")),
            ber_percent=float(end.group("ber")),
        )

    alias = _TALKER_ALIAS.fullmatch(body)
    if alias is not None:
        normalized_alias = alias.group("alias").strip()
        return DmrLogEvent(
            kind=DmrEventKind.TALKER_ALIAS,
            occurred_at=occurred_at,
            slot=slot,
            talker_alias=normalized_alias or None,
        )

    return None


class DmrLiveCallTracker:
    """Track active DMR calls by timeslot using explicit start/end events."""

    def __init__(self) -> None:
        self._active_by_slot: dict[int, DmrCallSnapshot] = {}

    def active_for_slot(self, slot: int) -> DmrCallSnapshot | None:
        """Return the current call for one timeslot, if any."""
        return self._active_by_slot.get(slot)

    @property
    def active_calls(self) -> tuple[DmrCallSnapshot, ...]:
        """Return current calls in deterministic timeslot order."""
        return tuple(self._active_by_slot[slot] for slot in sorted(self._active_by_slot))

    def apply(self, event: DmrLogEvent) -> DmrCallSnapshot | None:
        """Apply one parsed event and return the affected call snapshot."""
        if event.kind is DmrEventKind.VOICE_START:
            if event.source is None or event.callsign is None or event.target is None:
                return None

            snapshot = DmrCallSnapshot(
                identity=DmrCallIdentity(
                    started_at=event.occurred_at,
                    slot=event.slot,
                    source=event.source,
                    callsign=event.callsign,
                    target=event.target,
                )
            )
            self._active_by_slot[event.slot] = snapshot
            return snapshot

        active = self._active_by_slot.get(event.slot)
        if active is None:
            return None

        if event.kind is DmrEventKind.TALKER_ALIAS:
            updated = replace(active, talker_alias=event.talker_alias)
            self._active_by_slot[event.slot] = updated
            return updated

        if event.kind is DmrEventKind.VOICE_END:
            identity = active.identity
            if (
                event.source is not identity.source
                or event.callsign != identity.callsign
                or event.target != identity.target
            ):
                return None

            completed = replace(
                active,
                ended_at=event.occurred_at,
                duration_s=event.duration_s,
                packet_loss_percent=event.packet_loss_percent,
                ber_percent=event.ber_percent,
            )
            del self._active_by_slot[event.slot]
            return completed

        return None
