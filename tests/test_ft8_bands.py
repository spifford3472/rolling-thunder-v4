"""Tests for centralized FT8 dial-frequency and automated band policy."""

import pytest

from rolling_thunder.domain import Frequency
from rolling_thunder.ft8.bands import (
    FT8_AUTOMATED_BAND_ORDER,
    ft8_frequency_for_band,
    next_automated_ft8_band,
)
from rolling_thunder.radio import RadioBand


@pytest.mark.parametrize(
    ("band", "frequency_hz"),
    [
        (RadioBand.BAND_160M, 1_840_000),
        (RadioBand.BAND_80M, 3_573_000),
        (RadioBand.BAND_60M, 5_357_000),
        (RadioBand.BAND_40M, 7_074_000),
        (RadioBand.BAND_30M, 10_136_000),
        (RadioBand.BAND_20M, 14_074_000),
        (RadioBand.BAND_17M, 18_100_000),
        (RadioBand.BAND_15M, 21_074_000),
        (RadioBand.BAND_12M, 24_915_000),
        (RadioBand.BAND_10M, 28_074_000),
        (RadioBand.BAND_6M, 50_313_000),
    ],
)
def test_ft8_frequency_plan_uses_integer_hz(
    band: RadioBand,
    frequency_hz: int,
) -> None:
    assert ft8_frequency_for_band(band) == Frequency(hz=frequency_hz)


def test_60m_is_in_plan_but_not_automated_cross_band_cycle() -> None:
    assert ft8_frequency_for_band(RadioBand.BAND_60M) == Frequency(hz=5_357_000)
    assert RadioBand.BAND_60M not in FT8_AUTOMATED_BAND_ORDER


def test_unknown_current_band_defaults_cycle_to_20m() -> None:
    assert next_automated_ft8_band(None) is RadioBand.BAND_20M
    assert next_automated_ft8_band(RadioBand.BAND_60M) is RadioBand.BAND_20M


def test_automated_band_cycle_wraps() -> None:
    assert next_automated_ft8_band(RadioBand.BAND_20M) is RadioBand.BAND_17M
    assert next_automated_ft8_band(RadioBand.BAND_6M) is RadioBand.BAND_160M
