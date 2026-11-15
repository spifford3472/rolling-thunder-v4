"""Read-only recovery inspection: never run a live deployment or radio command."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "deploy/rolling-thunder-recovery-inspect.py"
SPEC = importlib.util.spec_from_file_location("rt_recovery_inspect", SOURCE)
assert SPEC and SPEC.loader
inspector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(inspector)

SHA_A = "a" * 40
SHA_B = "b" * 40


def _database(path: Path, contacts: int = 2, *, corrupt: bool = False) -> None:
    """Create only disposable SQLite fixtures."""
    if corrupt:
        path.write_bytes(b"not-sqlite")
        return
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE schema_metadata (name TEXT PRIMARY KEY, version INT)")
        connection.execute("INSERT INTO schema_metadata VALUES ('version',22)")
        connection.execute("CREATE TABLE contacts (callsign TEXT)")
        connection.executemany(
            "INSERT INTO contacts VALUES (?)", [(f"N{i}",) for i in range(contacts)]
        )


def _journal(directory: Path, backup: Path, phase: str = "migrating") -> Path:
    directory.mkdir(mode=0o700)
    path = directory / "transaction.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "transaction_id": "f" * 32,
                "previous_sha": SHA_A,
                "target_sha": SHA_B,
                "phase": phase,
                "backup_path": str(backup),
                "updated_utc": "2026-11-14T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    path.chmod(0o600)
    return path


def _mock_service(monkeypatch: pytest.MonkeyPatch, state: str, heartbeat: str) -> None:
    monkeypatch.setattr(
        inspector,
        "_service_evidence",
        lambda **_kw: {"state": state, "responsiveness": heartbeat, "pid": "444"},
    )


def _report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    current: int = 2,
    backup_count: int = 2,
    phase: str = "migrating",
) -> tuple[dict[str, object], Path]:
    app = tmp_path / "app"
    (app / ".git").mkdir(parents=True)
    db = app / "station.db"
    backup = tmp_path / "backup.db"
    _database(db, contacts=current)
    _database(backup, contacts=backup_count)
    journal = _journal(tmp_path / "private", backup, phase)
    monkeypatch.setattr(inspector, "_run", lambda *_args: SHA_B)
    _mock_service(monkeypatch, "single_expected_service_process", "tk_heartbeat_fresh")
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in (journal, db, backup)}
    report = inspector.inspect(journal, app, db)
    for path, prior in before.items():
        assert (path.read_bytes(), path.stat().st_mtime_ns) == prior
    assert "radio_ptt_state" in report and report["disposition"] == "blocked_manual_review"
    return report, journal


def test_complete_read_only_report_and_contact_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report, _ = _report(tmp_path, monkeypatch)
    assert report["git_sha"] == SHA_B
    assert report["database"]["integrity"] == "ok"
    assert report["schema_compatible_with_backup"] is True
    assert report["contact_count_not_regressed"] is True
    assert report["backup_contact_records_preserved"] is True
    assert report["database"]["contact_count"] == 2


def test_contact_regression_blocks_equivalence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report, _ = _report(tmp_path, monkeypatch, current=1, backup_count=3)
    assert report["contact_count_not_regressed"] is False
    assert report["backup_contact_records_preserved"] is False
    assert report["disposition"] == "blocked_manual_review"


def test_missing_backup_not_reported_safe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _report_value, journal = _report(tmp_path, monkeypatch)
    backup = Path(_report_value["journal"]["backup_path"])
    backup.unlink()
    revised = inspector.inspect(journal, tmp_path / "app", tmp_path / "app/station.db")
    assert revised["backup"]["integrity"] == "unknown"
    assert revised["schema_compatible_with_backup"] is False


def test_corrupt_database_and_journal_are_not_cleared(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _report_value, journal = _report(tmp_path, monkeypatch)
    (tmp_path / "app/station.db").write_bytes(b"corrupt")
    journal.write_text("not json", encoding="utf-8")
    revised = inspector.inspect(journal, tmp_path / "app", tmp_path / "app/station.db")
    assert revised["database"]["integrity"] == "unknown"
    assert "journal_error" in revised
    assert journal.read_text(encoding="utf-8") == "not json"


def test_old_version_without_heartbeat_is_unverified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _report_value, journal = _report(tmp_path, monkeypatch)
    _mock_service(monkeypatch, "single_expected_service_process", "unverified")
    revised = inspector.inspect(journal, tmp_path / "app", tmp_path / "app/station.db")
    assert revised["service"]["responsiveness"] == "unverified"
    assert revised["radio_ptt_state"] == "not_independently_verified"


def test_mismatched_and_duplicate_processes_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _report_value, journal = _report(tmp_path, monkeypatch)
    for state in ("unverified", "duplicate", "unmanaged"):
        _mock_service(monkeypatch, state, "unverified")
        revised = inspector.inspect(journal, tmp_path / "app", tmp_path / "app/station.db")
        assert revised["service"]["state"] != "single_expected_service_process"


def test_wal_requires_parked_snapshot_not_silent_immutable_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Read-only inspection never ignores uncheckpointed WAL transactions."""
    _report_value, journal = _report(tmp_path, monkeypatch)
    wal_path = Path(str(tmp_path / "app/station.db") + "-wal")
    wal_path.write_bytes(b"uncheckpointed data")
    revised = inspector.inspect(journal, tmp_path / "app", tmp_path / "app/station.db")
    assert revised["database"]["integrity"] == "unknown"
    assert revised["database"]["error"] == "wal_present_requires_parked_snapshot"
    assert revised["schema_compatible_with_backup"] is False
    assert wal_path.read_bytes() == b"uncheckpointed data"


def test_same_count_but_replaced_historical_contact_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Count parity must not conceal a dropped or overwritten prior QSO."""
    _report_value, journal = _report(tmp_path, monkeypatch)
    with sqlite3.connect(tmp_path / "app/station.db") as database:
        database.execute("UPDATE contacts SET callsign='REPLACED' WHERE callsign='N0'")
    revised = inspector.inspect(journal, tmp_path / "app", tmp_path / "app/station.db")
    assert revised["contact_count_not_regressed"] is True
    assert revised["backup_contact_records_preserved"] is False
    assert revised["disposition"] == "blocked_manual_review"
