"""Strict bounded RTCTRL/2 frames, separate from the legacy event parser."""

from __future__ import annotations

import re
from dataclasses import dataclass

from rolling_thunder.control_protocol import ControlProtocolError


@dataclass(frozen=True)
class Ready:
    """Fresh host-challenged firmware session observation."""

    nonce: str
    boot: str
    firmware: str
    sequence: int
    uptime_ms: int


@dataclass(frozen=True)
class Pong:
    """Response to one specific host health request."""

    nonce: str
    boot: str
    request_id: int
    sequence: int
    uptime_ms: int


@dataclass(frozen=True)
class Event:
    """Physical input; freshness and sequencing still require session validation."""

    nonce: str
    boot: str
    sequence: int
    uptime_ms: int
    input_id: str


def _uint(text: str) -> int:
    if re.fullmatch(r"0|[1-9][0-9]{0,19}", text) is None or int(text) > 2**64 - 1:
        raise ControlProtocolError("Expected canonical unsigned 64-bit integer")
    return int(text)


def parse_v2_line(raw: bytes) -> Ready | Pong | Event:
    """Require one complete ASCII line with exact fields and bounded values."""
    if not isinstance(raw, bytes):
        raise TypeError("Control protocol input must be bytes")
    if not raw or len(raw) > 256 or not raw.endswith(b"\n"):
        raise ControlProtocolError("Expected a complete controller line of at most256bytes")
    try:
        line = raw[:-1].removesuffix(b"\r").decode("ascii")
    except UnicodeDecodeError as error:
        raise ControlProtocolError("Controller line must be ASCII") from error
    if any(ord(c) < 32 or ord(c) == 127 for c in line):
        raise ControlProtocolError("Embedded controller control character")
    fields = line.split(" ")
    if len(fields) != 7 or any(not f for f in fields) or fields[0] != "RTCTRL/2":
        raise ControlProtocolError("Unexpected controller version/field count")
    _, kind, nonce, boot, a, b, c = fields
    if re.fullmatch(r"[0-9a-f]{32}", nonce) is None or re.fullmatch(r"[0-9a-f]{16}", boot) is None:
        raise ControlProtocolError("Invalid controller session/boot identity")
    if kind == "PONG":
        return Pong(nonce, boot, _uint(a), _uint(b), _uint(c))
    token = a if kind == "READY" else c
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,63}", token) is None:
        raise ControlProtocolError("Invalid controller token")
    if kind == "READY":
        return Ready(nonce, boot, a, _uint(b), _uint(c))
    if kind == "EVENT":
        return Event(nonce, boot, _uint(a), _uint(b), c)
    raise ControlProtocolError("Unsupported controller message type")
