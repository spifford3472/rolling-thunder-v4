"""Tests for Rolling Thunder SQLite storage initialization."""

import sqlite3
from pathlib import Path

import pytest

from rolling_thunder.storage import (
    CURRENT_SCHEMA_VERSION,
    StorageError,
    initialize_database,
)


def read_schema_version(database_path: Path) -> int:
    """Read the stored schema version from a test database."""
    with sqlite3.connect(database_path) as connection:
        result = connection.execute(
            """
            SELECT schema_version
            FROM schema_metadata
            WHERE singleton_id = 1
            """
        ).fetchone()

    assert result is not None
    return int(result[0])


def test_initialize_database_creates_parent_directory(tmp_path: Path) -> None:
    """Database initialization should create missing parent directories."""
    database_path = tmp_path / "nested" / "data" / "rolling-thunder.db"

    assert not database_path.parent.exists()

    version = initialize_database(database_path)

    assert database_path.is_file()
    assert version == CURRENT_SCHEMA_VERSION


def test_initialize_database_creates_schema_metadata(tmp_path: Path) -> None:
    """A new database should be migrated to the current schema version."""
    database_path = tmp_path / "rolling-thunder.db"

    version = initialize_database(database_path)

    assert version == CURRENT_SCHEMA_VERSION
    assert read_schema_version(database_path) == CURRENT_SCHEMA_VERSION


def test_initialize_database_is_safe_on_repeated_startup(tmp_path: Path) -> None:
    """Repeated initialization should not recreate or corrupt the schema."""
    database_path = tmp_path / "rolling-thunder.db"

    first_version = initialize_database(database_path)
    second_version = initialize_database(database_path)

    assert first_version == CURRENT_SCHEMA_VERSION
    assert second_version == CURRENT_SCHEMA_VERSION
    assert read_schema_version(database_path) == CURRENT_SCHEMA_VERSION


def test_initialize_database_enables_foreign_keys(tmp_path: Path) -> None:
    """SQLite foreign-key enforcement should be enabled during initialization."""
    database_path = tmp_path / "rolling-thunder.db"

    initialize_database(database_path)

    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        result = connection.execute("PRAGMA foreign_keys").fetchone()

    assert result == (1,)


def test_initialize_database_rejects_directory_path(tmp_path: Path) -> None:
    """A directory used as a database path should produce a storage error."""
    database_path = tmp_path / "database-directory"
    database_path.mkdir()

    with pytest.raises(StorageError, match="Database could not be initialized"):
        initialize_database(database_path)


