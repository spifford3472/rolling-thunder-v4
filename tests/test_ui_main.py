"""Tests for pure full-screen dashboard presentation helpers."""

from rolling_thunder.ui_main import (
    _BRIGHT,
    _WARNING,
    _ticker_presentation,
)


def test_normal_ticker_uses_routine_text_and_color() -> None:
    assert _ticker_presentation("RADIO CONNECTED", None) == (
        "RADIO CONNECTED",
        _BRIGHT,
    )


def test_atas_warning_overrides_routine_ticker_globally() -> None:
    warning = "BAND CHANGED TO 40 METERS — RETUNE ATAS-120"

    assert _ticker_presentation("RADIO CONNECTED", warning) == (
        warning,
        _WARNING,
    )
