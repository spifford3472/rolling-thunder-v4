"""Tests for shared amateur-radio frequency-to-band resolution."""

import pytest

from rolling_thunder.domain import Frequency
from rolling_thunder.radio import RadioBand
from rolling_thunder.radio_band import (
    RadioBandResolutionError,
    resolve_radio_band,
)


@pytest.mark.parametrize(
    ("frequency_hz", "expected_band"),
    [
        (1_800_000, RadioBand.BAND_160M),
        (2_000_000, RadioBand.BAND_160M),
        (3_500_000, RadioBand.BAND_80M),
        (4_000_000, RadioBand.BAND_80M),
        (5_357_000, RadioBand.BAND_60M),
        (7_000_000, RadioBand.BAND_40M),
        (7_300_000, RadioBand.BAND_40M),
        (10_120_000, RadioBand.BAND_30M),
        (14_250_000, RadioBand.BAND_20M),
        (18_130_000, RadioBand.BAND_17M),
        (21_300_000, RadioBand.BAND_15M),
        (24_950_000, RadioBand.BAND_12M),
        (28_400_000, RadioBand.BAND_10M),
        (50_125_000, RadioBand.BAND_6M),
        (54_000_000, RadioBand.BAND_6M),
        (144_000_000, RadioBand.BAND_2M),
        (146_520_000, RadioBand.BAND_2M),
        (148_000_000, RadioBand.BAND_2M),
        (420_000_000, RadioBand.BAND_70CM),
        (439_537_500, RadioBand.BAND_70CM),
        (450_000_000, RadioBand.BAND_70CM),
    ],
)
def test_resolve_radio_band_maps_supported_frequencies(
    frequency_hz: int,
    expected_band: RadioBand,
) -> None:
    assert resolve_radio_band(Frequency(hz=frequency_hz)) is expected_band


@pytest.mark.parametrize(
    "frequency_hz",
    [
        500_000,
        2_500_000,
        7_500_000,
        12_000_000,
        30_000_000,
        54_100_000,
        148_100_000,
        450_100_000,
    ],
)
def test_resolve_radio_band_rejects_unsupported_frequencies(
    frequency_hz: int,
) -> None:
    with pytest.raises(
        RadioBandResolutionError,
        match="outside the supported amateur bands",
    ):
        resolve_radio_band(Frequency(hz=frequency_hz))


def test_resolve_radio_band_requires_frequency_value_object() -> None:
    with pytest.raises(TypeError, match="frequency must be a Frequency"):
        resolve_radio_band(14_250_000)  # type: ignore[arg-type]
