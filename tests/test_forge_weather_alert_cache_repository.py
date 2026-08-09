"""Tests for the Pi retained Forge weather-alert cache."""

from datetime import UTC, datetime, timedelta

import pytest

from rolling_thunder.forge_weather_alert_cache_repository import (
    ForgeWeatherAlertCacheRepository,
)
from rolling_thunder.forge_weather_alert_client import (
    ForgeRemoteWeatherAlertHealth,
    ForgeWeatherAlertClientResult,
)
from rolling_thunder.forge_weather_alerts import (
    WeatherAlertApplicability,
    WeatherAlertProviderStatus,
    WeatherAlertSnapshot,
    WeatherAlertSourceMetadata,
)
from rolling_thunder.storage import StorageError

NOW = datetime(2026, 8, 9, 6, 0, tzinfo=UTC)


def result(
    revision: int = 3,
) -> ForgeWeatherAlertClientResult:
    return ForgeWeatherAlertClientResult(
        revision=revision,
        snapshot=WeatherAlertSnapshot(
            latitude=39.5245,
            longitude=-84.0625,
            fetched_at=NOW - timedelta(seconds=3),
            alerts=(),
            source=WeatherAlertSourceMetadata(
                provider_id="nws",
                provider_name="National Weather Service",
                attribution_text="National Weather Service alerts",
                attribution_url="https://www.weather.gov/",
            ),
        ),
        health=ForgeRemoteWeatherAlertHealth(
            status=WeatherAlertProviderStatus.HEALTHY,
            applicability=(
                WeatherAlertApplicability.VERIFIED_CURRENT
            ),
            revision=revision,
        ),
        received_at=NOW,
    )


def test_cache_round_trip_and_replace(tmp_path) -> None:
    database = tmp_path / "rolling-thunder.db"
    repository = ForgeWeatherAlertCacheRepository(database)

    assert repository.load() is None

    repository.replace(result(3))
    assert repository.load() == result(3)

    repository.replace(result(4))
    assert repository.load() == result(4)


def test_cache_rejects_snapshotless_result(tmp_path) -> None:
    repository = ForgeWeatherAlertCacheRepository(
        tmp_path / "rolling-thunder.db"
    )

    empty = ForgeWeatherAlertClientResult(
        revision=0,
        snapshot=None,
        health=ForgeRemoteWeatherAlertHealth(
            status=WeatherAlertProviderStatus.STARTING,
            applicability=WeatherAlertApplicability.UNAVAILABLE,
            revision=0,
        ),
        received_at=NOW,
    )

    with pytest.raises(
        StorageError,
        match="requires a snapshot",
    ):
        repository.replace(empty)
