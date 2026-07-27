"""Strict parser for versioned ESP32 physical-control event messages."""

from __future__ import annotations

import math
import re

from rolling_thunder.physical_controls import ControlInputEvent

_PROTOCOL_VERSION = "RTCTRL/1"
_EVENT_MESSAGE = "EVENT"
_DEFAULT_MAXIMUM_LINE_BYTES = 256
_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,63}\Z")


class ControlProtocolError(ValueError):
    """Raised when a physical-control transport message is invalid."""


def parse_control_event_line(
    raw_line: bytes,
    *,
    maximum_line_bytes: int = _DEFAULT_MAXIMUM_LINE_BYTES,
) -> ControlInputEvent:
    """Parse one complete RTCTRL/1 EVENT line into a typed input event."""
    if maximum_line_bytes < 1:
        raise ValueError("Control maximum_line_bytes must be positive.")
    if not isinstance(raw_line, bytes):
        raise TypeError("Control protocol input must be bytes.")
    if not raw_line:
        raise ControlProtocolError("Control protocol line must not be empty.")
    if len(raw_line) > maximum_line_bytes:
        raise ControlProtocolError(
            "Control protocol line exceeded "
            f"the {maximum_line_bytes}-byte limit."
        )

    try:
        line = raw_line.decode("ascii")
    except UnicodeDecodeError as error:
        raise ControlProtocolError("Control protocol line must contain ASCII only.") from error

    line = line.removesuffix("\n").removesuffix("\r")
    if not line:
        raise ControlProtocolError("Control protocol line must not be blank.")
    if any(ord(character) < 32 or ord(character) == 127 for character in line):
        raise ControlProtocolError(
            "Control protocol line contains an embedded control character."
        )

    fields = line.split(" ")
    if len(fields) != 5 or any(not field for field in fields):
        raise ControlProtocolError(
            "Expected 'RTCTRL/1 EVENT <input-id> <event-id> <seconds>'."
        )

    version, message_type, input_id, event_id, occurred_at_text = fields
    if version != _PROTOCOL_VERSION:
        raise ControlProtocolError(
            f"Unsupported control protocol version {version!r}; expected {_PROTOCOL_VERSION}."
        )
    if message_type != _EVENT_MESSAGE:
        raise ControlProtocolError(
            f"Unsupported control message type {message_type!r}; expected EVENT."
        )

    _validate_identifier(input_id, label="input identifier")
    _validate_identifier(event_id, label="event identifier")

    try:
        occurred_at_s = float(occurred_at_text)
    except ValueError as error:
        raise ControlProtocolError(
            f"Control event timestamp {occurred_at_text!r} is not numeric."
        ) from error
    if not math.isfinite(occurred_at_s):
        raise ControlProtocolError("Control event timestamp must be finite.")
    if occurred_at_s < 0:
        raise ControlProtocolError("Control event timestamp must not be negative.")

    return ControlInputEvent(
        input_id=input_id,
        event_id=event_id,
        occurred_at_s=occurred_at_s,
    )


def _validate_identifier(value: str, *, label: str) -> None:
    if _IDENTIFIER_PATTERN.fullmatch(value) is None:
        raise ControlProtocolError(
            f"Control {label} {value!r} must be 1-64 ASCII token characters "
            "using letters, digits, '.', '_', ':', or '-'."
        )
