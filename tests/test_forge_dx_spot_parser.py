"""Tests for deterministic DXSpider realtime spot parsing."""

from datetime import UTC, datetime

import pytest

from rolling_thunder.domain import Frequency, RadioMode
from rolling_thunder.forge_dx_spot_parser import (
    DxSpotLineError,
    is_dx_spot_line,
    parse_dx_frequency,
    parse_dx_spot_line,
    reconstruct_dx_timestamp,
    resolve_dx_mode,
)


def metadata(spot: object) -> dict[str, str]:
    """Return source metadata keyed for concise assertions."""
    return {item.key: item.value for item in spot.source_metadata}  # type: ignore[attr-defined]


def test_realtime_line_maps_to_complete_dx_record() -> None:
    fetched_at = datetime(2026, 8, 6, 2, 5, tzinfo=UTC)

    spot = parse_dx_spot_line(
        "DX de W1NT-#: 7002.5 WI3W CW 22dB **SEEME** FN20 0204Z",
        fetched_at=fetched_at,
    )

    assert spot.stable_key == "dx:WI3W:7002500"
    assert spot.callsign == "WI3W"
    assert spot.frequency.hz == 7_002_500
    assert spot.mode is RadioMode.CW
    assert spot.display_mode == "CW"
    assert spot.spotted_at == datetime(2026, 8, 6, 2, 4, tzinfo=UTC)
    assert spot.grid == "FN20"
    assert spot.operator_name is None
    assert spot.pota is None
    assert metadata(spot) == {
        "comment": "CW 22dB **SEEME** FN20",
        "mode_source": "explicit",
        "spotter": "W1NT-#",
    }


def test_decimal_kilohertz_conversion_is_exact() -> None:
    assert parse_dx_frequency("14074.025").hz == 14_074_025
    assert parse_dx_frequency("7002.5").hz == 7_002_500

    with pytest.raises(DxSpotLineError, match="integer hertz"):
        parse_dx_frequency("14074.0005")


@pytest.mark.parametrize(
    ("comment", "frequency_hz", "mode", "display"),
    [
        ("CQ FT8", 14_074_000, RadioMode.DATA, "FT8"),
        ("RTTY contest", 14_080_000, RadioMode.DATA, "RTTY"),
        ("PSK31", 14_070_000, RadioMode.DATA, "PSK31"),
        ("SSB contest", 7_200_000, RadioMode.LSB, "SSB"),
        ("SSB contest", 14_250_000, RadioMode.USB, "SSB"),
        ("USB net", 5_357_000, RadioMode.USB, "USB"),
    ],
)
def test_explicit_mode_tokens_take_precedence(
    comment: str,
    frequency_hz: int,
    mode: RadioMode,
    display: str,
) -> None:
    result = resolve_dx_mode(Frequency(hz=frequency_hz), comment)

    assert result.mode is mode
    assert result.display_mode == display
    assert result.source == "explicit"


@pytest.mark.parametrize(
    ("frequency_hz", "mode"),
    [
        (7_050_000, RadioMode.CW),
        (7_200_000, RadioMode.LSB),
        (10_120_000, RadioMode.CW),
        (10_136_000, RadioMode.DATA),
        (14_100_000, RadioMode.CW),
        (14_250_000, RadioMode.USB),
        (5_357_000, RadioMode.USB),
    ],
)
def test_fallback_mode_is_deterministic(frequency_hz: int, mode: RadioMode) -> None:
    result = resolve_dx_mode(Frequency(hz=frequency_hz), "strong signal")

    assert result.mode is mode
    assert result.display_mode == mode.value
    assert result.source == "fallback"


def test_midnight_rollover_uses_previous_utc_day() -> None:
    fetched_at = datetime(2026, 8, 6, 0, 2, tzinfo=UTC)

    timestamp = reconstruct_dx_timestamp("2359", fetched_at=fetched_at)

    assert timestamp == datetime(2026, 8, 5, 23, 59, tzinfo=UTC)


def test_small_future_skew_stays_on_fetch_date() -> None:
    fetched_at = datetime(2026, 8, 6, 12, 0, tzinfo=UTC)

    timestamp = reconstruct_dx_timestamp("1204", fetched_at=fetched_at)

    assert timestamp == datetime(2026, 8, 6, 12, 4, tzinfo=UTC)


def test_provider_grid_is_optional_and_normalized() -> None:
    spot = parse_dx_spot_line(
        "DX de K1ABC: 14250.0 W1AW SSB fn31pr 1234Z",
        fetched_at=datetime(2026, 8, 6, 12, 35, tzinfo=UTC),
    )

    assert spot.grid == "FN31pr"

    without_grid = parse_dx_spot_line(
        "DX de K1ABC: 14250.0 W1AW SSB strong 1234Z",
        fetched_at=datetime(2026, 8, 6, 12, 35, tzinfo=UTC),
    )
    assert without_grid.grid is None


def test_line_without_comment_uses_mode_fallback() -> None:
    spot = parse_dx_spot_line(
        "DX de K1ABC: 14250.0 W1AW 1234Z",
        fetched_at=datetime(2026, 8, 6, 12, 35, tzinfo=UTC),
    )

    assert spot.mode is RadioMode.USB
    assert spot.display_mode == "USB"
    assert metadata(spot) == {
        "mode_source": "fallback",
        "spotter": "K1ABC",
    }


def test_provider_comment_is_normalized_and_bounded() -> None:
    comment = "x" * 600
    spot = parse_dx_spot_line(
        f"DX de K1ABC: 14250.0 W1AW {comment} 1234Z",
        fetched_at=datetime(2026, 8, 6, 12, 35, tzinfo=UTC),
    )

    assert len(metadata(spot)["comment"]) == 500


@pytest.mark.parametrize(
    "line",
    [
        "Welcome to the cluster",
        "DX de K1ABC: 14074.0005 W1AW FT8 1234Z",
        "DX de K1ABC: 14250.0 NOT-A-CALL SSB 1234Z",
        "DX de K1ABC: 14250.0 W1AW SSB 2460Z",
        "DX de K1ABC 14250.0 W1AW SSB 1234Z",
    ],
)
def test_malformed_spot_like_lines_raise_typed_error(line: str) -> None:
    with pytest.raises(DxSpotLineError):
        parse_dx_spot_line(
            line,
            fetched_at=datetime(2026, 8, 6, 12, 35, tzinfo=UTC),
        )


def test_spot_line_detection_ignores_banner_text() -> None:
    assert is_dx_spot_line("  DX de K1ABC: 14250.0 W1AW SSB 1234Z") is True
    assert is_dx_spot_line("Welcome to DXSpider") is False
