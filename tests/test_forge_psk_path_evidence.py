import sqlite3
from datetime import UTC, datetime, timedelta

from rolling_thunder.forge_psk_path_evidence import lookup_outbound_evidence

NOW = datetime(2026, 10, 10, 18, tzinfo=UTC)


def test_readonly_directional_recent_nearby_deduplicated(tmp_path):
    path = tmp_path / "history.db"
    with sqlite3.connect(path) as db:
        db.execute(
            """CREATE TABLE psk_reception
            (sender_callsign TEXT, receiver_callsign TEXT,
             receiver_locator_normalized TEXT, flow_start_utc TEXT,
             snr_db INTEGER, frequency_hz INTEGER, mode TEXT)"""
        )
        def add(sender, recv, grid, time, freq=14_074_000, mode="FT8", snr=-9):
            db.execute("INSERT INTO psk_reception VALUES (?,?,?,?,?,?,?)",
                       (sender, recv, grid, time.isoformat(), snr, freq, mode))
        recent = NOW - timedelta(minutes=3)
        add("KI5VNB", "DL1ABC", "JN58", recent, snr=-12)
        add("KI5VNB", "DL1ABC", "JN58", recent, snr=-12)
        add("KI5VNB", "DL2ABC", "JN59", recent, snr=-8)
        add("DL1ABC", "KI5VNB", "EM79", recent, snr=15)
        add("KI5VNB", "DL3ABC", "JN58", NOW - timedelta(minutes=45))
        add("KI5VNB", "DL4ABC", "JN58", recent, freq=7_074_000)
        add("KI5VNB", "DL5ABC", "JN58", recent, mode="WSPR")
    result = lookup_outbound_evidence(
        path, sender_callsign="KI5VNB", target_grid="JN58",
        frequency_hz=14_074_000, now_utc=NOW,
    )
    assert result.nearby_receivers == 2
    assert result.independent_receivers == 2
    assert result.median_snr_db == -10
    assert result.directional and not result.usable_for_calibrated_probability


def test_missing_database_is_neutral(tmp_path):
    result = lookup_outbound_evidence(
        tmp_path / "missing.db", sender_callsign="KI5VNB",
        target_grid="PM95", frequency_hz=14_074_000, now_utc=NOW,
    )
    assert not result.has_relevant_evidence
    assert result.latest_reception_utc is None
    assert not (tmp_path / "missing.db").exists()