def test_initialize_database_rejects_newer_schema(tmp_path: Path) -> None:
    """A database newer than the application supports must not be modified."""
    database_path = tmp_path / "newer.db"

    initialize_database(database_path)

    newer_version = CURRENT_SCHEMA_VERSION + 1

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            UPDATE schema_metadata
            SET schema_version = ?
            WHERE singleton_id = 1
            """,
            (newer_version,),
        )
        connection.commit()

    with pytest.raises(
        StorageError,
        match=r"newer than supported version",
    ):
        initialize_database(database_path)

    assert read_schema_version(database_path) == newer_version


def read_table_columns(
    database_path: Path,
    table_name: str,
) -> dict[str, tuple[object, ...]]:
    """Return SQLite table metadata keyed by column name."""
    with sqlite3.connect(database_path) as connection:
        rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()

    return {str(row[1]): row for row in rows}


def read_index_names(database_path: Path, table_name: str) -> set[str]:
    """Return index names associated with a SQLite table."""
    with sqlite3.connect(database_path) as connection:
        rows = connection.execute(f"PRAGMA index_list({table_name})").fetchall()

    return {str(row[1]) for row in rows}


def create_version_one_database(database_path: Path) -> None:
    """Create a database matching the first released schema version."""
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE schema_metadata (
                singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
                schema_version INTEGER NOT NULL CHECK (schema_version >= 0),
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.execute(
            """
            INSERT INTO schema_metadata (
                singleton_id,
                schema_version
            )
            VALUES (1, 1)
            """
        )
        connection.commit()


def test_initialize_database_creates_contacts_table(tmp_path: Path) -> None:
    """A new database should include the durable contacts table."""
    database_path = tmp_path / "rolling-thunder.db"

    initialize_database(database_path)

    columns = read_table_columns(database_path, "contacts")

    assert set(columns) == {
        "contact_id",
        "callsign",
        "frequency_hz",
        "mode",
        "started_at",
        "rst_sent",
        "rst_received",
        "grid",
        "my_grid",
        "pota_reference",
        "grid_source",
        "enrichment_state",
        "notes",
        "synchronization_state",
        "created_at",
        "updated_at",
    }

    assert columns["contact_id"][5] == 1
    assert columns["callsign"][3] == 1
    assert columns["frequency_hz"][3] == 1
    assert columns["mode"][3] == 1
    assert columns["started_at"][3] == 1
    assert columns["synchronization_state"][4] == "'pending'"
    assert columns["enrichment_state"][4] == "'ready'"


def test_initialize_database_creates_pota_cache_metadata_columns(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "rolling-thunder.db"

    initialize_database(database_path)

    columns = read_table_columns(database_path, "pota_spot_cache")
    assert {
        "spot_mode",
        "location_code",
        "latitude",
        "longitude",
    }.issubset(columns)


def test_initialize_database_creates_contact_indexes(tmp_path: Path) -> None:
    """Contact retrieval and synchronization should have supporting indexes."""
    database_path = tmp_path / "rolling-thunder.db"

    initialize_database(database_path)

    indexes = read_index_names(database_path, "contacts")

    assert {
        "contacts_started_at_index",
        "contacts_synchronization_state_index",
        "contacts_callsign_index",
        "contacts_sync_enrichment_index",
    }.issubset(indexes)


def test_initialize_database_migrates_version_one_database(
    tmp_path: Path,
) -> None:
    """An existing version-one database should migrate without replacement."""
    database_path = tmp_path / "rolling-thunder.db"
    create_version_one_database(database_path)

    assert read_schema_version(database_path) == 1

    version = initialize_database(database_path)

    assert version == CURRENT_SCHEMA_VERSION
    assert read_schema_version(database_path) == CURRENT_SCHEMA_VERSION
    assert read_table_columns(database_path, "contacts")
    assert "spot_mode" in read_table_columns(database_path, "pota_spot_cache")


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("frequency_hz", 0),
        ("frequency_hz", 300_000_000_001),
        ("mode", "INVALID"),
        ("synchronization_state", "unknown"),
    ],
)
def test_contacts_table_rejects_invalid_constrained_values(
    tmp_path: Path,
    column: str,
    value: object,
) -> None:
    """The database should protect essential domain invariants."""
    database_path = tmp_path / "rolling-thunder.db"
    initialize_database(database_path)

    values: dict[str, object] = {
        "contact_id": "00000000-0000-0000-0000-000000000001",
        "callsign": "W8O",
        "frequency_hz": 14_250_000,
        "mode": "USB",
        "started_at": "2026-07-25T00:30:00Z",
        "rst_sent": "59",
        "rst_received": "59",
        "synchronization_state": "pending",
    }
    values[column] = value

    with sqlite3.connect(database_path) as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
                INSERT INTO contacts (
                    contact_id,
                    callsign,
                    frequency_hz,
                    mode,
                    started_at,
                    rst_sent,
                    rst_received,
                    synchronization_state
                )
                VALUES (
                    :contact_id,
                    :callsign,
                    :frequency_hz,
                    :mode,
                    :started_at,
                    :rst_sent,
                    :rst_received,
                    :synchronization_state
                )
                """,
            values,
        )


def test_contacts_table_rejects_duplicate_contact_id(tmp_path: Path) -> None:
    """A contact UUID must uniquely identify one durable record."""
    database_path = tmp_path / "rolling-thunder.db"
    initialize_database(database_path)

    values = {
        "contact_id": "00000000-0000-0000-0000-000000000001",
        "callsign": "W8O",
        "frequency_hz": 14_250_000,
        "mode": "USB",
        "started_at": "2026-07-25T00:30:00Z",
        "rst_sent": "59",
        "rst_received": "59",
        "synchronization_state": "pending",
    }

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO contacts (
                contact_id,
                callsign,
                frequency_hz,
                mode,
                started_at,
                rst_sent,
                rst_received,
                synchronization_state
            )
            VALUES (
                :contact_id,
                :callsign,
                :frequency_hz,
                :mode,
                :started_at,
                :rst_sent,
                :rst_received,
                :synchronization_state
            )
            """,
            values,
        )

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO contacts (
                    contact_id,
                    callsign,
                    frequency_hz,
                    mode,
                    started_at,
                    rst_sent,
                    rst_received,
                    synchronization_state
                )
                VALUES (
                    :contact_id,
                    :callsign,
                    :frequency_hz,
                    :mode,
                    :started_at,
                    :rst_sent,
                    :rst_received,
                    :synchronization_state
                )
                """,
                values,
            )
