"""Tests proving map Local Temp consumes the shared weather presentation."""

from datetime import UTC, datetime, timedelta

from rolling_thunder.live_map import GeoPoint, LiveMapGpsStatus, LiveMapPresentation
from rolling_thunder.live_map_info import LiveMapInfoController
from rolling_thunder.live_map_service import LiveMapSnapshot, MapDataStatus
from rolling_thunder.live_map_ui import live_map_info_lines
from rolling_thunder.weather_panel import (
    HourlyWeatherPresentation,
    WeatherPanelPresentation,
    WeatherPanelStatus,
)

NOW = datetime(2026, 8, 9, 4, 30, tzinfo=UTC)


def map_presentation() -> LiveMapPresentation:
    return LiveMapPresentation(
        status=LiveMapGpsStatus.READY,
        position=GeoPoint(39.5244, -84.0625),
        grid="EM79xm",
        detail="GPS READY",
        fix_time=NOW,
        is_current=True,
    )


def map_snapshot() -> LiveMapSnapshot:
    return LiveMapSnapshot(
        status=MapDataStatus.READY,
        viewport=None,
        tiles=(),
        detail="MAP READY",
        updated_at=NOW,
    )


def weather_presentation(*, has_data: bool = True) -> WeatherPanelPresentation:
    empty_hour = HourlyWeatherPresentation(
        available=False,
        time="--:--",
        temperature_f="--°F",
        temperature_c="--°C",
        precipitation="--%",
    )
    return WeatherPanelPresentation(
        status=(WeatherPanelStatus.STALE if has_data else WeatherPanelStatus.UNAVAILABLE),
        status_label=("STALE" if has_data else "UNAVAILABLE"),
        detail=("STALE • 40m OLD" if has_data else "WEATHER UNAVAILABLE"),
        has_data=has_data,
        temperature_f=("75°F" if has_data else "--°F"),
        temperature_c=("24°C" if has_data else "--°C"),
        humidity=("90%" if has_data else "--%"),
        condition=("Cloudy" if has_data else "Unavailable"),
        icon=("☁" if has_data else "?"),
        sunrise="6:43 AM",
        sunset="8:39 PM",
        hourly=(empty_hour, empty_hour, empty_hour),
        attribution=("Weather data by Open-Meteo.com" if has_data else ""),
        source_at=(NOW - timedelta(minutes=40) if has_data else None),
        source_age=(timedelta(minutes=40) if has_data else None),
    )


def test_map_local_temp_is_exactly_shared_weather_panel_temperature() -> None:
    weather = weather_presentation()
    info = LiveMapInfoController(clock=lambda: NOW).update(
        map_presentation(),
        map_snapshot(),
        weather,
    )

    assert info.temperature_f == weather.temperature_f == "75°F"
    assert info.temperature_c == weather.temperature_c == "24°C"
    assert info.temperature_detail == weather.detail == "STALE • 40m OLD"
    assert live_map_info_lines(info)[-1] == "TEMP   75°F / 24°C"


def test_map_uses_placeholders_when_shared_weather_has_no_data() -> None:
    weather = weather_presentation(has_data=False)
    info = LiveMapInfoController(clock=lambda: NOW).update(
        map_presentation(),
        map_snapshot(),
        weather,
    )

    assert info.temperature_f == "--°F"
    assert info.temperature_c == "--°C"
    assert info.temperature_detail == "WEATHER UNAVAILABLE"
    assert live_map_info_lines(info)[-1] == "TEMP   --°F / --°C"
