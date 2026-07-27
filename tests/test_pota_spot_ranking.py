from datetime import UTC, datetime, timedelta

import pytest

from rolling_thunder.domain import Frequency, RadioMode
from rolling_thunder.pota_spot_ranking import (
    PotaSpotRankingCriteria,
    rank_pota_spots,
)
from rolling_thunder.pota_spots import AmateurBand, ParkReference, PotaSpot


REFERENCE_TIME = datetime(2026, 7, 27, 0, 0, tzinfo=UTC)


def make_spot(
    callsign: str,
    *,
    frequency_hz: int,
    mode: RadioMode,
    age_minutes: int,
) -> PotaSpot:
    return PotaSpot(
        activator=callsign,
        park=ParkReference(reference="US-1234", name="Test Park"),
        frequency=Frequency(hz=frequency_hz),
        mode=mode,
        spotted_at=REFERENCE_TIME - timedelta(minutes=age_minutes),
        comments=None,
    )


def test_rejects_naive_reference_time() -> None:
    with pytest.raises(ValueError, match="timezone"):
        PotaSpotRankingCriteria(reference_time=datetime(2026, 7, 27))


def test_empty_input_returns_empty_tuple() -> None:
    criteria = PotaSpotRankingCriteria(reference_time=REFERENCE_TIME)

    assert rank_pota_spots([], criteria) == ()


def test_newest_spot_ranks_first_without_preferences() -> None:
    older = make_spot(
        "K1OLD",
        frequency_hz=14_250_000,
        mode=RadioMode.USB,
        age_minutes=20,
    )
    newer = make_spot(
        "K1NEW",
        frequency_hz=7_200_000,
        mode=RadioMode.LSB,
        age_minutes=2,
    )

    ranked = rank_pota_spots(
        [older, newer],
        PotaSpotRankingCriteria(reference_time=REFERENCE_TIME),
    )

    assert [str(item.spot.activator) for item in ranked] == ["K1NEW", "K1OLD"]
    assert [item.age_seconds for item in ranked] == [120, 1200]


def test_preferred_band_outranks_recency() -> None:
    preferred = make_spot(
        "K1BAND",
        frequency_hz=14_250_000,
        mode=RadioMode.USB,
        age_minutes=15,
    )
    newer_other_band = make_spot(
        "K1OTHER",
        frequency_hz=7_200_000,
        mode=RadioMode.LSB,
        age_minutes=1,
    )

    ranked = rank_pota_spots(
        [newer_other_band, preferred],
        PotaSpotRankingCriteria(
            reference_time=REFERENCE_TIME,
            preferred_band=AmateurBand.BAND_20M,
        ),
    )

    assert ranked[0].spot is preferred
    assert ranked[0].band_match is True
    assert ranked[1].band_match is False


def test_preferred_mode_breaks_ties_after_band() -> None:
    usb = make_spot(
        "K1USB",
        frequency_hz=14_250_000,
        mode=RadioMode.USB,
        age_minutes=10,
    )
    cw = make_spot(
        "K1CW",
        frequency_hz=14_050_000,
        mode=RadioMode.CW,
        age_minutes=1,
    )

    ranked = rank_pota_spots(
        [cw, usb],
        PotaSpotRankingCriteria(
            reference_time=REFERENCE_TIME,
            preferred_band=AmateurBand.BAND_20M,
            preferred_mode=RadioMode.USB,
        ),
    )

    assert ranked[0].spot is usb
    assert ranked[0].band_match is True
    assert ranked[0].mode_match is True


def test_source_order_is_stable_final_tie_breaker() -> None:
    first = make_spot(
        "K1FIRST",
        frequency_hz=14_250_000,
        mode=RadioMode.USB,
        age_minutes=5,
    )
    second = make_spot(
        "K1SECOND",
        frequency_hz=14_260_000,
        mode=RadioMode.USB,
        age_minutes=5,
    )
    original = [first, second]

    ranked = rank_pota_spots(
        original,
        PotaSpotRankingCriteria(reference_time=REFERENCE_TIME),
    )

    assert [item.spot for item in ranked] == original
    assert [item.source_index for item in ranked] == [0, 1]
    assert original == [first, second]


def test_future_spot_age_is_clamped_to_zero() -> None:
    future = PotaSpot(
        activator="K1FUTURE",
        park=ParkReference(reference="US-9999"),
        frequency=Frequency(hz=14_250_000),
        mode=RadioMode.USB,
        spotted_at=REFERENCE_TIME + timedelta(minutes=1),
    )

    ranked = rank_pota_spots(
        [future],
        PotaSpotRankingCriteria(reference_time=REFERENCE_TIME),
    )

    assert ranked[0].age_seconds == 0
