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
    raw_message: str | None = None,
    qualifier: str | None = None,
) -> FT8Decode:
    return FT8Decode(
        period=FT8Period(index=period),
        snr_db=snr,
        dt_seconds=dt,
        audio_frequency_hz=audio_hz,
        raw_message=raw_message or f"CQ {callsign}",
        kind=kind,
        source_callsign=callsign,
        grid=grid,
        cq_qualifier=qualifier,
    )


def test_clear_drops_all_old_band_activity_and_period_state() -> None:
    manager = FT8CQActivityManager()
    manager.ingest(_decode(100, callsign="K1AAA"))
    manager.ingest(_decode(101, callsign="K2BBB"))

    manager.clear()

    assert manager.snapshot() == ()
    assert manager.latest_period is None


def test_cq_is_added_and_repeated_cq_updates_without_duplicate() -> None:
    manager = FT8CQActivityManager()
    manager.ingest(_decode(100, snr=-15, audio_hz=1200))
    manager.ingest(_decode(102, callsign="k1abc", snr=-5, dt=0.3, audio_hz=1600))

    snapshot = manager.snapshot()

    assert len(snapshot) == 1
    assert snapshot[0].callsign == "K1ABC"
    assert snapshot[0].last_cq == FT8Period(index=102)
    assert snapshot[0].last_any_decode == FT8Period(index=102)
    assert snapshot[0].last_period == FT8Period(index=102)
    assert snapshot[0].cq_count == 2
    assert snapshot[0].snr_db == -5
    assert snapshot[0].dt_seconds == 0.3
    assert snapshot[0].audio_frequency_hz == 1600
    assert snapshot[0].active_non_cq is False


def test_non_cq_does_not_enter_browser_activity() -> None:
    manager = FT8CQActivityManager()

    manager.ingest(_decode(100, kind=FT8MessageKind.REPORT))

    assert manager.snapshot() == ()


def test_non_cq_for_existing_cq_updates_any_decode_and_marks_active() -> None:
    manager = FT8CQActivityManager()
    manager.ingest(_decode(100))
    manager.ingest(_decode(102, kind=FT8MessageKind.REPORT, grid="EM80aa"))

    activity = manager.snapshot()[0]

    assert activity.last_cq == FT8Period(index=100)
    assert activity.last_any_decode == FT8Period(index=102)
    assert activity.active_non_cq is True
    assert activity.grid == "EM80aa"


def test_non_cq_active_marker_expires_after_ten_seconds() -> None:
    now = {"value": 100.0}
    manager = FT8CQActivityManager(monotonic_clock=lambda: now["value"])
    manager.ingest(_decode(100))
    manager.ingest(_decode(101, kind=FT8MessageKind.REPORT))

    assert manager.snapshot()[0].active_non_cq is True

    now["value"] = 109.999
    assert manager.snapshot()[0].active_non_cq is True

    now["value"] = 110.0
    assert manager.snapshot()[0].active_non_cq is False


def test_subsequent_cq_clears_non_cq_active_state() -> None:
    manager = FT8CQActivityManager()
    manager.ingest(_decode(100))
    manager.ingest(_decode(101, kind=FT8MessageKind.REPORT))
    manager.ingest(_decode(102))

    activity = manager.snapshot()[0]

    assert activity.active_non_cq is False
    assert activity.cq_count == 2


def test_activity_expires_after_six_periods_without_any_traffic() -> None:
    manager = FT8CQActivityManager()
    manager.ingest(_decode(100))

    assert len(manager.snapshot(current_period=FT8Period(index=105))) == 1
    assert manager.snapshot(current_period=FT8Period(index=106)) == ()


def test_non_cq_traffic_extends_lifetime_without_changing_last_cq() -> None:
    manager = FT8CQActivityManager()
    manager.ingest(_decode(100))
    manager.ingest(_decode(104, kind=FT8MessageKind.REPORT))

    assert len(manager.snapshot(current_period=FT8Period(index=109))) == 1
    assert manager.snapshot()[0].last_cq == FT8Period(index=100)
    assert manager.snapshot(current_period=FT8Period(index=110)) == ()


def test_older_repeated_cq_does_not_replace_newer_signal_data() -> None:
    manager = FT8CQActivityManager()
    manager.ingest(_decode(102, snr=-5))
    manager.ingest(_decode(100, snr=-20))

    assert manager.snapshot()[0].snr_db == -5
    assert manager.latest_period == FT8Period(index=102)


def test_same_period_duplicate_cq_does_not_increment_cq_count() -> None:
    manager = FT8CQActivityManager()
    manager.ingest(_decode(100, snr=-10))
    manager.ingest(_decode(100, snr=-8))

    assert manager.snapshot()[0].cq_count == 1
    assert manager.snapshot()[0].snr_db == -8


def test_snapshot_preserves_first_seen_insertion_order() -> None:
    manager = FT8CQActivityManager()
    manager.ingest(_decode(100, callsign="K1AAA"))
    manager.ingest(_decode(101, callsign="K2BBB"))
    manager.ingest(_decode(102, callsign="K1AAA"))

    assert [item.callsign for item in manager.snapshot()] == ["K1AAA", "K2BBB"]


def test_pota_metadata_requires_explicit_pota_token() -> None:
    manager = FT8CQActivityManager()
    manager.ingest(
        _decode(
            100,
            callsign="K1POTA",
            raw_message="CQ POTA K1POTA EM79",
            qualifier="POTA",
        )
    )
    manager.ingest(_decode(100, callsign="K2ABC", raw_message="CQ K2ABC EM79"))

    activity = {item.callsign: item for item in manager.snapshot()}

    assert activity["K1POTA"].pota_cq is True
    assert activity["K2ABC"].pota_cq is False
