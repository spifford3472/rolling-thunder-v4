"""Tests for the Pi SQLite retained Forge weather cache."""

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from rolling_thunder.forge_weather import (
    WeatherConditionToken,
    WeatherCurrent,
    WeatherHourlyPoint,
    WeatherIconToken,
    WeatherProviderStatus,
    WeatherSnapshot,
    WeatherSolar,
    WeatherSourceMetadata,
)
from rolling_thunder.forge_weather_cache_repository import ForgeWeatherCacheRepository
from rolling_thunder.forge_weather_client import (
    ForgeRemoteWeatherHealth,
    ForgeWeatherClientResult,
)
from rolling_thunder.storage import StorageError

BASE_TIME = datetime(2026, 8, 9, 3, 35, tzinfo=UTC)


def result() -> ForgeWeatherClientResult:
    source_at = BASE_TIME - timedelta(minutes=5)
    weather = WeatherSnapshot(
        latitude=39.52449,
        longitude=-84.062475,
        source_at=source_at,
        fetched_at=source_at + timedelta(minutes=1),
        current=WeatherCurrent(
            temperature_c=22.0,
            relative_humidity_percent=64.0,
            condition=WeatherConditionToken.CLEAR,
            icon=WeatherIconToken.CLEAR_NIGHT,
            is_day=False,
        ),
        hourly=tuple(
            WeatherHourlyPoint(
                forecast_at=source_at + timedelta(hours=hour),
                temperature_c=22.0 - hour,
                precipitation_probability_percent=0.0,
            )
            for hour in (1, 2, 3)
        ),
        solar=WeatherSolar(
            sunrise_at=source_at + timedelta(hours=7),
            sunset_at=source_at + timedelta(hours=20),
        ),
        source=WeatherSourceMetadata(
            provider_id="test",
            provider_name="Test",
            attribution_text="Test weather",
            attribution_url="https://example.invalid/weather",
            license_name="Test License",
            license_url="https://example.invalid/license",
        ),
    )
    return ForgeWeatherClientResult(
        revision=7,
        stale=False,
        snapshot=weather,
        health=ForgeRemoteWeatherHealth(
            status=WeatherProviderStatus.HEALTHY,
            stale=False,
            revision=7,
            last_attempt_at=BASE_TIME,
            last_success_at=BASE_TIME,
        ),
        received_at=BASE_TIME,
    )


def test_repository_round_trips_one_complete_last_good_result(tmp_path: Path) -> None:
    database = tmp_path / "rolling-thunder.db"
    repository = ForgeWeatherCacheRepository(database)
    expected = result()

    assert repository.load() is None
    repository.replace(expected)

    loaded = repository.load()
    assert loaded == expected
    assert loaded is not None
    assert loaded.snapshot is not None
    assert loaded.snapshot.source_at == expected.snapshot.source_at  # type: ignore[union-attr]


def test_repository_replaces_prior_snapshot_atomically(tmp_path: Path) -> None:
    database = tmp_path / "rolling-thunder.db"
    repository = ForgeWeatherCacheRepository(database)
    first = result()
    second = first.model_copy(
        update={
            "revision": 8,
            "health": first.health.model_copy(update={"revision": 8}),
            "received_at": BASE_TIME + timedelta(minutes=15),
        }
    )

    repository.replace(first)
    repository.replace(second)

    assert repository.load() == second
    with sqlite3.connect(database) as connection:
        count = connection.execute("SELECT COUNT(*) FROM forge_weather_cache").fetchone()
    assert count == (1,)


def test_repository_rejects_snapshotless_results(tmp_path: Path) -> None:
    database = tmp_path / "rolling-thunder.db"
    repository = ForgeWeatherCacheRepository(database)
    empty = ForgeWeatherClientResult(
        revision=0,
        stale=True,
        snapshot=None,
        health=ForgeRemoteWeatherHealth(
            status=WeatherProviderStatus.STARTING,
            stale=True,
            revision=0,
        ),
        received_at=BASE_TIME,
    )

    with pytest.raises(StorageError, match="only accepts"):
        repository.replace(empty)


def test_repository_revalidates_payload_and_metadata_on_load(tmp_path: Path) -> None:
    database = tmp_path / "rolling-thunder.db"
    repository = ForgeWeatherCacheRepository(database)
    repository.replace(result())

    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE forge_weather_cache SET revision = 99 WHERE singleton_id = 1"
        )
        connection.commit()

    with pytest.raises(StorageError, match="metadata does not match"):
        repository.load()
