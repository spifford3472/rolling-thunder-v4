import sqlite3
from datetime import UTC, datetime, timedelta

from rolling_thunder.forge_psk_coverage_audit import audit_coverage

NOW = datetime(2026, 10, 10, 23, tzinfo=UTC)


def test_missing_and_wrong_schema_are_explicit(tmp_path):
    assert audit_coverage(tmp_path / "none.db", sender="KI5VNB", now=NOW)["reason"] == "database_missing"
    path = tmp_path / "wrong.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE unrelated (id INTEGER)")
    assert audit_coverage(path, sender="KI5VNB", now=NOW)["reason"] == "normalized_schema_missing"


def test_outbound_only_aggregates_no_receiver_names(tmp_path):
    path = tmp_path / "normalized.db"
    with sqlite3.connect(path) as db:
        db.execute("""CREATE TABLE psk_reception (
          sender_callsign TEXT, receiver_callsign TEXT, receiver_locator_normalized TEXT,
          frequency_hz INTEGER, flow_start_utc TEXT, mode TEXT, snr_db INTEGER)""")
        for sender, receiver, minutes, grid in (
            ("KI5VNB", "DL1ABC", 5, "JN58"),
            ("KI5VNB", "DL1ABC", 7, "JN58"),
            ("KI5VNB", "DL2ABC", 62, None),
            ("DL1ABC", "KI5VNB", 1, "EM79"),
            ("KI5VNB", "DL3ABC", 2000, "JN58"),
        ):
            db.execute(
                "INSERT INTO psk_reception VALUES (?,?,?,?,?,?,?)",
                (sender, receiver, grid, 14074000,
                 (NOW - timedelta(minutes=minutes)).isoformat(), "FT8", -10),
            )
    result = audit_coverage(path, sender="KI5VNB", now=NOW)
    assert result["last_30m"] == {
        "receptions": 2, "independent_receivers": 1, "receivers_with_grid": 1,
    }
    assert result["last_120m"]["independent_receivers"] == 2
    assert "DL1ABC" not in str(result)


def test_n2_z_timestamp_is_counted(tmp_path):
    path = tmp_path / "normalized.db"
    with sqlite3.connect(path) as db:
        db.execute("""CREATE TABLE psk_reception (sender_callsign TEXT, receiver_callsign TEXT, receiver_locator_normalized TEXT, frequency_hz INTEGER, flow_start_utc TEXT, mode TEXT, snr_db INTEGER)""")
        db.execute("INSERT INTO psk_reception VALUES (?,?,?,?,?,?,?)",
                   ("KI5VNB", "JA1XYZ", "PM95", 14074000, "2026-10-10T22:59:00Z", "FT8", -13))
    result = audit_coverage(path, sender="KI5VNB", now=NOW)
    assert result["last_30m"]["receptions"] == 1
