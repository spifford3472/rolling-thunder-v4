"""Tests for durable UTC-day POTA worked markers."""

from datetime import UTC, datetime
from pathlib import Path

from rolling_thunder.domain import Contact, Frequency, RadioMode
from rolling_thunder.pota_spots import ParkReference, PotaSpot
from rolling_thunder.pota_worked import (
    PotaWorkedRepository,
    PotaWorkedTracker,
    pota_worked_key_from_contact,
)

DAY_ONE = datetime(2026, 9, 24, 23, 59, tzinfo=UTC)
DAY_TWO = datetime(2026, 9, 25, 0, 1, tzinfo=UTC)


class MutableClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


def contact(
    *,
    callsign: str = "K1POTA",
    frequency_hz: int = 14_074_000,
    mode: RadioMode = RadioMode.DATA,
    started_at: datetime = DAY_ONE,
    park_reference: str | None = "US-1234",
) -> Contact:
    return Contact(
        callsign=callsign,
        frequency_hz=frequency_hz,
        mode=mode,
        started_at=started_at,
        rst_sent="-10",
        rst_received="-08",
        pota_reference=park_reference,
    )


def spot(
    *,
    callsign: str = "K1POTA",
    park_reference: str = "US-1234",
    frequency_hz: int = 14_074_000,
    mode: RadioMode = RadioMode.DATA,
    display_mode: str = "FT8",
) -> PotaSpot:
    return PotaSpot(
        activator=callsign,
        park=ParkReference(reference=park_reference),
        frequency=Frequency(hz=frequency_hz),
        mode=mode,
        spot_mode=display_mode,
        spotted_at=DAY_ONE,
    )


def tracker(database_path: Path, clock: MutableClock) -> PotaWorkedTracker:
    return PotaWorkedTracker(
        PotaWorkedRepository(database_path),
        clock=clock,
    )


def test_worked_key_is_callsign_display_mode_and_band_not_frequency(
    tmp_path: Path,
) -> None:
    clock = MutableClock(DAY_ONE)
    worked = tracker(tmp_path / "rolling-thunder.db", clock)

    key = worked.record_contact(contact(), (spot(),))

    assert key is not None
    assert worked.is_worked(
        callsign="K1POTA",
        frequency=Frequency(hz=14_074_000),
        display_mode="FT8",
        reference_time=DAY_ONE,
    )
    assert worked.is_worked(
        callsign="K1POTA",
        frequency=Frequency(hz=14_250_000),
        display_mode="FT8",
        reference_time=DAY_ONE,
    )
    assert not worked.is_worked(
        callsign="K1POTA",
        frequency=Frequency(hz=14_074_000),
        display_mode="RTTY",
        reference_time=DAY_ONE,
    )
    assert not worked.is_worked(
        callsign="K1POTA",
        frequency=Frequency(hz=7_074_000),
        display_mode="FT8",
        reference_time=DAY_ONE,
    )
    assert not worked.is_worked(
        callsign="K2POTA",
        frequency=Frequency(hz=14_074_000),
        display_mode="FT8",
        reference_time=DAY_ONE,
    )


def test_worked_marker_survives_same_day_restart(tmp_path: Path) -> None:
    database_path = tmp_path / "rolling-thunder.db"
    clock = MutableClock(DAY_ONE)
    first = tracker(database_path, clock)
    first.record_contact(contact(), (spot(),))

    restarted = tracker(database_path, clock)

    assert restarted.is_worked(
        callsign="K1POTA",
        frequency=Frequency(hz=14_074_000),
        display_mode="FT8",
        reference_time=DAY_ONE,
    )


def test_worked_marker_clears_at_next_utc_day_without_database_polling(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "rolling-thunder.db"
    clock = MutableClock(DAY_ONE)
    worked = tracker(database_path, clock)
    worked.record_contact(contact(), (spot(),))

    clock.value = DAY_TWO

    assert not worked.is_worked(
        callsign="K1POTA",
        frequency=Frequency(hz=14_074_000),
        display_mode="FT8",
        reference_time=DAY_TWO,
    )


def test_key_resolution_preserves_exact_pota_display_mode() -> None:
    resolved = pota_worked_key_from_contact(contact(), (spot(display_mode="FT8"),))

    assert resolved is not None
    assert resolved.callsign == "K1POTA"
    assert resolved.band.value == "20m"
    assert resolved.display_mode == "FT8"


def test_key_resolution_does_not_guess_ambiguous_display_mode() -> None:
    resolved = pota_worked_key_from_contact(
        contact(),
        (
            spot(display_mode="FT8"),
            spot(display_mode="RTTY"),
        ),
    )

    assert resolved is None


def test_unmatched_contact_is_not_marked_worked() -> None:
    resolved = pota_worked_key_from_contact(
        contact(callsign="K9XYZ", park_reference=None),
        (spot(),),
    )

    assert resolved is None


def test_matching_active_pota_contact_can_mark_without_resolved_park() -> None:
    resolved = pota_worked_key_from_contact(
        contact(park_reference=None),
        (spot(),),
    )

    assert resolved is not None
    assert resolved.callsign == "K1POTA"
    assert resolved.display_mode == "FT8"


def test_phone_sidebands_resolve_to_spot_display_mode() -> None:
    resolved = pota_worked_key_from_contact(
        contact(
            frequency_hz=7_200_000,
            mode=RadioMode.LSB,
        ),
        (
            spot(
                frequency_hz=7_200_000,
                mode=RadioMode.USB,
                display_mode="SSB",
            ),
        ),
    )

    assert resolved is not None
    assert resolved.band.value == "40m"
    assert resolved.display_mode == "SSB"
