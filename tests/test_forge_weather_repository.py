"""Tests for transactional Forge weather SQLite persistence."""

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from rolling_thunder.forge_weather import (
    ForgeWeatherStorageError,
    WeatherConditionToken,
    WeatherCurrent,
    WeatherHourlyPoint,
    WeatherIconToken,
    WeatherSnapshot,
    WeatherSolar,
    WeatherSourceMetadata,
)
from rolling_thunder.forge_weather_repository import SqliteForgeWeatherRepository

BASE_TIME = datetime(2026, 8, 9, 0, 35, tzinfo=UTC)


def snapshot(*, temperature_c: float = 22.0) -> WeatherSnapshot:
    return WeatherSnapshot(
        latitude=39.524492,
        longitude=-84.062475,
        source_at=BASE_TIME - timedelta(minutes=5),
        fetched_at=BASE_TIME,
        current=WeatherCurrent(
            temperature_c=temperature_c,
            relative_humidity_percent=70.0,
            condition=WeatherConditionToken.CLEAR,
            icon=WeatherIconToken.CLEAR_NIGHT,
            is_day=False,
        ),
        hourly=(
            WeatherHourlyPoint(
                forecast_at=BASE_TIME + timedelta(hours=1),
                temperature_c=21.0,
                precipitation_probability_percent=10,
            ),
            WeatherHourlyPoint(
                forecast_at=BASE_TIME + timedelta(hours=2),
                temperature_c=20.0,
                precipitation_probability_percent=20,
            ),
            WeatherHourlyPoint(
                forecast_at=BASE_TIME + timedelta(hours=3),
                temperature_c=19.0,
                precipitation_probability_percent=30,
            ),
        ),
        solar=WeatherSolar(
            sunrise_at=datetime(2026, 8, 9, 10, 42, tzinfo=UTC),
            sunset_at=datetime(2026, 8, 10, 0, 41, tzinfo=UTC),
        ),
        source=WeatherSourceMetadata(
            provider_id="open_meteo",
            provider_name="Open-Meteo",
            attribution_text="Weather data by Open-Meteo.com",
            attribution_url="https://open-meteo.com/",
            license_name="CC BY 4.0",
            license_url="https://creativecommons.org/licenses/by/4.0/",
        ),
    )


def table_names(path: Path) -> set[str]:
    with sqlite3.connect(path) as connection:
        return {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }


def test_repository_round_trips_and_advances_singleton_revision(tmp_path: Path) -> None:
    database = tmp_path / "forge.db"
    repository = SqliteForgeWeatherRepository(database)

    assert repository.load() is None
    first = repository.replace(snapshot())
    second = repository.replace(snapshot(temperature_c=23.0))

    assert first.revision == 1
    assert second.revision == 2
    assert second.snapshot is not None
    assert second.snapshot.current.temperature_c == 23.0

    reloaded = SqliteForgeWeatherRepository(database).load()
    assert reloaded is not None
    assert reloaded.revision == 2
    assert reloaded.snapshot == second.snapshot
    assert {
        "forge_weather_schema_metadata",
        "forge_weather_snapshot",
    } <= table_names(database)


def test_repository_uses_existing_forge_database_without_changing_spot_schema(
    tmp_path: Path,
) -> None:
    database = tmp_path / "forge.db"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE forge_schema_metadata (singleton_id INTEGER PRIMARY KEY, schema_version INTEGER)"
        )
        connection.execute(
            "INSERT INTO forge_schema_metadata VALUES (1, 1)"
        )
        connection.commit()

    SqliteForgeWeatherRepository(database).replace(snapshot())

    with sqlite3.connect(database) as connection:
        version = connection.execute(
            "SELECT schema_version FROM forge_schema_metadata WHERE singleton_id = 1"
        ).fetchone()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()

    assert version == (1,)
    assert integrity == ("ok",)


def test_repository_revalidates_persisted_snapshot(tmp_path: Path) -> None:
    database = tmp_path / "forge.db"
    repository = SqliteForgeWeatherRepository(database)
    repository.replace(snapshot())
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE forge_weather_snapshot SET snapshot_json = ? WHERE singleton_id = 1",
            ('{"latitude":999}',),
        )
        connection.commit()

    with pytest.raises(ForgeWeatherStorageError, match="invalid data"):
        repository.load()


def test_repository_rejects_application_database(tmp_path: Path) -> None:
    database = tmp_path / "rolling-thunder.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE contacts (id INTEGER PRIMARY KEY)")
        connection.commit()

    with pytest.raises(
        ForgeWeatherStorageError,
        match="Refusing to initialize Forge weather",
    ):
        SqliteForgeWeatherRepository(database)
