"""Tests for transactional Forge weather-alert persistence."""

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from rolling_thunder.forge_weather_alert_repository import (
    SqliteForgeWeatherAlertRepository,
)
from rolling_thunder.forge_weather_alerts import (
    ForgeWeatherAlertStorageError,
    WeatherAlertApplicability,
    WeatherAlertCertainty,
    WeatherAlertProviderStatus,
    WeatherAlertRecord,
    WeatherAlertSeverity,
    WeatherAlertSnapshot,
    WeatherAlertSourceMetadata,
    WeatherAlertUrgency,
)

BASE_TIME = datetime(2026, 8, 9, 5, 30, tzinfo=UTC)
SOURCE = WeatherAlertSourceMetadata(
    provider_id="nws",
    provider_name="National Weather Service",
    attribution_text="National Weather Service alerts",
    attribution_url="https://www.weather.gov/",
)


def alert(alert_id: str = "https://api.weather.gov/alerts/test") -> WeatherAlertRecord:
    return WeatherAlertRecord(
        alert_id=alert_id,
        event="Tornado Warning",
        severity=WeatherAlertSeverity.EXTREME,
        urgency=WeatherAlertUrgency.IMMEDIATE,
        certainty=WeatherAlertCertainty.OBSERVED,
        headline="Tornado Warning issued for Test Area",
        area_description="Test Area",
        sent_at=BASE_TIME - timedelta(minutes=2),
        effective_at=BASE_TIME - timedelta(minutes=2),
        expires_at=BASE_TIME + timedelta(minutes=30),
    )


def snapshot(
    *,
    alerts: tuple[WeatherAlertRecord, ...] = (),
    latitude: float = 39.5245,
) -> WeatherAlertSnapshot:
    return WeatherAlertSnapshot(
        latitude=latitude,
        longitude=-84.0625,
        fetched_at=BASE_TIME,
        alerts=alerts,
        source=SOURCE,
    )


def test_repository_starts_empty_and_round_trips_empty_active_set(tmp_path: Path) -> None:
    database = tmp_path / "forge.db"
    repository = SqliteForgeWeatherAlertRepository(database)

    assert repository.load() is None

    stored = repository.replace(snapshot())
    loaded = repository.load()

    assert stored.revision == 1
    assert stored.snapshot == snapshot()
    assert loaded is not None
    assert loaded.revision == 1
    assert loaded.snapshot == snapshot()
    assert loaded.provider_status is WeatherAlertProviderStatus.STARTING
    assert loaded.applicability is WeatherAlertApplicability.RETAINED_UNVERIFIED


def test_repository_replaces_complete_set_and_advances_revision(tmp_path: Path) -> None:
    repository = SqliteForgeWeatherAlertRepository(tmp_path / "forge.db")

    first = repository.replace(snapshot(alerts=(alert("alert-1"),)))
    second_snapshot = snapshot(
        alerts=(alert("alert-2"),),
        latitude=39.6500,
    )
    second = repository.replace(second_snapshot)
    loaded = repository.load()

    assert first.revision == 1
    assert second.revision == 2
    assert loaded is not None
    assert loaded.revision == 2
    assert loaded.snapshot == second_snapshot


def test_repository_rejects_application_database(tmp_path: Path) -> None:
    database = tmp_path / "rolling-thunder.db"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE schema_metadata (singleton_id INTEGER PRIMARY KEY)"
        )
        connection.commit()

    with pytest.raises(
        ForgeWeatherAlertStorageError,
        match="Rolling Thunder application database",
    ):
        SqliteForgeWeatherAlertRepository(database)


def test_repository_rejects_unknown_alert_schema_version(tmp_path: Path) -> None:
    database = tmp_path / "forge.db"
    SqliteForgeWeatherAlertRepository(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE forge_weather_alert_schema_metadata SET schema_version = 99"
        )
        connection.commit()

    with pytest.raises(ForgeWeatherAlertStorageError, match="schema version"):
        SqliteForgeWeatherAlertRepository(database)


def test_repository_rejects_corrupt_retained_snapshot(tmp_path: Path) -> None:
    database = tmp_path / "forge.db"
    repository = SqliteForgeWeatherAlertRepository(database)
    repository.replace(snapshot(alerts=(alert(),)))
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE forge_weather_alert_snapshot SET snapshot_json = ?",
            ("not-json",),
        )
        connection.commit()

    with pytest.raises(ForgeWeatherAlertStorageError, match="invalid data"):
        repository.load()
