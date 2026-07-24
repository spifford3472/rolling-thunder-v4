"""Tests for Rolling Thunder SQLite storage initialization."""

import sqlite3
from pathlib import Path

import pytest

from rolling_thunder.storage import StorageError, initialize_database


def test_initialize_database_creates_parent_directory(tmp_path: Path) -> None:
    """Database initialization should create missing parent directories."""
    database_path = tmp_path / "nested" / "data" / "rolling-thunder.db"

    assert not database_path.parent.exists()

    initialize_database(database_path)

    assert database_path.is_file()


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
