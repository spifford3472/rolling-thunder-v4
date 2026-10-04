"""Read-only parsing for live DX Summit IRC #CQDX messages."""

from __future__ import annotations

from datetime import datetime
from re import IGNORECASE
from re import compile as compile_pattern

from rolling_thunder.forge_dx_spot_parser import DxSpotLineError, parse_dx_spot_line
from rolling_thunder.spot_domain import SpotRecord, SpotSourceMetadataItem

_IRC_MESSAGE_PATTERN = compile_pattern(
    r"^:(?P<prefix>\S+)\s+(?P<command>[A-Z]+)\s+(?P<target>\S+)\s+:(?P<body>.*)$",
    IGNORECASE,
)
_DX_SUMMIT_SPOT_PATTERN = compile_pattern(
    r"^\s*(?P<spotter>\S+)\s+"
    r"(?P<frequency>\d+(?:\.\d+)?)\s+"
    r"(?P<callsign>\S+)"
    r"(?:\s+(?P<comment>.*?))?"
    r"\s+(?P<hhmm>\d{4})\s*$",
)
_IRC_COLOR_PATTERN = compile_pattern(r"\x03(?:\d{1,2}(?:,\d{1,2})?)?")
_IRC_FORMAT_CONTROLS = str.maketrans("", "", "\x02\x0f\x16\x1d\x1f")
_DXS_NICK = "dxs"
_DX_CHANNEL = "#cqdx"


def parse_dxsummit_irc_line(
    line: str,
    *,
    received_at: datetime,
) -> SpotRecord | None:
    """Return one normalized DX spot from a live #CQDX line, or None.

    IRC protocol traffic, JOIN/PART/QUIT traffic, ordinary channel chat,
    announcements, malformed messages, and non-DXS PRIVMSG traffic are ignored
    safely. The parser is intentionally read-only and performs no network work.
    """
    message = _IRC_MESSAGE_PATTERN.fullmatch(line.rstrip("\r\n"))
    if message is None:
        return None

    if message.group("command").upper() != "PRIVMSG":
        return None
    if message.group("target").lower() != _DX_CHANNEL:
        return None

    nick = message.group("prefix").split("!", 1)[0].lower()
    if nick != _DXS_NICK:
        return None

    body = strip_irc_formatting(message.group("body"))
    spot_match = _DX_SUMMIT_SPOT_PATTERN.fullmatch(body)
    if spot_match is None:
        return None

    comment = " ".join((spot_match.group("comment") or "").split())
    dxspider_equivalent = (
        f"DX de {spot_match.group('spotter')}: "
        f"{spot_match.group('frequency')} "
        f"{spot_match.group('callsign')}"
    )
    if comment:
        dxspider_equivalent += f" {comment}"
    dxspider_equivalent += f" {spot_match.group('hhmm')}Z"

    try:
        spot = parse_dx_spot_line(
            dxspider_equivalent,
            fetched_at=received_at,
        )
    except DxSpotLineError:
        return None

    return SpotRecord(
        identity=spot.identity,
        callsign=spot.callsign,
        operator_name=spot.operator_name,
        grid=spot.grid,
        frequency=spot.frequency,
        mode=spot.mode,
        display_mode=spot.display_mode,
        spotted_at=spot.spotted_at,
        source_metadata=spot.source_metadata
        + (SpotSourceMetadataItem(key="source", value="dxsummit_irc"),),
        pota=spot.pota,
    )


def strip_irc_formatting(value: str) -> str:
    """Remove common mIRC color/style controls without changing spot text."""
    without_colors = _IRC_COLOR_PATTERN.sub("", value)
    return without_colors.translate(_IRC_FORMAT_CONTROLS)
