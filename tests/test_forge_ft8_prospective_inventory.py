"""C5.2 Forge read-only v2 source audit on isolated mock SQLite files."""
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from rolling_thunder.forge_ft8_prospective_inventory import audit_prospective_inbox
from rolling_thunder.ft8.attempt_ledger import (
    FT8AttemptClassification,
    FT8AttemptEvent,
    FT8AttemptTxPeriod,
)
from rolling_thunder.ft8.performance import FT8AttemptOutcome


def _dbs(root: Path) -> tuple[Path, Path]:
    inbox, history = root / "inbox.sqlite", root / "history.sqlite"
    with sqlite3.connect(inbox) as db:
        db.execute("CREATE TABLE ft8_attempt_inbox (attempt_uuid TEXT,payload_sha256 TEXT,payload_json TEXT)")
    with sqlite3.connect(history) as db:
        db.execute("CREATE TABLE ft8_attempt_provenance_v1 (attempt_uuid TEXT, provenance TEXT)")
        db.execute("CREATE TABLE voacap_attempt_link_v1 (attempt_uuid TEXT,relation TEXT,as_of_cutoff_utc TEXT,training_eligible INTEGER,input_hash TEXT,prediction_uuid TEXT)")
        db.execute("CREATE TABLE voacap_prediction_run_v1 (prediction_uuid TEXT,available_at_utc TEXT,status TEXT)")
        db.execute("CREATE TABLE voacap_prediction_input_v1 (input_hash TEXT,input_json TEXT)")
    return inbox, history


def test_missing_and_unverified_history_never_promotes(tmp_path: Path) -> None:
    result = audit_prospective_inbox(tmp_path / "missing1", tmp_path / "missing2")
    assert not result["available"]
    inbox, history = _dbs(tmp_path)
    now = datetime(2026, 10, 11, 18, tzinfo=UTC)
    attempt = FT8AttemptEvent(
        schema_version=2, choice_at_utc=now, attempt_uuid=uuid4(),
        source_event_created_utc=now + timedelta(minutes=5),
        started_at_utc=now + timedelta(seconds=5),
        ended_at_utc=now + timedelta(minutes=2),
        classification=FT8AttemptClassification.SUCCESS,
        source_outcome=FT8AttemptOutcome.COMPLETED,
        terminal_phase="completed", remote_callsign="TEST1", band="40m",
        tx_periods=(FT8AttemptTxPeriod(sequence=1, started_at_utc=now + timedelta(seconds=15),
                                      ended_at_utc=now + timedelta(seconds=30),
                                      frequency_hz=7074000, transmitted=True),),
        transmit_attempt_count=1, busy_extension_attempts=0,
    )
    with sqlite3.connect(inbox) as db:
        db.execute("INSERT INTO ft8_attempt_inbox VALUES (?,?,?)",
                   (str(attempt.attempt_uuid), attempt.payload_sha256, attempt.model_dump_json()))
    assert audit_prospective_inbox(inbox, history)["prospective_pairs"] == 0
    with sqlite3.connect(history) as db:
        db.execute("INSERT INTO ft8_attempt_provenance_v1 VALUES (?,?)",
                   (str(attempt.attempt_uuid), "field_observed"))
    assert audit_prospective_inbox(inbox, history)["prospective_pairs"] == 0
    # Fake post-choice forecasts never qualify even if provider run is marked ready.
    with sqlite3.connect(history) as db:
        db.execute("INSERT INTO voacap_attempt_link_v1 VALUES (?,?,?,?,?,?)",
                   (str(attempt.attempt_uuid), "retrospective", now.isoformat(), 0, "fake", "run1"))
        db.execute("INSERT INTO voacap_prediction_run_v1 VALUES (?,?,?)",
                   ("run1", (now + timedelta(minutes=3)).isoformat(), "ready"))
        db.execute("INSERT INTO voacap_prediction_input_v1 VALUES (?,?)", ("fake", json.dumps({})))
    assert audit_prospective_inbox(inbox, history)["prospective_pairs"] == 0
