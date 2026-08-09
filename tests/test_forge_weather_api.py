"""Tests for the versioned read-only retained Forge weather endpoint."""

from datetime import UTC, datetime, timedelta
from json import loads

from rolling_thunder.forge_spot_aggregation import (
    ForgeAggregationState,
    ForgeProviderHealth,
    ForgeProviderHealthStatus,
)
from rolling_thunder.forge_spot_api import ForgeSpotApiApplication
from rolling_thunder.forge_weather import (
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
from rolling_thunder.spot_domain import SpotProvider, SpotSnapshot

BASE_TIME = datetime(2026, 8, 9, 0, 35, tzinfo=UTC)


class StaticSpotStateSource:
    def __init__(self) -> None:
        self.reads = 0
        self.state = ForgeAggregationState(
            revision=12,
            snapshot=SpotSnapshot.empty(generated_at=BASE_TIME),
            providers=(
                ForgeProviderHealth(
                    provider=SpotProvider.POTA,
                    status=ForgeProviderHealthStatus.HEALTHY,
                    active_spot_count=0,
                    last_attempt_at=BASE_TIME,
                    last_success_at=BASE_TIME,
                ),
            ),
        )

    def get_state(self) -> ForgeAggregationState:
        self.reads += 1
        return self.state


class StaticWeatherStateSource:
    def __init__(self, state: ForgeWeatherState, *, stale: bool) -> None:
        self.state = state
        self.stale = stale
        self.reads = 0
        self.stale_reads = 0

    def get_state(self) -> ForgeWeatherState:
        self.reads += 1
        return self.state

    def is_stale(self) -> bool:
        self.stale_reads += 1
        return self.stale


def snapshot() -> WeatherSnapshot:
    return WeatherSnapshot(
        latitude=39.524492,
        longitude=-84.062475,
        source_at=BASE_TIME - timedelta(minutes=5),
        fetched_at=BASE_TIME,
        current=WeatherCurrent(
            temperature_c=22.4,
            relative_humidity_percent=78,
            condition=WeatherConditionToken.PARTLY_CLOUDY,
            icon=WeatherIconToken.PARTLY_CLOUDY_NIGHT,
            is_day=False,
        ),
        hourly=(
            WeatherHourlyPoint(
                forecast_at=BASE_TIME + timedelta(hours=1),
                temperature_c=22.1,
                precipitation_probability_percent=10,
            ),
            WeatherHourlyPoint(
                forecast_at=BASE_TIME + timedelta(hours=2),
                temperature_c=21.7,
                precipitation_probability_percent=20,
            ),
            WeatherHourlyPoint(
                forecast_at=BASE_TIME + timedelta(hours=3),
                temperature_c=21.0,
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


def weather_state() -> ForgeWeatherState:
    return ForgeWeatherState(
        revision=3,
        snapshot=snapshot(),
        provider_status=WeatherProviderStatus.HEALTHY,
        last_attempt_at=BASE_TIME,
        last_success_at=BASE_TIME,
    )


def test_weather_endpoint_serves_retained_normalized_snapshot_without_spot_read() -> None:
    spots = StaticSpotStateSource()
    weather = StaticWeatherStateSource(weather_state(), stale=False)
    app = ForgeSpotApiApplication(spots, weather=weather)

    response = app.handle("GET", "/api/v1/weather")
    payload = loads(response.body)

    assert response.status_code == 200
    assert payload["api_schema_version"] == "1"
    assert payload["revision"] == 3
    assert payload["stale"] is False
    assert payload["snapshot"]["current"]["temperature_c"] == 22.4
    assert payload["snapshot"]["current"]["relative_humidity_percent"] == 78
    assert payload["snapshot"]["current"]["condition"] == "partly_cloudy"
    assert payload["snapshot"]["current"]["icon"] == "partly_cloudy_night"
    assert len(payload["snapshot"]["hourly"]) == 3
    assert payload["snapshot"]["source"]["provider_id"] == "open_meteo"
    assert payload["snapshot"]["source"]["attribution_text"] == (
        "Weather data by Open-Meteo.com"
    )
    assert payload["health"]["status"] == "healthy"
    assert spots.reads == 0
    assert weather.reads == 1
    assert weather.stale_reads == 1


def test_health_includes_weather_health_without_changing_core_service_status() -> None:
    spots = StaticSpotStateSource()
    degraded = weather_state().model_copy(
        update={
            "provider_status": WeatherProviderStatus.DEGRADED,
            "last_error": "provider offline",
        }
    )
    weather = StaticWeatherStateSource(degraded, stale=True)
    app = ForgeSpotApiApplication(spots, weather=weather)

    response = app.handle("GET", "/api/v1/health")
    payload = loads(response.body)

    assert response.status_code == 200
    assert payload["service_status"] == "healthy"
    assert payload["weather"]["status"] == "degraded"
    assert payload["weather"]["stale"] is True
    assert payload["weather"]["revision"] == 3
    assert payload["weather"]["last_error"] == "provider offline"


def test_weather_endpoint_is_get_only_and_disabled_weather_is_explicit() -> None:
    spots = StaticSpotStateSource()
    enabled = ForgeSpotApiApplication(
        spots,
        weather=StaticWeatherStateSource(weather_state(), stale=False),
    )
    disabled = ForgeSpotApiApplication(spots)

    wrong_method = enabled.handle("POST", "/api/v1/weather")
    unavailable = disabled.handle("GET", "/api/v1/weather")

    assert wrong_method.status_code == 405
    assert dict(wrong_method.headers)["Allow"] == "GET"
    assert unavailable.status_code == 503
    assert loads(unavailable.body)["error"] == "weather_unavailable"


def test_empty_weather_state_is_returned_as_truthful_stale_unavailable_state() -> None:
    spots = StaticSpotStateSource()
    weather = StaticWeatherStateSource(
        ForgeWeatherState(
            revision=0,
            provider_status=WeatherProviderStatus.UNAVAILABLE,
            last_error="No retained mobile location is available for weather refresh.",
        ),
        stale=True,
    )
    app = ForgeSpotApiApplication(spots, weather=weather)

    response = app.handle("GET", "/api/v1/weather")
    payload = loads(response.body)

    assert response.status_code == 200
    assert payload["revision"] == 0
    assert payload["snapshot"] is None
    assert payload["stale"] is True
    assert payload["health"]["status"] == "unavailable"
