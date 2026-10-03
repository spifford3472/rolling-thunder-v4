"""Centralized FT8 dial-frequency plan for Rolling Thunder."""

from __future__ import annotations

from typing import Final

from rolling_thunder.domain import Frequency
from rolling_thunder.radio import RadioBand

FT8_DIAL_FREQUENCY_HZ: Final[dict[RadioBand, int]] = {
    RadioBand.BAND_160M: 1_840_000,
    RadioBand.BAND_80M: 3_573_000,
    RadioBand.BAND_60M: 5_357_000,
    RadioBand.BAND_40M: 7_074_000,
    RadioBand.BAND_30M: 10_136_000,
    RadioBand.BAND_20M: 14_074_000,
    RadioBand.BAND_17M: 18_100_000,
    RadioBand.BAND_15M: 21_074_000,
    RadioBand.BAND_12M: 24_915_000,
    RadioBand.BAND_10M: 28_074_000,
    RadioBand.BAND_6M: 50_313_000,
}

# The FT-891 adapter has no safe automated 60 m band-memory selection today.
# Keep 60 m in the frequency plan so a manually selected 60 m VFO can still be
# prepared safely, but omit it from automated cross-band cycling.
FT8_AUTOMATED_BAND_ORDER: Final[tuple[RadioBand, ...]] = (
    RadioBand.BAND_40M,
    RadioBand.BAND_30M,
    RadioBand.BAND_20M,
    RadioBand.BAND_17M,
    RadioBand.BAND_15M,
    RadioBand.BAND_12M,
    RadioBand.BAND_10M,
)


def ft8_frequency_for_band(band: RadioBand) -> Frequency:
    """Return the configured common FT8 dial frequency for one supported band."""
    if not isinstance(band, RadioBand):
        raise TypeError("band must be a RadioBand")
    try:
        return Frequency(hz=FT8_DIAL_FREQUENCY_HZ[band])
    except KeyError as error:
        raise ValueError(f"FT8 dial frequency is not configured for {band.value}") from error


def next_automated_ft8_band(current: RadioBand | None) -> RadioBand:
    """Cycle through bands that Rolling Thunder can select safely by CAT."""
    if current not in FT8_AUTOMATED_BAND_ORDER:
        return RadioBand.BAND_20M
    index = FT8_AUTOMATED_BAND_ORDER.index(current)
    return FT8_AUTOMATED_BAND_ORDER[(index + 1) % len(FT8_AUTOMATED_BAND_ORDER)]
