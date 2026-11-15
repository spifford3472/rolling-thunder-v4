"""Tests for the FT-891 CAT command codec and transport boundary."""

import pytest

from rolling_thunder.cat_transport import CatTransport
from rolling_thunder.domain import Frequency, RadioMode
from rolling_thunder.ft891_cat import (
    Ft891CatError,
    Ft891SsbBfo,
    encode_memory_to_vfo_a,
    encode_read_frequency,
    encode_read_memory_channel,
    encode_read_mode,
    encode_read_narrow_enabled,
    encode_read_noise_blanker_enabled,
    encode_read_power,
    encode_read_preamp_enabled,
    encode_read_ssb_bfo,
    encode_select_band_memory,
    encode_set_frequency,
    encode_set_mode,
    encode_set_narrow_enabled,
    encode_set_noise_blanker_enabled,
    encode_set_power,
    encode_set_preamp_enabled,
    encode_set_ssb_bfo,
    memory_channel_for_band,
    parse_frequency_reply,
    parse_memory_channel_reply,
    parse_mode_reply,
    parse_narrow_enabled_reply,
    parse_noise_blanker_enabled_reply,
    parse_power_reply,
    parse_preamp_enabled_reply,
    parse_ssb_bfo_reply,
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


def test_ft8_receive_setting_commands_match_documented_ft891_format() -> None:
    assert encode_read_preamp_enabled() == b"PA0;"
    assert encode_set_preamp_enabled(True) == b"PA01;"
    assert encode_set_preamp_enabled(False) == b"PA00;"
    assert parse_preamp_enabled_reply(b"PA01;") is True
    assert parse_preamp_enabled_reply(b"PA00;") is False

    assert encode_read_narrow_enabled() == b"NA0;"
    assert encode_set_narrow_enabled(False) == b"NA00;"
    assert encode_set_narrow_enabled(True) == b"NA01;"
    assert parse_narrow_enabled_reply(b"NA00;") is False
    assert parse_narrow_enabled_reply(b"NA01;") is True

    assert encode_read_noise_blanker_enabled() == b"NB0;"
    assert encode_set_noise_blanker_enabled(False) == b"NB00;"
    assert encode_set_noise_blanker_enabled(True) == b"NB01;"
    assert parse_noise_blanker_enabled_reply(b"NB00;") is False
    assert parse_noise_blanker_enabled_reply(b"NB01;") is True


def test_power_commands_match_documented_ft891_format() -> None:
    assert encode_read_power() == b"PC;"
    assert encode_set_power(5) == b"PC005;"
    assert encode_set_power(20) == b"PC020;"
    assert encode_set_power(100) == b"PC100;"


@pytest.mark.parametrize("power_watts", [4, 101])
def test_power_set_rejects_out_of_range_values(power_watts: int) -> None:
    with pytest.raises(Ft891CatError, match="between 5 and 100 watts"):
        encode_set_power(power_watts)


def test_power_set_requires_integer() -> None:
    with pytest.raises(TypeError, match="power_watts must be an int"):
        encode_set_power(20.0)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("reply", "power_watts"),
    [(b"PC005;", 5), (b"PC020;", 20), (b"PC100;", 100)],
)
def test_power_reply_parses_documented_values(reply: bytes, power_watts: int) -> None:
    assert parse_power_reply(reply) == power_watts


@pytest.mark.parametrize("reply", [b"", b"PC;", b"PC20;", b"PC020", b"PX020;"])
def test_power_reply_rejects_malformed_data(reply: bytes) -> None:
    with pytest.raises(Ft891CatError, match="Malformed FT-891 power reply"):
        parse_power_reply(reply)


@pytest.mark.parametrize("reply", [b"PC000;", b"PC004;", b"PC101;", b"PC999;"])
def test_power_reply_rejects_out_of_range_values(reply: bytes) -> None:
    with pytest.raises(Ft891CatError, match="outside the documented range"):
        parse_power_reply(reply)


@pytest.mark.parametrize(
    ("value", "command", "reply"),
    [
        (Ft891SsbBfo.USB, b"EX11070;", b"EX11070;"),
        (Ft891SsbBfo.LSB, b"EX11071;", b"EX11071;"),
        (Ft891SsbBfo.AUTO, b"EX11072;", b"EX11072;"),
    ],
)
def test_ssb_bfo_commands_match_documented_ex_menu_format(
    value: Ft891SsbBfo,
    command: bytes,
    reply: bytes,
) -> None:
    assert encode_read_ssb_bfo() == b"EX1107;"
    assert encode_set_ssb_bfo(value) == command
    assert parse_ssb_bfo_reply(reply) is value


def test_ssb_bfo_set_requires_typed_value() -> None:
    with pytest.raises(TypeError, match="Ft891SsbBfo"):
        encode_set_ssb_bfo("usb")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "reply",
    [b"", b"EX1107;", b"EX11073;", b"EX110700;", b"EX11070", b"EX011070;"],
)
def test_ssb_bfo_reply_rejects_malformed_data(reply: bytes) -> None:
    with pytest.raises(Ft891CatError, match="Malformed FT-891 SSB-BFO reply"):
        parse_ssb_bfo_reply(reply)


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


@pytest.mark.parametrize("value, digit", [("mic", b"0"), ("rear", b"1")])
def test_ssb_mic_select_cat_commands_and_replies(value: str, digit: bytes) -> None:
    from rolling_thunder.ft891_cat import (
        Ft891SsbMicSelect,
        encode_read_ssb_mic_select,
        encode_set_ssb_mic_select,
        parse_ssb_mic_select_reply,
    )

    typed = Ft891SsbMicSelect(value)
    assert encode_read_ssb_mic_select() == b"EX1105;"
    assert encode_set_ssb_mic_select(typed) == b"EX1105" + digit + b";"
    assert parse_ssb_mic_select_reply(b"EX1105" + digit + b";") is typed


