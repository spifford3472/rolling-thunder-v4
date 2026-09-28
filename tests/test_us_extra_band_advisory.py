"""Tests for the US Amateur Extra Browse band advisory."""

import pytest

from rolling_thunder.domain import Frequency, RadioMode
from rolling_thunder.us_extra_band_advisory import (
    BandAdvisoryLevel,
    us_extra_band_advisory,
)


@pytest.mark.parametrize(
    ("frequency_hz", "mode"),
    [
        (3_500_000, RadioMode.CW),
        (3_950_000, RadioMode.CW),
        (7_250_000, RadioMode.CW),
        (10_125_000, RadioMode.CW),
        (14_250_000, RadioMode.CW),
        (18_150_000, RadioMode.CW),
        (21_300_000, RadioMode.CW),
        (24_950_000, RadioMode.CW),
        (29_100_000, RadioMode.CW),
        (53_000_000, RadioMode.CW),
    ],
)
def test_cw_is_valid_anywhere_inside_extra_allocation(
    frequency_hz: int,
    mode: RadioMode,
) -> None:
    advisory = us_extra_band_advisory(Frequency(hz=frequency_hz), mode)
    assert advisory.level is BandAdvisoryLevel.OK


@pytest.mark.parametrize(
    ("frequency_hz", "mode"),
    [
        (3_800_000, RadioMode.LSB),
        (7_200_000, RadioMode.LSB),
        (14_250_000, RadioMode.USB),
        (18_130_000, RadioMode.USB),
        (21_300_000, RadioMode.USB),
        (24_950_000, RadioMode.USB),
        (28_500_000, RadioMode.USB),
        (51_000_000, RadioMode.FM),
    ],
)
def test_phone_modes_are_valid_in_phone_segments(
    frequency_hz: int,
    mode: RadioMode,
) -> None:
    advisory = us_extra_band_advisory(Frequency(hz=frequency_hz), mode)
    assert advisory.level is BandAdvisoryLevel.OK


@pytest.mark.parametrize(
    ("frequency_hz", "mode"),
    [
        (3_550_000, RadioMode.LSB),
        (7_100_000, RadioMode.LSB),
        (10_125_000, RadioMode.USB),
        (14_100_000, RadioMode.USB),
        (18_090_000, RadioMode.USB),
        (21_100_000, RadioMode.USB),
        (24_910_000, RadioMode.USB),
        (28_100_000, RadioMode.USB),
        (50_050_000, RadioMode.FM),
    ],
)
def test_phone_modes_warn_in_non_phone_segments(
    frequency_hz: int,
    mode: RadioMode,
) -> None:
    advisory = us_extra_band_advisory(Frequency(hz=frequency_hz), mode)
    assert advisory.level is BandAdvisoryLevel.MODE_RESTRICTED


@pytest.mark.parametrize(
    "frequency_hz",
    [
        3_499_900,
        4_100_000,
        6_900_000,
        14_500_000,
        55_000_000,
    ],
)
def test_frequency_outside_supported_extra_bands_is_red_warning(
    frequency_hz: int,
) -> None:
    advisory = us_extra_band_advisory(
        Frequency(hz=frequency_hz),
        RadioMode.CW,
    )
    assert advisory.level is BandAdvisoryLevel.OUT_OF_BAND


def test_30_meters_accepts_data_but_not_phone() -> None:
    frequency = Frequency(hz=10_125_000)

    assert (
        us_extra_band_advisory(frequency, RadioMode.DATA).level
        is BandAdvisoryLevel.OK
    )
    assert (
        us_extra_band_advisory(frequency, RadioMode.USB).level
        is BandAdvisoryLevel.MODE_RESTRICTED
    )



def test_160_meters_is_part_of_extra_allocation() -> None:
    frequency = Frequency(hz=1_900_000)

    assert (
        us_extra_band_advisory(frequency, RadioMode.LSB).level
        is BandAdvisoryLevel.OK
    )


def test_current_60_meter_continuous_segment_accepts_usb_and_cw() -> None:
    frequency = Frequency(hz=5_357_000)

    assert (
        us_extra_band_advisory(frequency, RadioMode.USB).level
        is BandAdvisoryLevel.OK
    )
    assert (
        us_extra_band_advisory(frequency, RadioMode.CW).level
        is BandAdvisoryLevel.OK
    )


def test_current_60_meter_channel_distinguishes_carrier_and_cw_center() -> None:
    usb = us_extra_band_advisory(Frequency(hz=5_330_500), RadioMode.USB)
    cw = us_extra_band_advisory(Frequency(hz=5_332_000), RadioMode.CW)
    wrong_mode = us_extra_band_advisory(Frequency(hz=5_332_000), RadioMode.LSB)

    assert usb.level is BandAdvisoryLevel.OK
    assert cw.level is BandAdvisoryLevel.OK
    assert wrong_mode.level is BandAdvisoryLevel.MODE_RESTRICTED
