"""Tests for strict ESP32 physical-control event protocol parsing."""

import math

import pytest

from rolling_thunder.control_protocol import (
    ControlProtocolError,
    parse_control_event_line,
)


def test_valid_event_line_becomes_typed_input_event() -> None:
    event = parse_control_event_line(
        b"RTCTRL/1 EVENT discard-button boot42-000017 123.875\r\n"
    )

    assert event.input_id == "discard-button"
    assert event.event_id == "boot42-000017"
    assert event.occurred_at_s == 123.875


def test_event_identifiers_allow_protocol_safe_token_characters() -> None:
    event = parse_control_event_line(
        b"RTCTRL/1 EVENT panel.1_voice panel:1_evt_9 0\n"
    )

    assert event.input_id == "panel.1_voice"
    assert event.event_id == "panel:1_evt_9"
    assert event.occurred_at_s == 0.0


@pytest.mark.parametrize(
    ("raw_line", "message"),
    [
        (b"", "must not be empty"),
        (b"\r\n", "must not be blank"),
        (b"RTCTRL/2 EVENT voice-button evt-1 1.0\n", "Unsupported"),
        (b"RTCTRL/1 ACTION commit evt-1 1.0\n", "message type"),
        (b"RTCTRL/1 READY\n", "Expected"),
        (b"RTCTRL/1 EVENT voice-button evt-1\n", "Expected"),
        (b"RTCTRL/1 EVENT voice-button evt-1 1.0 extra\n", "Expected"),
        (b"RTCTRL/1  EVENT voice-button evt-1 1.0\n", "Expected"),
        (b"RTCTRL/1 EVENT voice button evt-1 1.0\n", "Expected"),
        (b"RTCTRL/1 EVENT voice/button evt-1 1.0\n", "input identifier"),
        (b"RTCTRL/1 EVENT voice-button evt/1 1.0\n", "event identifier"),
        (b"RTCTRL/1 EVENT voice-button evt-1 later\n", "not numeric"),
        (b"RTCTRL/1 EVENT voice-button evt-1 -0.1\n", "must not be negative"),
        (b"RTCTRL/1 EVENT voice-button evt-1 nan\n", "must be finite"),
        (b"RTCTRL/1 EVENT voice-button evt-1 inf\n", "must be finite"),
        (b"RTCTRL/1 EVENT voice-button\tevt-1 1.0\n", "control character"),
        (b"RTCTRL/1 EVENT voice-button evt-1 1.0\x00\n", "control character"),
        (b"RTCTRL/1 EVENT voice-button evt-1 1.0\xff\n", "ASCII only"),
    ],
)
def test_malformed_lines_fail_safely(raw_line: bytes, message: str) -> None:
    with pytest.raises(ControlProtocolError, match=message):
        parse_control_event_line(raw_line)


def test_oversized_line_is_rejected_before_decode() -> None:
    raw_line = b"RTCTRL/1 EVENT " + b"x" * 64 + b" evt-1 1.0\n"

    with pytest.raises(ControlProtocolError, match="32-byte limit"):
        parse_control_event_line(raw_line, maximum_line_bytes=32)


@pytest.mark.parametrize("maximum_line_bytes", [0, -1])
def test_nonpositive_maximum_line_length_is_rejected(
    maximum_line_bytes: int,
) -> None:
    with pytest.raises(ValueError, match="must be positive"):
        parse_control_event_line(
            b"RTCTRL/1 EVENT voice-button evt-1 1.0\n",
            maximum_line_bytes=maximum_line_bytes,
        )


def test_non_bytes_input_is_rejected() -> None:
    with pytest.raises(TypeError, match="must be bytes"):
        parse_control_event_line("RTCTRL/1 EVENT voice-button evt-1 1.0\n")  # type: ignore[arg-type]


def test_identifier_length_is_bounded() -> None:
    input_id = b"x" * 65
    raw_line = b"RTCTRL/1 EVENT " + input_id + b" evt-1 1.0\n"

    with pytest.raises(ControlProtocolError, match="input identifier"):
        parse_control_event_line(raw_line)


def test_negative_zero_is_accepted_as_nonnegative() -> None:
    event = parse_control_event_line(
        b"RTCTRL/1 EVENT voice-button evt-1 -0.0\n"
    )

    assert event.occurred_at_s == 0.0
    assert math.copysign(1.0, event.occurred_at_s) == -1.0
