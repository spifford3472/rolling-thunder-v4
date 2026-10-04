"""Offline tests for live DX Summit IRC #CQDX parsing."""

from datetime import UTC, datetime

import pytest

from rolling_thunder.domain import RadioMode
from rolling_thunder.forge_dxsummit_irc_parser import (
    parse_dxsummit_irc_line,
    strip_irc_formatting,
)


RECEIVED_AT = datetime(2026, 10, 4, 1, 31, 40, tzinfo=UTC)
DXS_PREFIX = ":dxs!dxs@static.101.3.180.157.clients.your-server.de PRIVMSG #CQDX :"


def metadata(spot: object) -> dict[str, str]:
    """Return source metadata keyed for concise assertions."""
    return {item.key: item.value for item in spot.source_metadata}  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("payload", "callsign", "frequency_hz", "mode", "display_mode"),
    [
        (
            "AA4CS       14270.0 NX6T        USB                           0126",
            "NX6T",
            14_270_000,
            RadioMode.USB,
            "USB",
        ),
        (
            "AI4DB        7239.4 K6LA        LSB                           0127",
            "K6LA",
            7_239_400,
            RadioMode.LSB,
            "LSB",
        ),
        (
            "BH3AGU      14003.0 BD4WVQ      CW                            0128",
            "BD4WVQ",
            14_003_000,
            RadioMode.CW,
            "CW",
        ),
        (
            "IU6HWW      10137.7 N6MTX       FT8 -16 db                    0127",
            "N6MTX",
            10_137_700,
            RadioMode.DATA,
            "FT8",
        ),
        (
            "N1FS-@       7076.0 KE1VT       JT65 VT                       0127",
            "KE1VT",
            7_076_000,
            RadioMode.DATA,
            "JT65",
        ),
    ],
)
def test_live_dxs_lines_reuse_existing_dx_normalization(
    payload: str,
    callsign: str,
    frequency_hz: int,
    mode: RadioMode,
    display_mode: str,
) -> None:
    spot = parse_dxsummit_irc_line(
        DXS_PREFIX + "\x031,15" + payload,
        received_at=RECEIVED_AT,
    )

    assert spot is not None
    assert str(spot.callsign) == callsign
    assert spot.frequency.hz == frequency_hz
    assert spot.mode is mode
    assert spot.display_mode == display_mode
    assert metadata(spot)["source"] == "dxsummit_irc"
    assert metadata(spot)["spotter"] == payload.split()[0]


def test_live_grid_comment_preserves_provider_grid_and_comment() -> None:
    spot = parse_dxsummit_irc_line(
        DXS_PREFIX
        + "\x031,15KE4IHI       7059.0 9T0MD       "
        + "USB EM82du -> JI75ss          0129",
        received_at=RECEIVED_AT,
    )

    assert spot is not None
    assert str(spot.callsign) == "9T0MD"
    assert spot.grid == "JI75ss"
    assert metadata(spot)["comment"] == "USB EM82du -> JI75ss"


def test_missing_explicit_mode_uses_existing_frequency_fallback() -> None:
    spot = parse_dxsummit_irc_line(
        DXS_PREFIX
        + "\x031,15KI7GPT-@    28456.0 JH4UTP                                    0129",
        received_at=RECEIVED_AT,
    )

    assert spot is not None
    assert str(spot.callsign) == "JH4UTP"
    assert spot.mode is RadioMode.USB
    assert spot.display_mode == "USB"
    assert metadata(spot)["mode_source"] == "fallback"


@pytest.mark.parametrize(
    "line",
    [
        "PING :Newark.NJ.US.WorldIRC.Org",
        ":N4RJ!N4RJ@66.118.99.102 QUIT :Ping timeout",
        ":W4NDX!W4NDX@172.59.64.88 JOIN #CQDX",
        ":Newark.NJ.US.WorldIRC.Org 353 KI5VNB @ #CQDX :dxs KI5VNB",
        ":K1ABC!user@example PRIVMSG #CQDX :hello everyone",
        DXS_PREFIX + "not a spot",
        DXS_PREFIX + "\x031,15AA4CS 14270.0005 NX6T USB 0126",
        DXS_PREFIX + "\x031,15AA4CS 14270.0 NOT-A-CALL USB 0126",
        DXS_PREFIX + "\x031,15AA4CS 14270.0 NX6T USB 2460",
    ],
)
def test_protocol_chat_and_malformed_lines_are_ignored_safely(line: str) -> None:
    assert parse_dxsummit_irc_line(line, received_at=RECEIVED_AT) is None


def test_channel_and_robot_matching_are_case_insensitive() -> None:
    line = (
        ":DXS!dxs@example PRIVMSG #cqdx :"
        "\x031,15AA4CS       14270.0 NX6T        USB                           0126"
    )

    spot = parse_dxsummit_irc_line(line, received_at=RECEIVED_AT)

    assert spot is not None
    assert str(spot.callsign) == "NX6T"


def test_irc_color_and_style_controls_are_removed() -> None:
    assert (
        strip_irc_formatting("\x02\x031,15AA4CS\x0f 14270.0")
        == "AA4CS 14270.0"
    )
