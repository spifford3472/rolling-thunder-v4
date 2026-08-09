"""Regression tests for truthful retained-weather health after Forge restart."""

from datetime import UTC, datetime, timedelta
from typing import cast

from rolling_thunder.forge_mobile_location import (
    ForgeMobileLocationService,
    MobileLocationRecord,
    MobileLocationState,
)
from rolling_thunder.forge_weather import (
    ForgeWeatherProviderError,
    ForgeWeatherService,
    ForgeWeatherState,
    WeatherConditionToken,
    WeatherCurrent,
    WeatherHourlyPoint,
    WeatherIconToken,
    WeatherProviderStatus,
    WeatherSnapshot,
    WeatherSolar,
    WeatherSourceMetadata,
)

BASE_TIME = datetime(2026, 8, 9, 1, 0, tzinfo=UTC)
LOCATION = MobileLocationRecord(
    latitude=39.524492,
    longitude=-84.062475,
    fix_at=BASE_TIME - timedelta(seconds=2),
    received_at=BASE_TIME - timedelta(seconds=1),
)
SOURCE = WeatherSourceMetadata(
    provider_id="test",
    provider_name="Test Weather",
    attribution_text="Test attribution",
    attribution_url="https://weather.example.invalid/",
    license_name="Test licence",
    license_url="https://weather.example.invalid/license",
)


def weather_snapshot(fetched_at: datetime) -> WeatherSnapshot:
    return WeatherSnapshot(
        latitude=LOCATION.latitude,
        longitude=LOCATION.longitude,
        source_at=fetched_at - timedelta(minutes=5),
        fetched_at=fetched_at,
        current=WeatherCurrent(
            temperature_c=24.0,
            relative_humidity_percent=70.0,
            condition=WeatherConditionToken.CLOUDY,
            icon=WeatherIconToken.CLOUDY,
            is_day=False,
        ),
        hourly=tuple(
            WeatherHourlyPoint(
                forecast_at=fetched_at + timedelta(hours=index),
                temperature_c=24.0 - index,
                precipitation_probability_percent=index * 5.0,
            )
            for index in range(1, 4)
        ),
        solar=WeatherSolar(
            sunrise_at=fetched_at.replace(hour=10, minute=43),
            sunset_at=(fetched_at + timedelta(days=1)).replace(hour=0, minute=39),
        ),
        source=SOURCE,
    )


class StaticLocationSource:
    def get_state(self) -> MobileLocationState:
        return MobileLocationState(revision=3, location=LOCATION)


class RecordingProvider:
    def __init__(self, response: WeatherSnapshot | Exception) -> None:
        self.response = response
        self.calls = 0

    def fetch_weather(self, location: MobileLocationRecord) -> WeatherSnapshot:
        assert location == LOCATION
        self.calls += 1
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class RetainedRepository:
    def __init__(self, retained: WeatherSnapshot) -> None:
        self.state = ForgeWeatherState(
            revision=1,
            snapshot=retained,
            provider_status=WeatherProviderStatus.STARTING,
        )

    def load(self) -> ForgeWeatherState:
        return self.state

    def replace(self, snapshot: WeatherSnapshot) -> ForgeWeatherState:
        self.state = ForgeWeatherState(
            revision=self.state.revision + 1,
            snapshot=snapshot,
            provider_status=WeatherProviderStatus.STARTING,
        )
        return self.state


def build_service(
    provider: RecordingProvider,
    repository: RetainedRepository,
) -> ForgeWeatherService:
    return ForgeWeatherService(
        provider,
        repository,
        cast(ForgeMobileLocationService, StaticLocationSource()),
        now=lambda: BASE_TIME + timedelta(minutes=10),
        max_forecast_age_s=1_800.0,
        movement_refresh_km=10.0,
    )


def test_forced_startup_refresh_moves_fresh_retained_weather_to_healthy() -> None:
    retained = weather_snapshot(BASE_TIME)
    replacement = weather_snapshot(BASE_TIME + timedelta(minutes=10))
    provider = RecordingProvider(replacement)
    service = build_service(provider, RetainedRepository(retained))

    assert service.get_state().provider_status is WeatherProviderStatus.STARTING
    assert service.is_stale() is False

    refreshed = service.refresh_if_needed(force=True)

    assert provider.calls == 1
    assert refreshed.revision == 2
    assert refreshed.snapshot == replacement
    assert refreshed.provider_status is WeatherProviderStatus.HEALTHY
    assert refreshed.last_error is None


def test_failed_forced_startup_refresh_retains_snapshot_and_reports_degraded() -> None:
    retained = weather_snapshot(BASE_TIME)
    provider = RecordingProvider(ForgeWeatherProviderError("provider offline"))
    service = build_service(provider, RetainedRepository(retained))

    failed = service.refresh_if_needed(force=True)

    assert provider.calls == 1
    assert failed.revision == 1
    assert failed.snapshot == retained
    assert failed.provider_status is WeatherProviderStatus.DEGRADED
    assert failed.last_error == "provider offline"
