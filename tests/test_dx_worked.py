"""Tests for durable UTC-day DX worked markers."""

from datetime import UTC, datetime
from pathlib import Path

from rolling_thunder.domain import Contact, Frequency, RadioMode
from rolling_thunder.dx_worked import DxWorkedRepository, DxWorkedTracker

DAY_ONE = datetime(2026, 9, 24, 23, 59, tzinfo=UTC)
DAY_TWO = datetime(2026, 9, 25, 0, 1, tzinfo=UTC)


class MutableClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


def contact(*, frequency_hz: int = 14_250_000) -> Contact:
    return Contact(
        callsign="K1DX",
        frequency_hz=frequency_hz,
        mode=RadioMode.USB,
        started_at=DAY_ONE,
        rst_sent="59",
        rst_received="59",
    )


def tracker(database_path: Path, clock: MutableClock) -> DxWorkedTracker:
    return DxWorkedTracker(DxWorkedRepository(database_path), clock=clock)


def test_worked_key_is_callsign_and_band_not_frequency(tmp_path: Path) -> None:
    clock = MutableClock(DAY_ONE)
    worked = tracker(tmp_path / "rolling-thunder.db", clock)

    worked.record_contact(contact())

    assert worked.is_worked(
        callsign="K1DX",
        frequency=Frequency(hz=14_020_000),
        reference_time=DAY_ONE,
    )
    assert not worked.is_worked(
        callsign="K1DX",
        frequency=Frequency(hz=7_200_000),
        reference_time=DAY_ONE,
    )
    assert not worked.is_worked(
        callsign="K2DX",
        frequency=Frequency(hz=14_020_000),
        reference_time=DAY_ONE,
    )


def test_worked_marker_survives_same_day_restart(tmp_path: Path) -> None:
    database_path = tmp_path / "rolling-thunder.db"
    clock = MutableClock(DAY_ONE)
    tracker(database_path, clock).record_contact(contact())

    restarted = tracker(database_path, clock)

    assert restarted.is_worked(
        callsign="K1DX",
        frequency=Frequency(hz=14_300_000),
        reference_time=DAY_ONE,
    )


def test_worked_marker_expires_at_next_utc_day(tmp_path: Path) -> None:
    clock = MutableClock(DAY_ONE)
    worked = tracker(tmp_path / "rolling-thunder.db", clock)
    worked.record_contact(contact())

    clock.value = DAY_TWO

    assert not worked.is_worked(
        callsign="K1DX",
        frequency=Frequency(hz=14_250_000),
        reference_time=DAY_TWO,
    )
