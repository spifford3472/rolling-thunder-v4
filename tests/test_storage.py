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
