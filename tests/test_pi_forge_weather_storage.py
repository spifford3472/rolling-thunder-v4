"""Focused schema tests for durable Pi retained weather storage."""

import sqlite3
from pathlib import Path

from rolling_thunder.storage import CURRENT_SCHEMA_VERSION, initialize_database


def test_current_schema_contains_singleton_weather_cache(tmp_path: Path) -> None:
    database = tmp_path / "rolling-thunder.db"
    version = initialize_database(database)
    assert version == CURRENT_SCHEMA_VERSION

    with sqlite3.connect(database) as connection:
        columns = connection.execute("PRAGMA table_info(forge_weather_cache)").fetchall()
        stored = connection.execute(
            "SELECT schema_version FROM schema_metadata WHERE singleton_id = 1"
        ).fetchone()

    assert stored == (CURRENT_SCHEMA_VERSION,)
    assert {row[1] for row in columns} == {
        "singleton_id",
        "revision",
        "source_at",
        "received_at",
        "payload_json",
        "updated_at",
    }
