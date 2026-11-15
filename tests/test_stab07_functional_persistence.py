"""STAB-07 synthetic SQLite migration and WAL recovery safety checks.

No production QSO, station database, or real radio may be used here.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from rolling_thunder import storage


def test_failed_multistatement_migration_rolls_back_schema_and_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unsuccessful migration must not leave a half-applied column."""
    database = tmp_path / "synthetic-schema.sqlite3"
    monkeypatch.setattr(storage, "CURRENT_SCHEMA_VERSION", 21)
    assert storage.initialize_database(database) == 21
    monkeypatch.setattr(storage, "CURRENT_SCHEMA_VERSION", 22)
    monkeypatch.setattr(
        storage,
        "_MIGRATIONS",
        {**storage._MIGRATIONS, 22: (
            "ALTER TABLE contacts ADD COLUMN synthetic_partial_column TEXT",
            "THIS IS NOT SQL",
        )},
    )
    with pytest.raises(storage.StorageError, match="Database could not be initialized"):
        storage.initialize_database(database)
    with sqlite3.connect(database) as connection:
        version = connection.execute(
            "SELECT schema_version FROM schema_metadata WHERE singleton_id=1"
        ).fetchone()
        columns = {row[1] for row in connection.execute("PRAGMA table_info(contacts)")}
    assert version == (21,)
    assert "synthetic_partial_column" not in columns
    monkeypatch.setattr(storage, "_MIGRATIONS", {
        **storage._MIGRATIONS,
        22: ("ALTER TABLE contacts ADD COLUMN my_county TEXT",),
    })
    assert storage.initialize_database(database) == 22
    assert storage.initialize_database(database) == 22


def test_synthetic_wal_committed_data_survives_reconnection_and_failed_write(
    tmp_path: Path,
) -> None:
    """A committed synthetic record survives reopening; a failed txn does not."""
    database = tmp_path / "synthetic-wal.sqlite3"
    assert storage.initialize_database(database) == storage.CURRENT_SCHEMA_VERSION
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
        connection.execute("CREATE TABLE isolated_probe (id INTEGER PRIMARY KEY, value TEXT)")
        connection.execute("INSERT INTO isolated_probe VALUES (1, 'committed')")
    with sqlite3.connect(database) as connection:
        connection.execute("BEGIN")
        connection.execute("INSERT INTO isolated_probe VALUES (2, 'uncommitted')")
        connection.rollback()
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("SELECT id,value FROM isolated_probe").fetchall() == [
            (1, "committed")
        ]
        assert connection.execute(
            "SELECT schema_version FROM schema_metadata WHERE singleton_id=1"
        ).fetchone() == (storage.CURRENT_SCHEMA_VERSION,)
