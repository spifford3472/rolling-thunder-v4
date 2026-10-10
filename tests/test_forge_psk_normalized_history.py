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
            "VALUES ('q1','2026-10-10T02:48:00Z','provider','succeeded','{}','<receptionReports/>',0)"
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
        db.execute("INSERT INTO pskreporter_query (query_id,queried_at_utc,endpoint,status,query_parameters_json,raw_xml,skipped_record_count) VALUES ('q1','2026-10-10T02:48:00Z','provider','succeeded','{}','<receptionReports/>',0)")
        db.execute("INSERT INTO qso_pskreporter_summary (contact_id,query_id,status,queried_at_utc,raw_response_json) VALUES (?,?,?,?,?)", ("c1","q1","queried_with_reports","2026-10-10T02:48:00Z",json.dumps({"matched_reports":[_report()]})))
        db.commit()
    assert backfill(path) == {
        "contacts": 1, "matched_reports": 1, "provider_queries": 1,
        "provider_receptions": 0,
    }
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM psk_reception").fetchone()[0] == 0
    backfill(path, apply=True)
    backfill(path, apply=True)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM psk_reception").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM psk_qso_reception").fetchone()[0] == 1
        assert db.execute("SELECT raw_xml FROM pskreporter_query").fetchone()[0] == "<receptionReports/>"
    assert RAW_RETENTION_DAYS == 90
    assert retention_preview(path) == []



def _xml(*receivers: str) -> str:
    records = "".join(
        '<receptionReport senderCallsign="KI5VNB" receiverCallsign="'
        + call +
        '" receiverLocator="FN42" frequency="7074000" '
        'flowStartSeconds="1791600000" sNR="-14" mode="FT8"/>'
        for call in receivers
    )
    return "<receptionReports>" + records + "</receptionReports>"


def test_provider_ingestion_preserves_unlinked_reports_and_is_repeatable(tmp_path: Path) -> None:
    from rolling_thunder.forge_psk_normalized_history import normalize_provider_query
    path = tmp_path / "history.sqlite"
    ForgePropagationHistoryRepository(path)
    xml = _xml("K1ONE", "K1TWO", "K1TWO")
    with sqlite3.connect(path) as db:
        db.execute(
            "INSERT INTO pskreporter_query "
            "(query_id,queried_at_utc,endpoint,status,query_parameters_json,raw_xml,skipped_record_count)"
            " VALUES ('q1','2026-10-10T02:48:00Z','provider','succeeded','{}',?,0)", (xml,)
        )
        assert normalize_provider_query(
            db, query_id="q1", raw_xml=xml, skipped_expected=0
        ) == (3, 0)
        assert normalize_provider_query(
            db, query_id="q1", raw_xml=xml, skipped_expected=0
        ) == (3, 0)
        assert db.execute("SELECT COUNT(*) FROM psk_reception").fetchone()[0] == 3
        assert db.execute("SELECT COUNT(*) FROM psk_qso_reception").fetchone()[0] == 0
        assert db.execute(
            "SELECT parsed_count,normalized_count FROM psk_query_normalization_audit"
        ).fetchone() == (3, 3)


def test_pruning_requires_backup_and_preserves_query_provenance(tmp_path: Path) -> None:
    from datetime import UTC, datetime

    import pytest

    from rolling_thunder.forge_psk_normalized_history import (
        normalize_provider_query,
        prune_eligible_raw,
    )

    path = tmp_path / "history.sqlite"
    backup_path = tmp_path / "backup.sqlite"
    ForgePropagationHistoryRepository(path)
    xml = _xml("K1ONE")
    with sqlite3.connect(path) as db:
        db.execute(
            "INSERT INTO pskreporter_query "
            "(query_id,queried_at_utc,endpoint,status,query_parameters_json,raw_xml,skipped_record_count)"
            " VALUES ('q1','2026-01-01T00:00:00Z','provider','succeeded','{}',?,0)", (xml,)
        )
        normalize_provider_query(db,query_id="q1",raw_xml=xml,skipped_expected=0)
        db.commit()
        with sqlite3.connect(backup_path) as backup:
            db.backup(backup)
    with pytest.raises(ValueError, match="independent"):
        prune_eligible_raw(path,backup_evidence=path,now=datetime(2026,10,10,tzinfo=UTC))
    assert prune_eligible_raw(
        path,backup_evidence=backup_path,now=datetime(2026,10,10,tzinfo=UTC)
    ) == 1
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT raw_xml FROM pskreporter_query").fetchone() == (None,)
        assert db.execute("SELECT COUNT(*) FROM psk_reception").fetchone() == (1,)
