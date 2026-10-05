"""Tests for SQLite-backed repeater Active overrides."""

import sqlite3
from pathlib import Path

from rolling_thunder.domain import Frequency
from rolling_thunder.repeater_domain import RepeaterIdentity
from rolling_thunder.repeater_repository import RepeaterActiveOverrideRepository
from rolling_thunder.storage import CURRENT_SCHEMA_VERSION, initialize_database


def identity() -> RepeaterIdentity:
    return RepeaterIdentity(
        name="KI6SZ Fairborn",
        rx_frequency=Frequency(hz=51_660_000),
    )


def test_schema_migration_creates_repeater_override_table(tmp_path: Path) -> None:
    database_path = tmp_path / "rolling-thunder.db"
    initialize_database(database_path)

    with sqlite3.connect(database_path) as connection:
        columns = connection.execute(
            "PRAGMA table_info(repeater_active_overrides)"
        ).fetchall()

    assert CURRENT_SCHEMA_VERSION == 17
    assert {str(row[1]) for row in columns} == {
        "repeater_identity",
        "active",
        "updated_at",
    }


def test_active_override_round_trips_and_clear_restores_missing(tmp_path: Path) -> None:
    database_path = tmp_path / "rolling-thunder.db"
    repository = RepeaterActiveOverrideRepository(database_path)
    repeater_identity = identity()

    assert repository.read(repeater_identity) is None

    repository.write(repeater_identity, False)
    assert RepeaterActiveOverrideRepository(database_path).read(repeater_identity) is False

    repository.write(repeater_identity, True)
    assert repository.read(repeater_identity) is True
    assert repository.read_all() == {repeater_identity.stable_key: True}

    repository.clear(repeater_identity)
    assert repository.read(repeater_identity) is None
    assert repository.read_all() == {}
