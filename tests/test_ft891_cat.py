"""Tests for the FT-891 CAT command codec and transport boundary."""

import pytest

from rolling_thunder.cat_transport import CatTransport
from rolling_thunder.domain import Frequency, RadioMode
from rolling_thunder.ft891_cat import (
    Ft891CatError,
    encode_memory_to_vfo_a,
    encode_read_frequency,
    encode_read_memory_channel,
    encode_read_mode,
    encode_select_band_memory,
    encode_set_frequency,
    encode_set_mode,
    memory_channel_for_band,
    parse_frequency_reply,
    parse_memory_channel_reply,
    parse_mode_reply,
)
from rolling_thunder.radio import RadioBand


class FakeCatTransport:
    """Minimal deterministic transport used to verify protocol compatibility."""

    def __init__(self) -> None:
        self.opened = False
        self.commands: list[bytes] = []
        self.replies: dict[bytes, bytes] = {}

    def open(self) -> None:
        self.opened = True

    def close(self) -> None:
        self.opened = False

    def query(self, command: bytes) -> bytes:
        self.commands.append(command)
        return self.replies[command]

    def command(self, command: bytes) -> None:
        self.commands.append(command)


def test_fake_transport_satisfies_cat_transport_protocol() -> None:
    transport = FakeCatTransport()

    assert isinstance(transport, CatTransport)


@pytest.mark.parametrize(
    ("band", "memory", "command"),
    [
        (RadioBand.BAND_160M, 1, b"MC001;"),
        (RadioBand.BAND_80M, 2, b"MC002;"),
        (RadioBand.BAND_40M, 3, b"MC003;"),
        (RadioBand.BAND_30M, 4, b"MC004;"),
        (RadioBand.BAND_20M, 5, b"MC005;"),
        (RadioBand.BAND_17M, 6, b"MC006;"),
        (RadioBand.BAND_15M, 7, b"MC007;"),
        (RadioBand.BAND_12M, 8, b"MC008;"),
        (RadioBand.BAND_10M, 9, b"MC009;"),
        (RadioBand.BAND_6M, 10, b"MC010;"),
    ],
)
def test_band_memories_use_operator_mapping(
    band: RadioBand,
    memory: int,
    command: bytes,
) -> None:
    assert memory_channel_for_band(band) == memory
    assert encode_select_band_memory(band) == command


def test_band_memory_selection_rejects_unsupported_60m_without_guessing() -> None:
    with pytest.raises(
        Ft891CatError,
        match="memory band selection does not support 60m",
    ):
        encode_select_band_memory(RadioBand.BAND_60M)


def test_band_memory_selection_requires_radio_band_value() -> None:
    with pytest.raises(TypeError, match="band must be a RadioBand"):
        encode_select_band_memory("40m")  # type: ignore[arg-type]


def test_memory_commands_match_verified_ft891_sequence() -> None:
    assert encode_read_memory_channel() == b"MC;"
    assert encode_memory_to_vfo_a() == b"MA;"


@pytest.mark.parametrize(
    ("reply", "channel"),
    [
        (b"MC001;", 1),
        (b"MC005;", 5),
        (b"MC010;", 10),
        (b"MC099;", 99),
    ],
)
def test_memory_channel_reply_parses_selected_channel(
    reply: bytes,
    channel: int,
) -> None:
    assert parse_memory_channel_reply(reply) == channel


@pytest.mark.parametrize(
    "reply",
    [b"", b"MC;", b"MC01;", b"MC0001;", b"MCABC;", b"MC010"],
)
def test_memory_channel_reply_rejects_malformed_data(reply: bytes) -> None:
    with pytest.raises(Ft891CatError, match="Malformed FT-891 memory-channel reply"):
        parse_memory_channel_reply(reply)


def test_memory_channel_reply_rejects_channel_zero() -> None:
    with pytest.raises(Ft891CatError, match="outside the supported range"):
        parse_memory_channel_reply(b"MC000;")


