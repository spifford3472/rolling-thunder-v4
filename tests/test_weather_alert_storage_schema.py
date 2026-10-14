"""Tests for weather-alert persistence across the current application schema."""

import sqlite3

import rolling_thunder.storage as storage_module
from rolling_thunder.storage import (
    CURRENT_SCHEMA_VERSION,
    initialize_database,
)


def table_names(database) -> set[str]:
    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
            """
        ).fetchall()

    return {str(row[0]) for row in rows}


def test_current_schema_retains_alert_cache_and_notification_ledger(
    tmp_path,
) -> None:
    database = tmp_path / "rolling-thunder.db"

    version = initialize_database(database)

    assert CURRENT_SCHEMA_VERSION == 21
    assert version == CURRENT_SCHEMA_VERSION

    tables = table_names(database)

    assert "forge_weather_alert_cache" in tables
    assert "weather_alert_notification_ledger" in tables


def test_version_9_database_upgrades_without_losing_weather_cache(
    tmp_path,
    monkeypatch,
) -> None:
    database = tmp_path / "rolling-thunder.db"
    current_schema_version = storage_module.CURRENT_SCHEMA_VERSION

    monkeypatch.setattr(storage_module, "CURRENT_SCHEMA_VERSION", 9)
    assert initialize_database(database) == 9
    monkeypatch.setattr(
        storage_module,
        "CURRENT_SCHEMA_VERSION",
        current_schema_version,
    )

    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            INSERT INTO forge_weather_cache (
                singleton_id,
                revision,
                source_at,
                received_at,
                payload_json
            )
            VALUES (
                1,
                11,
                '2026-08-09T04:45:00Z',
                '2026-08-09T05:20:23Z',
                '{}'
            )
            """
        )
        connection.commit()

    assert initialize_database(database) == CURRENT_SCHEMA_VERSION

    with sqlite3.connect(database) as connection:
        version = connection.execute(
            """
            SELECT schema_version
            FROM schema_metadata
            WHERE singleton_id = 1
            """
        ).fetchone()

        weather = connection.execute(
            """
            SELECT revision
            FROM forge_weather_cache
            WHERE singleton_id = 1
            """
        ).fetchone()

    assert version == (CURRENT_SCHEMA_VERSION,)
    assert weather == (11,)

    tables = table_names(database)
    assert "forge_weather_alert_cache" in tables
    assert "weather_alert_notification_ledger" in tables
    assert "repeater_active_overrides" in tables
