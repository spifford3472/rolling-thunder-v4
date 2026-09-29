"""Tests for FT8 CQ discovery activity without station selection authority."""

from rolling_thunder.ft8.activity import FT8CQActivityManager
from rolling_thunder.ft8.domain import FT8Decode, FT8MessageKind, FT8Period


def _decode(
    period: int,
    *,
    callsign: str = "K1ABC",
    kind: FT8MessageKind = FT8MessageKind.CQ,
    snr: int = -10,
    dt: float = 0.1,
    audio_hz: int = 1500,
    grid: str | None = "EM79xm",
) -> FT8Decode:
    return FT8Decode(
        period=FT8Period(index=period),
        snr_db=snr,
        dt_seconds=dt,
        audio_frequency_hz=audio_hz,
        raw_message=f"CQ {callsign}",
        kind=kind,
        source_callsign=callsign,
        grid=grid,
    )


def test_cq_is_added_and_repeated_cq_updates_without_duplicate() -> None:
    manager = FT8CQActivityManager()
    manager.ingest(_decode(100, snr=-15, audio_hz=1200))
    manager.ingest(_decode(102, callsign="k1abc", snr=-5, dt=0.3, audio_hz=1600))

    snapshot = manager.snapshot()

    assert len(snapshot) == 1
    assert snapshot[0].callsign == "K1ABC"
    assert snapshot[0].last_period == FT8Period(index=102)
    assert snapshot[0].snr_db == -5
    assert snapshot[0].dt_seconds == 0.3
    assert snapshot[0].audio_frequency_hz == 1600


def test_non_cq_does_not_enter_browser_activity() -> None:
    manager = FT8CQActivityManager()

    manager.ingest(_decode(100, kind=FT8MessageKind.REPORT))

    assert manager.snapshot() == ()


def test_activity_expires_after_four_periods_by_default() -> None:
    manager = FT8CQActivityManager()
    manager.ingest(_decode(100))

    assert len(manager.snapshot(current_period=FT8Period(index=103))) == 1
    assert manager.snapshot(current_period=FT8Period(index=104)) == ()


def test_older_repeated_cq_does_not_replace_newer_signal_data() -> None:
    manager = FT8CQActivityManager()
    manager.ingest(_decode(102, snr=-5))
    manager.ingest(_decode(100, snr=-20))

    assert manager.snapshot()[0].snr_db == -5
    assert manager.latest_period == FT8Period(index=102)
