"""Tests for typed POTA spot models and deterministic filtering."""

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from rolling_thunder.domain import Frequency, RadioMode
from rolling_thunder.pota_spots import (
    AmateurBand,
    ParkReference,
    PotaModeFilter,
    PotaSpot,
    filter_pota_spots,
    frequency_band,
)

_FIXED_TIME = datetime(2026, 7, 26, 18, 0, tzinfo=UTC)


def _spot(
    callsign: str,
    park: str,
    frequency_hz: int,
    mode: RadioMode,
    *,
    spot_mode: str | None = None,
    spotted_at: datetime = _FIXED_TIME,
) -> PotaSpot:
    return PotaSpot(
        activator=callsign,
        park=ParkReference(reference=park),
        frequency=Frequency(hz=frequency_hz),
        mode=mode,
        spot_mode=spot_mode,
        spotted_at=spotted_at,
    )


def test_pota_spot_normalizes_operator_facing_values() -> None:
    local_time = datetime(
        2026,
        7,
        26,
        14,
        0,
        tzinfo=timezone(timedelta(hours=-4)),
    )

    spot = PotaSpot(
        activator=" ki5vnb/p ",
        park=ParkReference(
            reference=" us-1234 ",
            name="  Caesar Creek State Park  ",
            location_code=" us-oh ",
            latitude=39.5,
            longitude=-84.0,
        ),
        frequency=Frequency(hz=14_250_000),
        mode=" usb ",
        spot_mode=" ssb ",
        spotted_at=local_time,
        comments="  Strong signal  ",
    )

    assert spot.activator == "KI5VNB/P"
    assert spot.park.reference == "US-1234"
    assert spot.park.name == "Caesar Creek State Park"
    assert spot.park.location_code == "us-oh"
    assert spot.park.latitude == 39.5
    assert spot.park.longitude == -84.0
    assert spot.mode is RadioMode.USB
    assert spot.spot_mode == "SSB"
    assert spot.display_mode == "SSB"
    assert spot.spotted_at == _FIXED_TIME
    assert spot.comments == "Strong signal"


def test_optional_text_converts_blank_values_to_none() -> None:
    park = ParkReference(reference="US-0001", name="   ", location_code=" ")
    spot = PotaSpot(
        activator="W8O",
        park=park,
        frequency=Frequency(hz=7_200_000),
        mode=RadioMode.LSB,
        spotted_at=_FIXED_TIME,
        comments="  ",
    )

    assert park.name is None
    assert park.location_code is None
    assert spot.comments is None


@pytest.mark.parametrize("reference", ["", "US1234", "US-12", "US-ABCDE", "US_-1234"])
def test_invalid_park_reference_is_rejected(reference: str) -> None:
    with pytest.raises(ValidationError, match="POTA reference"):
        ParkReference(reference=reference)


def test_naive_spot_timestamp_is_rejected() -> None:
    with pytest.raises(ValidationError, match="timezone information"):
        PotaSpot(
            activator="KI5VNB",
            park=ParkReference(reference="US-1234"),
            frequency=Frequency(hz=14_250_000),
            mode=RadioMode.USB,
            spotted_at=datetime(2026, 7, 26, 18, 0),  # noqa: DTZ001
        )


def test_frequency_band_returns_supported_band_or_none() -> None:
    assert frequency_band(Frequency(hz=14_250_000)) is AmateurBand.BAND_20M
    assert frequency_band(Frequency(hz=7_000_000)) is AmateurBand.BAND_40M
    assert frequency_band(Frequency(hz=144_200_000)) is None


def test_filter_spots_by_band_preserves_source_order() -> None:
    first = _spot("KI5VNB", "US-1001", 14_250_000, RadioMode.USB)
    second = _spot("W8O", "US-1002", 7_200_000, RadioMode.LSB)
    third = _spot("NC4XL", "US-1003", 14_300_000, RadioMode.USB)

    result = filter_pota_spots(
        [first, second, third],
        band=AmateurBand.BAND_20M,
    )

    assert result == [first, third]


def test_filter_spots_by_mode_and_combined_criteria() -> None:
    usb = _spot("KI5VNB", "US-1001", 14_250_000, RadioMode.USB)
    data = _spot("W8O", "US-1002", 14_074_000, RadioMode.DATA)
    lsb = _spot("NC4XL", "US-1003", 7_200_000, RadioMode.LSB)
    spots = [usb, data, lsb]

    assert filter_pota_spots(spots, mode=RadioMode.DATA) == [data]
    assert filter_pota_spots(
        spots,
        band=AmateurBand.BAND_20M,
        mode=RadioMode.USB,
    ) == [usb]
    assert filter_pota_spots(spots) == spots


def test_operator_mode_groups_keep_ft4_and_ft8_distinct() -> None:
    ssb = _spot(
        "K1SSB",
        "US-1001",
        14_250_000,
        RadioMode.USB,
        spot_mode="PHONE",
    )
    ft4 = _spot(
        "K1FT4",
        "US-1002",
        14_080_000,
        RadioMode.DATA,
        spot_mode="FT4",
    )
    ft8 = _spot(
        "K1FT8",
        "US-1003",
        14_074_000,
        RadioMode.DATA,
        spot_mode="FT8",
    )
    data = _spot(
        "K1DAT",
        "US-1004",
        14_070_000,
        RadioMode.DATA,
        spot_mode="RTTY",
    )
    spots = [ssb, ft4, ft8, data]

    assert filter_pota_spots(spots, mode_filter=PotaModeFilter.SSB_PHONE) == [ssb]
    assert filter_pota_spots(spots, mode_filter=PotaModeFilter.FT4) == [ft4]
    assert filter_pota_spots(spots, mode_filter=PotaModeFilter.FT8) == [ft8]
    assert filter_pota_spots(spots, mode_filter=PotaModeFilter.DATA) == [data]
    assert filter_pota_spots(spots, mode_filter=PotaModeFilter.ALL) == spots


def test_freshness_filter_hides_spots_older_than_fifteen_minutes() -> None:
    reference_time = datetime(2026, 7, 26, 18, 30, tzinfo=UTC)
    old = _spot(
        "K1OLD",
        "US-1001",
        14_250_000,
        RadioMode.USB,
        spotted_at=reference_time - timedelta(minutes=16),
    )
    fresh = _spot(
        "K1NEW",
        "US-1002",
        14_260_000,
        RadioMode.USB,
        spotted_at=reference_time - timedelta(minutes=15),
    )

    assert filter_pota_spots(
        [old, fresh],
        reference_time=reference_time,
        maximum_age=timedelta(minutes=15),
    ) == [fresh]


def test_freshness_filter_requires_reference_time() -> None:
    with pytest.raises(ValueError, match="reference time"):
        filter_pota_spots(
            [],
            maximum_age=timedelta(minutes=15),
        )
