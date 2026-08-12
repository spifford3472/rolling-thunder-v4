"""Tests for FT-891 FM repeater CAT codecs."""

from decimal import Decimal

import pytest

from rolling_thunder.fm_repeater import CtcssBehavior, FmRepeaterShiftDirection
from rolling_thunder.ft891_cat import (
    Ft891CatError,
    Ft891OperatingContext,
    encode_read_6m_repeater_offset,
    encode_read_ctcss_behavior,
    encode_read_ctcss_tone,
    encode_read_information,
    encode_read_repeater_shift,
    encode_set_6m_repeater_offset,
    encode_set_ctcss_behavior,
    encode_set_ctcss_tone,
    encode_set_repeater_shift,
    parse_6m_repeater_offset_reply,
    parse_ctcss_behavior_reply,
    parse_ctcss_tone_reply,
    parse_operating_context_reply,
    parse_repeater_shift_reply,
)


def test_information_command_and_vfo_context_parse() -> None:
    reply = b"IF010052525000+000000400002;"

    assert encode_read_information() == b"IF;"
    assert parse_operating_context_reply(reply) is Ft891OperatingContext.VFO


def test_information_context_distinguishes_memory_and_memory_tune() -> None:
    memory = b"IF010052525000+000000410002;"
    memory_tune = b"IF010052525000+000000420002;"

    assert parse_operating_context_reply(memory) is Ft891OperatingContext.MEMORY
    assert parse_operating_context_reply(memory_tune) is Ft891OperatingContext.MEMORY_TUNE


@pytest.mark.parametrize(
    "reply",
    [b"", b"IF;", b"IF010052525000+000000400002", b"IF010052525000+00000X400002;"],
)
def test_information_parser_rejects_malformed_reply(reply: bytes) -> None:
    with pytest.raises(Ft891CatError, match="Malformed FT-891 information reply"):
        parse_operating_context_reply(reply)


@pytest.mark.parametrize(
    ("direction", "set_command", "reply"),
    [
        (FmRepeaterShiftDirection.SIMPLEX, b"OS00;", b"OS00;"),
        (FmRepeaterShiftDirection.PLUS, b"OS01;", b"OS01;"),
        (FmRepeaterShiftDirection.MINUS, b"OS02;", b"OS02;"),
    ],
)
def test_repeater_shift_commands_round_trip(
    direction: FmRepeaterShiftDirection,
    set_command: bytes,
    reply: bytes,
) -> None:
    assert encode_read_repeater_shift() == b"OS0;"
    assert encode_set_repeater_shift(direction) == set_command
    assert parse_repeater_shift_reply(reply) is direction


@pytest.mark.parametrize(
    ("offset_hz", "command", "reply"),
    [
        (0, b"EX09050000;", b"EX09050000;"),
        (1_000_000, b"EX09051000;", b"EX09051000;"),
        (4_000_000, b"EX09054000;", b"EX09054000;"),
    ],
)
def test_6m_repeater_offset_commands_round_trip(
    offset_hz: int,
    command: bytes,
    reply: bytes,
) -> None:
    assert encode_read_6m_repeater_offset() == b"EX0905;"
    assert encode_set_6m_repeater_offset(offset_hz) == command
    assert parse_6m_repeater_offset_reply(reply) == offset_hz


@pytest.mark.parametrize("offset_hz", [-10_000, 4_010_000])
def test_6m_repeater_offset_rejects_out_of_range(offset_hz: int) -> None:
    with pytest.raises(Ft891CatError, match="between 0 and 4,000,000"):
        encode_set_6m_repeater_offset(offset_hz)


def test_6m_repeater_offset_rejects_non_10khz_step() -> None:
    with pytest.raises(Ft891CatError, match="10,000 Hz steps"):
        encode_set_6m_repeater_offset(1_005_000)


@pytest.mark.parametrize(
    ("tone", "number"),
    [
        (Decimal("67.0"), 0),
        (Decimal("88.5"), 8),
        (Decimal("131.8"), 20),
        (Decimal("151.4"), 24),
        (Decimal("254.1"), 49),
    ],
)
def test_ctcss_tone_commands_use_official_tone_number_table(
    tone: Decimal,
    number: int,
) -> None:
    reply = f"CN00{number:03d};".encode("ascii")

    assert encode_read_ctcss_tone() == b"CN00;"
    assert encode_set_ctcss_tone(tone) == reply
    assert parse_ctcss_tone_reply(reply) == tone


def test_ctcss_tone_rejects_value_not_in_official_table() -> None:
    with pytest.raises(Ft891CatError, match="does not support CTCSS tone"):
        encode_set_ctcss_tone(Decimal("123.4"))


@pytest.mark.parametrize(
    ("behavior", "command"),
    [
        (CtcssBehavior.OFF, b"CT00;"),
        (CtcssBehavior.ENCODE_DECODE, b"CT01;"),
        (CtcssBehavior.ENCODE_ONLY, b"CT02;"),
    ],
)
def test_ctcss_behavior_commands_round_trip(
    behavior: CtcssBehavior,
    command: bytes,
) -> None:
    assert encode_read_ctcss_behavior() == b"CT0;"
    assert encode_set_ctcss_behavior(behavior) == command
    assert parse_ctcss_behavior_reply(command) is behavior


def test_ctcss_behavior_rejects_dcs_as_outside_ctcss_capability() -> None:
    with pytest.raises(Ft891CatError, match="reported DCS"):
        parse_ctcss_behavior_reply(b"CT03;")
