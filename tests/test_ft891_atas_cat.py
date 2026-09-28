"""Tests for FT-891 CAT commands used only by the isolated ATAS probe."""

import pytest

from rolling_thunder.ft891_cat import (
    Ft891CatError,
    encode_cat_ptt_off,
    encode_cat_ptt_on,
    encode_force_receive,
    encode_mic_down,
    encode_mic_up,
    encode_read_power_meter,
    encode_read_swr_meter,
    encode_read_tx_state,
    parse_meter_reply,
    parse_tx_state_reply,
)


def test_atas_probe_commands_match_ft891_cat_reference() -> None:
    assert encode_read_tx_state() == b"TX;"
    assert encode_cat_ptt_on() == b"TX1;"
    assert encode_cat_ptt_off() == b"TX0;"
    assert encode_force_receive() == b"RX;"
    assert encode_mic_up() == b"UP;"
    assert encode_mic_down() == b"DN;"
    assert encode_read_swr_meter() == b"RM6;"
    assert encode_read_power_meter() == b"RM5;"


@pytest.mark.parametrize(("reply", "state"), [(b"TX0;", 0), (b"TX1;", 1), (b"TX2;", 2)])
def test_tx_state_reply_parses_documented_states(reply: bytes, state: int) -> None:
    assert parse_tx_state_reply(reply) == state


@pytest.mark.parametrize("reply", [b"", b"TX;", b"TX3;", b"TX1", b" RX0;"])
def test_tx_state_reply_rejects_malformed_values(reply: bytes) -> None:
    with pytest.raises(Ft891CatError, match="Malformed FT-891 TX-state"):
        parse_tx_state_reply(reply)


def test_meter_reply_parses_raw_0_to_255_value() -> None:
    assert parse_meter_reply(b"RM6000;", expected_meter=6) == 0
    assert parse_meter_reply(b"RM6255;", expected_meter=6) == 255
    assert parse_meter_reply(b"RM5128;", expected_meter=5) == 128


def test_meter_reply_rejects_wrong_selector() -> None:
    with pytest.raises(Ft891CatError, match="Unexpected FT-891 meter reply selector"):
        parse_meter_reply(b"RM5128;", expected_meter=6)


@pytest.mark.parametrize("reply", [b"", b"RM6;", b"RM6256;", b"RM699;", b"RM6000"])
def test_meter_reply_rejects_malformed_values(reply: bytes) -> None:
    with pytest.raises(Ft891CatError, match="Malformed FT-891 meter reply"):
        parse_meter_reply(reply, expected_meter=6)
