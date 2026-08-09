"""Tests for pure retained-weather presentation."""

from datetime import UTC, datetime, timedelta, timezone

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
from rolling_thunder.forge_weather_client import ForgeRemoteWeatherHealth
from rolling_thunder.pi_forge_weather_service import (
    PiForgeWeatherErrorKind,
    PiForgeWeatherState,
    PiForgeWeatherStateKind,
)
from rolling_thunder.weather_panel import WeatherPanelController, WeatherPanelStatus

NOW = datetime(2026, 8, 9, 4, 30, tzinfo=UTC)
EASTERN = timezone(timedelta(hours=-4))


def snapshot(*, source_at: datetime | None = None) -> WeatherSnapshot:
    return WeatherSnapshot(
        latitude=39.5244,
        longitude=-84.0625,
        source_at=source_at or NOW - timedelta(minutes=10),
        fetched_at=NOW - timedelta(minutes=9),
        current=WeatherCurrent(
            temperature_c=23.7,
            relative_humidity_percent=90.0,
            condition=WeatherConditionToken.CLOUDY,
            icon=WeatherIconToken.CLOUDY,
            is_day=False,
        ),
        hourly=(
            WeatherHourlyPoint(
                forecast_at=NOW - timedelta(minutes=5),
                temperature_c=23.6,
                precipitation_probability_percent=7.0,
            ),
            WeatherHourlyPoint(
                forecast_at=NOW + timedelta(minutes=30),
                temperature_c=23.3,
                precipitation_probability_percent=2.0,
            ),
            WeatherHourlyPoint(
                forecast_at=NOW + timedelta(hours=1, minutes=30),
                temperature_c=22.7,
                precipitation_probability_percent=1.0,
            ),
            WeatherHourlyPoint(
                forecast_at=NOW + timedelta(hours=2, minutes=30),
                temperature_c=22.2,
                precipitation_probability_percent=12.0,
            ),
        ),
        solar=WeatherSolar(
            sunrise_at=datetime(2026, 8, 9, 10, 43, tzinfo=UTC),
            sunset_at=datetime(2026, 8, 10, 0, 39, tzinfo=UTC),
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


def live_state() -> PiForgeWeatherState:
    weather = snapshot()
    return PiForgeWeatherState(
        kind=PiForgeWeatherStateKind.LIVE,
        snapshot_revision=9,
        snapshot=weather,
        health=ForgeRemoteWeatherHealth(
            status=WeatherProviderStatus.HEALTHY,
            stale=False,
            revision=9,
            last_attempt_at=NOW,
            last_success_at=NOW,
        ),
        stale=False,
        last_attempt_at=NOW,
        last_success_at=NOW,
    )


def controller() -> WeatherPanelController:
    return WeatherPanelController(clock=lambda: NOW, display_timezone=EASTERN)


def test_live_weather_formats_current_solar_and_next_three_future_hours() -> None:
    presentation = controller().update(live_state())

    assert presentation.status is WeatherPanelStatus.LIVE
    assert presentation.detail == "LIVE • 10m OLD"
    assert presentation.has_data is True
    assert presentation.temperature_f == "75°F"
    assert presentation.temperature_c == "24°C"
    assert presentation.humidity == "90%"
    assert presentation.condition == "Cloudy"
    assert presentation.icon == "☁"
    assert presentation.sunrise == "6:43 AM"
    assert presentation.sunset == "8:39 PM"
    assert [item.time for item in presentation.hourly] == [
        "1:00 AM",
        "2:00 AM",
        "3:00 AM",
    ]
    assert [item.temperature_f for item in presentation.hourly] == [
        "74°F",
        "73°F",
        "72°F",
    ]
    assert [item.precipitation for item in presentation.hourly] == ["2%", "1%", "12%"]
    assert presentation.attribution == "Weather data by Open-Meteo.com"


def test_retained_fresh_weather_is_visibly_retained_but_still_usable() -> None:
    weather = snapshot()
    state = PiForgeWeatherState(
        kind=PiForgeWeatherStateKind.RETAINED,
        snapshot_revision=9,
        snapshot=weather,
        stale=False,
        last_success_at=NOW - timedelta(minutes=2),
    )

    presentation = controller().update(state)

    assert presentation.status is WeatherPanelStatus.RETAINED
    assert presentation.detail == "RETAINED • 10m OLD"
    assert presentation.has_data is True
    assert presentation.temperature_f == "75°F"


def test_stale_weather_remains_visible_with_true_source_age() -> None:
    weather = snapshot(source_at=NOW - timedelta(minutes=40))
    state = PiForgeWeatherState(
        kind=PiForgeWeatherStateKind.RETAINED,
        snapshot_revision=9,
        snapshot=weather,
        stale=True,
        last_success_at=NOW - timedelta(minutes=30),
    )

    presentation = controller().update(state)

    assert presentation.status is WeatherPanelStatus.STALE
    assert presentation.detail == "STALE • 40m OLD"
    assert presentation.has_data is True
    assert presentation.source_age == timedelta(minutes=40)


def test_error_keeps_valid_retained_forecast_visible() -> None:
    weather = snapshot(source_at=NOW - timedelta(minutes=22))
    state = PiForgeWeatherState(
        kind=PiForgeWeatherStateKind.RETAINED,
        snapshot_revision=9,
        snapshot=weather,
        stale=False,
        last_attempt_at=NOW,
        last_success_at=NOW - timedelta(minutes=3),
        error_kind=PiForgeWeatherErrorKind.TRANSPORT,
        last_error="Forge unavailable",
    )

    presentation = controller().update(state)

    assert presentation.status is WeatherPanelStatus.ERROR
    assert presentation.detail == "ERROR • TRANSPORT • RETAINED 22m OLD"
    assert presentation.has_data is True
    assert presentation.temperature_f == "75°F"
    assert presentation.hourly[0].available is True


def test_unavailable_and_disabled_states_use_placeholders() -> None:
    unavailable = controller().update(
        PiForgeWeatherState(kind=PiForgeWeatherStateKind.NO_DATA)
    )
    disabled = controller().update(PiForgeWeatherState.disabled())

    assert unavailable.status is WeatherPanelStatus.UNAVAILABLE
    assert unavailable.has_data is False
    assert unavailable.temperature_f == "--°F"
    assert unavailable.hourly[0].available is False
    assert disabled.status is WeatherPanelStatus.DISABLED
    assert disabled.detail == "WEATHER DISABLED"


def test_error_without_snapshot_is_red_error_state_with_no_fake_data() -> None:
    state = PiForgeWeatherState(
        kind=PiForgeWeatherStateKind.NO_DATA,
        stale=True,
        last_attempt_at=NOW,
        error_kind=PiForgeWeatherErrorKind.VALIDATION,
        last_error="Invalid response",
    )

    presentation = controller().update(state)

    assert presentation.status is WeatherPanelStatus.ERROR
    assert presentation.detail == "WEATHER ERROR • VALIDATION"
    assert presentation.has_data is False
    assert presentation.temperature_c == "--°C"


def test_controller_rejects_naive_clock() -> None:
    weather_controller = WeatherPanelController(clock=lambda: NOW.replace(tzinfo=None))

    with pytest.raises(ValueError, match="aware"):
        weather_controller.update(live_state())
