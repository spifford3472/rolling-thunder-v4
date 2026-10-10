"""Provider-free, read-only PSK bridge schema and matching tests."""

import sqlite3
from datetime import date
from pathlib import Path

import pytest

from rolling_thunder.forge_psk_bridge_audit import audit_completed_ft8


def _database(path: Path) -> None:
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE forge_contact_sync_ledger (contact_id TEXT PRIMARY KEY, state TEXT)"
        )
        db.execute(
            "CREATE TABLE ft8_performance_attempts (attempt_id TEXT PRIMARY KEY,"
            " utc_date TEXT, outcome TEXT, success INTEGER, remote_grid TEXT,"
            " dial_frequency_hz INTEGER, ended_at_utc TEXT)"
        )
        db.executemany(
            "INSERT INTO ft8_performance_attempts VALUES (?,?,?,?,?,?,?)",
            [
                ("one", "2026-10-09", "completed", 1, "EM79", 14074000, "2026-10-09T12:00:00Z"),
                ("two", "2026-10-09", "completed", 1, None, 7074000, "2026-10-09T12:05:00Z"),
                (
                    "three",
                    "2026-10-09",
                    "retry_exhausted",
                    0,
                    "EM79",
                    7074000,
                    "2026-10-09T12:10:00Z",
                ),
                ("four", "2026-10-08", "completed", 1, "EM79", 7074000, "2026-10-08T12:10:00Z"),
            ],
        )
        db.execute("INSERT INTO forge_contact_sync_ledger VALUES ('one','synchronized')")


def test_readonly_aggregate_and_missing_contact_evidence(tmp_path: Path) -> None:
    db = tmp_path / "forge.db"
    _database(db)
    before = db.read_bytes()
    result = audit_completed_ft8(db, date(2026, 10, 9))
    assert result.attempts == 3
    assert result.completed_attempts == 2
    assert result.synchronized_completed_attempts == 1
    assert result.missing_synchronized_contacts == 1
    assert result.completed_with_grid == 1
    assert result.completed_with_frequency == 2
    assert result.eligible_for_existing_event_contract == 0
    assert db.read_bytes() == before


def test_missing_schema_fails_closed(tmp_path: Path) -> None:
    db = tmp_path / "empty.db"
    sqlite3.connect(db).close()
    with pytest.raises(ValueError, match="Missing required Forge tables"):
        audit_completed_ft8(db, date(2026, 10, 9))


def test_missing_database_does_not_create_it(tmp_path: Path) -> None:
    db = tmp_path / "absent.db"
    with pytest.raises(sqlite3.OperationalError):
        audit_completed_ft8(db, date(2026, 10, 9))
    assert not db.exists()
