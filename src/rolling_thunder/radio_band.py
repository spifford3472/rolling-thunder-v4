"""Resolve operating frequencies to supported amateur-radio bands."""

from typing import Final

from rolling_thunder.domain import Frequency
from rolling_thunder.radio import RadioBand, RadioError


class RadioBandResolutionError(RadioError):
    """Raised when a frequency does not resolve to a supported amateur band."""


_BAND_RANGES: Final[tuple[tuple[int, int, RadioBand], ...]] = (
    (1_800_000, 2_000_000, RadioBand.BAND_160M),
    (3_500_000, 4_000_000, RadioBand.BAND_80M),
    (5_300_000, 5_500_000, RadioBand.BAND_60M),
    (7_000_000, 7_300_000, RadioBand.BAND_40M),
    (10_100_000, 10_150_000, RadioBand.BAND_30M),
    (14_000_000, 14_350_000, RadioBand.BAND_20M),
    (18_068_000, 18_168_000, RadioBand.BAND_17M),
    (21_000_000, 21_450_000, RadioBand.BAND_15M),
    (24_890_000, 24_990_000, RadioBand.BAND_12M),
    (28_000_000, 29_700_000, RadioBand.BAND_10M),
    (50_000_000, 54_000_000, RadioBand.BAND_6M),
)


def resolve_radio_band(frequency: Frequency) -> RadioBand:
    """Return the supported amateur band containing one frequency."""
    if not isinstance(frequency, Frequency):
        raise TypeError("frequency must be a Frequency")

    for lower_hz, upper_hz, band in _BAND_RANGES:
        if lower_hz <= frequency.hz <= upper_hz:
            return band

    raise RadioBandResolutionError(
        f"Frequency {frequency.hz} Hz is outside the supported amateur bands."
    )