@pytest.mark.parametrize(
    "reply",
    [b"", b"EX1105;", b"EX11052;", b"EX110500;", b"EX11050", b"EX11070;", b"EX11050;EX11051;"],
)
def test_ssb_mic_select_rejects_malformed_reply(reply: bytes) -> None:
    from rolling_thunder.ft891_cat import parse_ssb_mic_select_reply

    with pytest.raises(Ft891CatError):
        parse_ssb_mic_select_reply(reply)


@pytest.mark.parametrize("value", ["mic", 0, 1, None, True, Ft891SsbBfo.USB])
def test_ssb_mic_select_rejects_untyped_value(value: object) -> None:
    from rolling_thunder.ft891_cat import encode_set_ssb_mic_select

    with pytest.raises(TypeError):
        encode_set_ssb_mic_select(value)  # type: ignore[arg-type]


def test_ssb_mic_select_reply_requires_bytes() -> None:
    from rolling_thunder.ft891_cat import parse_ssb_mic_select_reply

    with pytest.raises(TypeError):
        parse_ssb_mic_select_reply("EX11050;")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("reply", "expected"),
    [(b"TX0;", "both_off"), (b"TX1;", "cat_on"), (b"TX2;", "radio_on")],
)
def test_readonly_tx_status_round_trip(reply: bytes, expected: str) -> None:
    """FT-891 readback is decoded without issuing a write/key command."""
    from rolling_thunder.ft891_cat import (
        encode_read_tx_readback,
        parse_tx_readback,
    )

    transport = FakeCatTransport()
    transport.open()
    transport.replies[b"TX;"] = reply
    assert parse_tx_readback(transport.query(encode_read_tx_readback())) == expected
    assert transport.commands == [b"TX;"]


@pytest.mark.parametrize(
    "invalid",
    [b"", b"TX;", b"TX3;", b"TX0", b"TX0;;", b"tx0;", b"TX0;TX1;"],
)
def test_tx_status_invalid_or_ambiguous_reply_fails_closed(invalid: bytes) -> None:
    """Never infer RX status from an unknown or partial CAT response."""
    from rolling_thunder.ft891_cat import parse_tx_readback

    with pytest.raises(Ft891CatError, match="Malformed FT-891 TX status"):
        parse_tx_readback(invalid)


def test_tx_status_nonbytes_rejected() -> None:
    """CAT codec does not coerce untrusted object data into valid telemetry."""
    from rolling_thunder.ft891_cat import parse_tx_readback

    with pytest.raises(TypeError, match="bytes"):
        parse_tx_readback("TX0;")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("selector", "expected_command", "answer", "expected_enabled"),
    [
        ("A", b"RIA;", b"RIA0;", False),
        ("A", b"RIA;", b"RIA1;", True),
        ("B", b"RIB;", b"RIB0;", False),
        ("B", b"RIB;", b"RIB1;", True),
    ],
)
def test_readonly_radio_led_reports(
    selector: str, expected_command: bytes, answer: bytes, expected_enabled: bool
) -> None:
    """RI A/B indicators are read-only firmware telemetry, not RF sensors."""
    from rolling_thunder.ft891_cat import (
        encode_read_rx_led,
        encode_read_tx_led,
        parse_radio_led_reply,
    )

    query = encode_read_tx_led() if selector == "A" else encode_read_rx_led()
    assert query == expected_command
    assert parse_radio_led_reply(answer, indicator=selector) is expected_enabled


@pytest.mark.parametrize(
    ("indicator", "reply"),
    [("A", b"RIB0;"), ("B", b"RIA1;"), ("A", b"RIA2;"),
     ("B", b"RIB;"), ("A", b"RIA0;RIB1;"), ("A", b"ria0;")],
)
def test_radio_led_bad_or_crossed_responses_fail_closed(
    indicator: str, reply: bytes
) -> None:
    """Crossed TX/RX replies must never be misclassified as receive."""
    from rolling_thunder.ft891_cat import parse_radio_led_reply

    with pytest.raises(Ft891CatError, match="Malformed or mismatched"):
        parse_radio_led_reply(reply, indicator=indicator)


def test_radio_led_rejects_invalid_selector_and_type() -> None:
    """The protocol parser supports only documented TX/RX LED reads."""
    from rolling_thunder.ft891_cat import parse_radio_led_reply

    with pytest.raises(ValueError, match="indicator"):
        parse_radio_led_reply(b"RIA0;", indicator="0")
    with pytest.raises(TypeError, match="bytes"):
        parse_radio_led_reply("RIA0;", indicator="A")  # type: ignore[arg-type]


def test_readonly_receive_codec_does_not_grant_transmit_authority() -> None:
    """Parsing all three nominal receive reports leaves live alarm inhibited."""
    from rolling_thunder.ft8.ptt_alarm import FT8PttAlarm
    from rolling_thunder.ft891_cat import parse_radio_led_reply, parse_tx_readback
    from rolling_thunder.physical_controls import ControlAction as A

    assert parse_tx_readback(b"TX0;").value == "both_off"
    assert not parse_radio_led_reply(b"RIA0;", indicator="A")
    assert parse_radio_led_reply(b"RIB1;", indicator="B")
    alarm = FT8PttAlarm()
    alarm.trigger()
    alarm.voice_cancel()
    for action in (A.PANEL_PRIMARY, A.PANEL_TERTIARY, A.PANEL_PRIMARY):
        assert not alarm.unlock_step(action, ft8_screen=True,
                                     radio_confirmed_receive=False)
    assert alarm.tx_inhibited
