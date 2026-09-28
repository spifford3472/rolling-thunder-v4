"""US Amateur Extra frequency and emission-segment advisory for Browse."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from rolling_thunder.domain import Frequency, RadioMode


class BandAdvisoryLevel(StrEnum):
    """Presentation level for one frequency/mode advisory."""

    OK = "ok"
    MODE_RESTRICTED = "mode_restricted"
    OUT_OF_BAND = "out_of_band"


@dataclass(frozen=True)
class AmateurExtraBand:
    """One US Amateur Extra allocation and its emission sub-bands."""

    name: str
    lower_hz: int
    upper_hz: int
    phone_ranges_hz: tuple[tuple[int, int], ...]
    data_ranges_hz: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class BandAdvisory:
    """Result displayed by the Browse page."""

    level: BandAdvisoryLevel
    message: str | None = None


_SIXTY_METER_CONTINUOUS = (5_351_500, 5_366_500)
_SIXTY_METER_USB_CARRIERS = (5_330_500, 5_346_500, 5_371_500, 5_403_500)
_SIXTY_METER_CW_CENTERS = (5_332_000, 5_348_000, 5_373_000, 5_405_000)


US_EXTRA_BANDS: tuple[AmateurExtraBand, ...] = (
    AmateurExtraBand(
        "160m",
        1_800_000,
        2_000_000,
        ((1_800_000, 2_000_000),),
        ((1_800_000, 2_000_000),),
    ),
    AmateurExtraBand(
        "80m",
        3_500_000,
        4_000_000,
        ((3_600_000, 4_000_000),),
        ((3_500_000, 3_600_000),),
    ),
    AmateurExtraBand(
        "40m",
        7_000_000,
        7_300_000,
        ((7_125_000, 7_300_000),),
        ((7_000_000, 7_125_000),),
    ),
    AmateurExtraBand(
        "30m",
        10_100_000,
        10_150_000,
        (),
        ((10_100_000, 10_150_000),),
    ),
    AmateurExtraBand(
        "20m",
        14_000_000,
        14_350_000,
        ((14_150_000, 14_350_000),),
        ((14_000_000, 14_150_000),),
    ),
    AmateurExtraBand(
        "17m",
        18_068_000,
        18_168_000,
        ((18_110_000, 18_168_000),),
        ((18_068_000, 18_110_000),),
    ),
    AmateurExtraBand(
        "15m",
        21_000_000,
        21_450_000,
        ((21_200_000, 21_450_000),),
        ((21_000_000, 21_200_000),),
    ),
    AmateurExtraBand(
        "12m",
        24_890_000,
        24_990_000,
        ((24_930_000, 24_990_000),),
        ((24_890_000, 24_930_000),),
    ),
    AmateurExtraBand(
        "10m",
        28_000_000,
        29_700_000,
        ((28_300_000, 29_700_000),),
        ((28_000_000, 28_300_000),),
    ),
    AmateurExtraBand(
        "6m",
        50_000_000,
        54_000_000,
        ((50_100_000, 54_000_000),),
        ((50_100_000, 54_000_000),),
    ),
)

_PHONE_MODES = frozenset({RadioMode.AM, RadioMode.FM, RadioMode.LSB, RadioMode.USB})


def us_extra_band_advisory(
    frequency: Frequency | None,
    mode: RadioMode | None,
) -> BandAdvisory:
    """Return the US Extra advisory for the current carrier and radio mode."""
    if frequency is None or mode is None:
        return BandAdvisory(BandAdvisoryLevel.OK)

    sixty_meter = _sixty_meter_advisory(frequency.hz, mode)
    if sixty_meter is not None:
        return sixty_meter

    band = next(
        (
            candidate
            for candidate in US_EXTRA_BANDS
            if candidate.lower_hz <= frequency.hz <= candidate.upper_hz
        ),
        None,
    )
    if band is None:
        return BandAdvisory(
            BandAdvisoryLevel.OUT_OF_BAND,
            "OUTSIDE US EXTRA BAND",
        )

    # Part 97 permits CW anywhere the control operator is otherwise authorized.
    if mode is RadioMode.CW:
        return BandAdvisory(BandAdvisoryLevel.OK)

    if mode in _PHONE_MODES:
        if _inside_any(frequency.hz, band.phone_ranges_hz):
            return BandAdvisory(BandAdvisoryLevel.OK)
        return BandAdvisory(
            BandAdvisoryLevel.MODE_RESTRICTED,
            f"{_mode_label(mode)} NOT AUTHORIZED HERE",
        )

    if mode is RadioMode.DATA:
        if _inside_any(frequency.hz, band.data_ranges_hz):
            return BandAdvisory(BandAdvisoryLevel.OK)
        return BandAdvisory(
            BandAdvisoryLevel.MODE_RESTRICTED,
            "DATA NOT AUTHORIZED HERE",
        )

    return BandAdvisory(
        BandAdvisoryLevel.MODE_RESTRICTED,
        f"{_mode_label(mode)} NOT AUTHORIZED HERE",
    )


def _inside_any(frequency_hz: int, ranges: tuple[tuple[int, int], ...]) -> bool:
    return any(lower <= frequency_hz <= upper for lower, upper in ranges)



def _sixty_meter_advisory(
    frequency_hz: int,
    mode: RadioMode,
) -> BandAdvisory | None:
    """Evaluate the current US 60 m segment/channels, when applicable."""
    in_continuous = (
        _SIXTY_METER_CONTINUOUS[0]
        <= frequency_hz
        <= _SIXTY_METER_CONTINUOUS[1]
    )
    in_sixty_envelope = 5_330_500 <= frequency_hz <= 5_406_400
    on_usb_carrier = frequency_hz in _SIXTY_METER_USB_CARRIERS
    on_cw_center = frequency_hz in _SIXTY_METER_CW_CENTERS

    if not in_sixty_envelope:
        return None

    if mode is RadioMode.CW:
        if in_continuous or on_cw_center:
            return BandAdvisory(BandAdvisoryLevel.OK)
        return BandAdvisory(
            BandAdvisoryLevel.OUT_OF_BAND,
            "OUTSIDE US EXTRA BAND",
        )

    if mode in {RadioMode.USB, RadioMode.DATA}:
        if in_continuous or on_usb_carrier:
            return BandAdvisory(BandAdvisoryLevel.OK)
        return BandAdvisory(
            BandAdvisoryLevel.OUT_OF_BAND,
            "OUTSIDE US EXTRA BAND",
        )

    if in_continuous or on_usb_carrier or on_cw_center:
        return BandAdvisory(
            BandAdvisoryLevel.MODE_RESTRICTED,
            f"{_mode_label(mode)} NOT AUTHORIZED HERE",
        )

    return BandAdvisory(
        BandAdvisoryLevel.OUT_OF_BAND,
        "OUTSIDE US EXTRA BAND",
    )



def _mode_label(mode: RadioMode) -> str:
    if mode in {RadioMode.LSB, RadioMode.USB}:
        return "SSB"
    return mode.value
