import sqlite3

import pytest

from rolling_thunder.forge_psk_evidence_server import validate_normalized_history


def test_normalized_schema_is_required_and_database_not_created(tmp_path):
    missing = tmp_path / "missing.db"
    with pytest.raises(ValueError):
        validate_normalized_history(missing)
    assert not missing.exists()
    with sqlite3.connect(tmp_path / "wrong.db") as db:
        db.execute("CREATE TABLE unrelated (id INTEGER)")
    with pytest.raises(ValueError):
        validate_normalized_history(tmp_path / "wrong.db")


def test_minimal_normalized_schema_passes(tmp_path):
    path = tmp_path / "normalized.db"
    with sqlite3.connect(path) as db:
        db.execute("""CREATE TABLE psk_reception (
            sender_callsign TEXT, receiver_callsign TEXT,
            receiver_locator_normalized TEXT, frequency_hz INTEGER,
            flow_start_utc TEXT, snr_db INTEGER, mode TEXT)""")
    validate_normalized_history(path)
