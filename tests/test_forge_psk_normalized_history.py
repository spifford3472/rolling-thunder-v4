"""Normalized PSK history is additive and safe to repeat."""
import json
import sqlite3
from pathlib import Path

from rolling_thunder.forge_propagation_history import ForgePropagationHistoryRepository
from rolling_thunder.forge_psk_normalized_history import (
    RAW_RETENTION_DAYS,
    backfill,
    normalize_summary,
    retention_preview,
)


def _report(grid: str = "FN42gh82") -> dict:
    return {
        "sender_callsign": "KI5VNB", "receiver_callsign": "K1ABC",
        "receiver_locator": grid, "frequency_hz": 7074100,
        "flow_start_utc": "2026-10-10T02:40:00Z",
        "snr_db": -15, "mode": "FT8", "sequence_number": None,
    }


def test_normalization_preserves_repeated_identical_observations(tmp_path: Path) -> None:
    path = tmp_path / "history.sqlite"
    ForgePropagationHistoryRepository(path)
    with sqlite3.connect(path) as db:
        db.execute(
            "INSERT INTO pskreporter_query "
            "(query_id,queried_at_utc,endpoint,status,query_parameters_json,raw_xml,skipped_record_count)"
            "VALUES ('q1','2026-10-10T02:48:00Z','provider','succeeded','{}','<xml/>',0)"
        )
        reports = [_report(), _report(), _report("EL87VUEL09")]
        normalize_summary(db, contact_id="c1", query_id="q1", matched_reports=reports, raw_xml="<xml/>")
        normalize_summary(db, contact_id="c1", query_id="q1", matched_reports=reports, raw_xml="<xml/>")
        assert db.execute("SELECT count(*) FROM psk_reception").fetchone()[0] == 3
        assert db.execute("SELECT count(*) FROM psk_qso_reception").fetchone()[0] == 3
        assert db.execute("SELECT receiver_locator_normalized,locator_quality FROM psk_reception WHERE receiver_locator_raw='EL87VUEL09'").fetchone() == (None, "invalid")


def test_backfill_is_idempotent_and_non_destructive(tmp_path: Path) -> None:
    path = tmp_path / "history.sqlite"
    ForgePropagationHistoryRepository(path)
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO pskreporter_query (query_id,queried_at_utc,endpoint,status,query_parameters_json,raw_xml,skipped_record_count) VALUES ('q1','2026-10-10T02:48:00Z','provider','succeeded','{}','<xml/>',0)")
        db.execute("INSERT INTO qso_pskreporter_summary (contact_id,query_id,status,queried_at_utc,raw_response_json) VALUES (?,?,?,?,?)", ("c1","q1","queried_with_reports","2026-10-10T02:48:00Z",json.dumps({"matched_reports":[_report()]})))
        db.commit()
    assert backfill(path) == {"contacts": 1, "matched_reports": 1}
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM psk_reception").fetchone()[0] == 0
    backfill(path, apply=True)
    backfill(path, apply=True)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM psk_reception").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM psk_qso_reception").fetchone()[0] == 1
        assert db.execute("SELECT raw_xml FROM pskreporter_query").fetchone()[0] == "<xml/>"
    assert RAW_RETENTION_DAYS == 90
    assert retention_preview(path) == []