def test_frequency_read_and_set_commands_match_ft891_format() -> None:
    assert encode_read_frequency() == b"FA;"
    assert encode_set_frequency(Frequency(hz=14_250_000)) == b"FA014250000;"
    assert encode_set_frequency(Frequency(hz=30_000)) == b"FA000030000;"
    assert encode_set_frequency(Frequency(hz=56_000_000)) == b"FA056000000;"


@pytest.mark.parametrize("frequency_hz", [29_999, 56_000_001])
def test_frequency_set_rejects_values_outside_ft891_cat_range(
    frequency_hz: int,
) -> None:
    with pytest.raises(Ft891CatError, match="between 30,000 and 56,000,000"):
        encode_set_frequency(Frequency(hz=frequency_hz))


def test_frequency_reply_parses_integer_hertz() -> None:
    assert parse_frequency_reply(b"FA014250000;") == Frequency(hz=14_250_000)


@pytest.mark.parametrize(
    "reply",
    [
        b"",
        b"FA;",
        b"FA14250000;",
        b"FB014250000;",
        b"FA014250000",
        b"FA01425X000;",
        b" FA014250000;",
    ],
)
def test_frequency_reply_rejects_malformed_or_incomplete_data(reply: bytes) -> None:
    with pytest.raises(Ft891CatError, match="Malformed FT-891 frequency reply"):
        parse_frequency_reply(reply)


@pytest.mark.parametrize("reply", [b"FA000000000;", b"FA056000001;"])
def test_frequency_reply_rejects_out_of_range_data(reply: bytes) -> None:
    with pytest.raises(Ft891CatError, match="outside the supported range"):
        parse_frequency_reply(reply)


def test_mode_read_command_targets_main_receiver() -> None:
    assert encode_read_mode() == b"MD0;"


@pytest.mark.parametrize(
    ("mode", "command"),
    [
        (RadioMode.LSB, b"MD01;"),
        (RadioMode.USB, b"MD02;"),
        (RadioMode.CW, b"MD03;"),
        (RadioMode.FM, b"MD04;"),
        (RadioMode.AM, b"MD05;"),
        (RadioMode.DATA, b"MD0C;"),
    ],
)
def test_mode_set_commands_use_supported_ft891_codes(
    mode: RadioMode,
    command: bytes,
) -> None:
    assert encode_set_mode(mode) == command


@pytest.mark.parametrize(
    ("reply", "mode"),
    [
        (b"MD01;", RadioMode.LSB),
        (b"MD02;", RadioMode.USB),
        (b"MD03;", RadioMode.CW),
        (b"MD04;", RadioMode.FM),
        (b"MD05;", RadioMode.AM),
        (b"MD07;", RadioMode.CW),
        (b"MD08;", RadioMode.DATA),
        (b"MD0B;", RadioMode.FM),
        (b"MD0C;", RadioMode.DATA),
        (b"MD0D;", RadioMode.AM),
    ],
)
def test_mode_reply_maps_ft891_variants_to_domain_modes(
    reply: bytes,
    mode: RadioMode,
) -> None:
    assert parse_mode_reply(reply) is mode


@pytest.mark.parametrize("reply", [b"", b"MD0;", b"MD1;", b"MD01", b"MD0Z;"])
def test_mode_reply_rejects_malformed_data(reply: bytes) -> None:
    with pytest.raises(Ft891CatError, match="Malformed FT-891 mode reply"):
        parse_mode_reply(reply)


@pytest.mark.parametrize("reply", [b"MD00;", b"MD06;", b"MD09;", b"MD0A;"])
def test_mode_reply_rejects_unsupported_modes(reply: bytes) -> None:
    with pytest.raises(Ft891CatError, match="Unsupported FT-891 operating mode code"):
        parse_mode_reply(reply)


def test_fake_transport_records_safe_read_and_set_commands() -> None:
    transport = FakeCatTransport()
    transport.replies[encode_read_frequency()] = b"FA007200000;"

    transport.open()
    reply = transport.query(encode_read_frequency())
    transport.command(encode_set_mode(RadioMode.LSB))
    transport.close()

    assert parse_frequency_reply(reply) == Frequency(hz=7_200_000)
    assert transport.commands == [b"FA;", b"MD01;"]
    assert transport.opened is False
