"""Tests for transactional Forge mobile-location SQLite persistence."""

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from rolling_thunder.forge_mobile_location import (
    ForgeMobileLocationStorageError,
    MobileLocationRecord,
    StaleMobileLocationError,
)
from rolling_thunder.forge_mobile_location_repository import (
    SqliteForgeMobileLocationRepository,
)
from rolling_thunder.forge_snapshot_repository import SqliteForgeSnapshotRepository

BASE_TIME = datetime(2026, 8, 8, 23, 30, tzinfo=UTC)


def location(*, seconds: int = 0) -> MobileLocationRecord:
    fix_at = BASE_TIME + timedelta(seconds=seconds)
    return MobileLocationRecord(
        latitude=39.529 + seconds / 10_000,
        longitude=-84.064,
        fix_at=fix_at,
        received_at=fix_at + timedelta(seconds=1),
        speed_m_s=18.0,
        heading_degrees=90.0,
    )


def test_repository_round_trips_and_increments_revision(tmp_path: Path) -> None:
    repository = SqliteForgeMobileLocationRepository(tmp_path / "forge.db")

    first = repository.replace(location())
    second = repository.replace(location(seconds=5))
    loaded = repository.load()

    assert first.revision == 1
    assert second.revision == 2
    assert loaded == second
    assert loaded is not None
    assert loaded.location == location(seconds=5)


def test_stale_write_rolls_back_and_retains_prior_location(tmp_path: Path) -> None:
    repository = SqliteForgeMobileLocationRepository(tmp_path / "forge.db")
    current = repository.replace(location(seconds=10))

    with pytest.raises(StaleMobileLocationError, match="advance both"):
        repository.replace(location(seconds=5))

    assert repository.load() == current


def test_equal_fix_timestamp_is_rejected_without_revision_change(tmp_path: Path) -> None:
    repository = SqliteForgeMobileLocationRepository(tmp_path / "forge.db")
    current = repository.replace(location())
    duplicate = location().model_copy(
        update={"received_at": BASE_TIME + timedelta(seconds=2)}
    )

    with pytest.raises(StaleMobileLocationError):
        repository.replace(duplicate)

    assert repository.load() == current


def test_mobile_tables_coexist_with_existing_forge_snapshot_schema(tmp_path: Path) -> None:
    database_path = tmp_path / "forge.db"
    SqliteForgeSnapshotRepository(database_path)
    mobile = SqliteForgeMobileLocationRepository(database_path)
    mobile.replace(location())

    with sqlite3.connect(database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        snapshot_version = connection.execute(
            "SELECT schema_version FROM forge_schema_metadata WHERE singleton_id = 1"
        ).fetchone()
        mobile_version = connection.execute(
            """
            SELECT schema_version
            FROM forge_mobile_location_schema_metadata
            WHERE singleton_id = 1
            """
        ).fetchone()

    assert "forge_spots" in tables
    assert "forge_mobile_location" in tables
    assert snapshot_version == (1,)
    assert mobile_version == (1,)


def test_corrupt_retained_row_is_rejected_on_load(tmp_path: Path) -> None:
    database_path = tmp_path / "forge.db"
    repository = SqliteForgeMobileLocationRepository(database_path)
    repository.replace(location())

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "UPDATE forge_mobile_location SET fix_at = 'not-a-timestamp'"
        )
        connection.commit()

    with pytest.raises(ForgeMobileLocationStorageError, match="invalid data"):
        repository.load()


def test_repository_refuses_pi_application_database(tmp_path: Path) -> None:
    database_path = tmp_path / "rolling-thunder.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE schema_metadata (singleton_id INTEGER)")
        connection.execute("CREATE TABLE contacts (contact_id TEXT)")
        connection.commit()

    with pytest.raises(ForgeMobileLocationStorageError, match="separate Forge"):
        SqliteForgeMobileLocationRepository(database_path)


def test_repository_rejects_unsupported_mobile_schema_version(tmp_path: Path) -> None:
    database_path = tmp_path / "forge.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE forge_mobile_location_schema_metadata (
                singleton_id INTEGER PRIMARY KEY,
                schema_version INTEGER NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT INTO forge_mobile_location_schema_metadata VALUES (1, 99)"
        )
        connection.commit()

    with pytest.raises(ForgeMobileLocationStorageError, match="Unsupported"):
        SqliteForgeMobileLocationRepository(database_path)
