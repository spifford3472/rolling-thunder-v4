"""Pure presentation projection for retained Pi weather state."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, tzinfo
from enum import StrEnum

from rolling_thunder.forge_weather import WeatherIconToken, WeatherSnapshot
from rolling_thunder.pi_forge_weather_service import (
    PiForgeWeatherErrorKind,
    PiForgeWeatherState,
    PiForgeWeatherStateKind,
)

Clock = Callable[[], datetime]


class WeatherPanelStatus(StrEnum):
    """Operator-facing availability/health states for weather presentation."""

    DISABLED = "disabled"
    LIVE = "live"
    RETAINED = "retained"
    STALE = "stale"
    UNAVAILABLE = "unavailable"
    ERROR = "error"


@dataclass(frozen=True)
class HourlyWeatherPresentation:
    """One compact hourly forecast cell."""

    available: bool
    time: str
    temperature_f: str
    temperature_c: str
    precipitation: str


@dataclass(frozen=True)
class WeatherPanelPresentation:
    """Immutable presentation consumed by both Tkinter and live-map information."""

    status: WeatherPanelStatus
    status_label: str
    detail: str
    has_data: bool
    temperature_f: str
    temperature_c: str
    humidity: str
    condition: str
    icon: str
    sunrise: str
    sunset: str
    hourly: tuple[HourlyWeatherPresentation, ...]
    attribution: str
    source_at: datetime | None
    source_age: timedelta | None


_ICON_GLYPHS: dict[WeatherIconToken, str] = {
    WeatherIconToken.CLEAR_DAY: "☀",
    WeatherIconToken.CLEAR_NIGHT: "☾",
    WeatherIconToken.PARTLY_CLOUDY_DAY: "☁",
    WeatherIconToken.PARTLY_CLOUDY_NIGHT: "☁",
    WeatherIconToken.CLOUDY: "☁",
    WeatherIconToken.FOG: "≋",
    WeatherIconToken.DRIZZLE: "☂",
    WeatherIconToken.RAIN: "☂",
    WeatherIconToken.FREEZING_RAIN: "❄",
    WeatherIconToken.SNOW: "❄",
    WeatherIconToken.SHOWERS: "☂",
    WeatherIconToken.THUNDERSTORM: "⚡",
    WeatherIconToken.UNKNOWN: "?",
}


class WeatherPanelController:
    """Project immutable #164 state into a deterministic display model without I/O."""

    def __init__(
        self,
        *,
        clock: Clock | None = None,
        display_timezone: tzinfo | None = None,
    ) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))
        self._display_timezone = display_timezone

    def update(self, state: PiForgeWeatherState) -> WeatherPanelPresentation:
        """Build one weather presentation without network, storage, or provider work."""
        now = self._aware_now()
        snapshot = state.snapshot

        if snapshot is None:
            status = self._status_without_snapshot(state)
            detail = self._detail_without_snapshot(state, status)
            return WeatherPanelPresentation(
                status=status,
                status_label=status.value.upper(),
                detail=detail,
                has_data=False,
                temperature_f="--°F",
                temperature_c="--°C",
                humidity="--%",
                condition="Unavailable",
                icon="?",
                sunrise="--:--",
                sunset="--:--",
                hourly=self._empty_hourly(),
                attribution="",
                source_at=None,
                source_age=None,
            )

        age = self._age(now, snapshot.source_at)
        status = self._status_with_snapshot(state)
        detail = self._detail_with_snapshot(state, status, age)
        local_timezone = self._timezone_for(now)

        return WeatherPanelPresentation(
            status=status,
            status_label=status.value.upper(),
            detail=detail,
            has_data=True,
            temperature_f=self._format_fahrenheit(snapshot.current.temperature_c),
            temperature_c=self._format_celsius(snapshot.current.temperature_c),
            humidity=f"{round(snapshot.current.relative_humidity_percent):d}%",
            condition=snapshot.current.condition.value.replace("_", " ").title(),
            icon=_ICON_GLYPHS[snapshot.current.icon],
            sunrise=self._format_local_time(snapshot.solar.sunrise_at, local_timezone),
            sunset=self._format_local_time(snapshot.solar.sunset_at, local_timezone),
            hourly=self._hourly(snapshot, now, local_timezone),
            attribution=snapshot.source.attribution_text,
            source_at=snapshot.source_at,
            source_age=age,
        )

    @staticmethod
    def _status_without_snapshot(state: PiForgeWeatherState) -> WeatherPanelStatus:
        if state.kind is PiForgeWeatherStateKind.DISABLED:
            return WeatherPanelStatus.DISABLED
        if state.error_kind is not None:
            return WeatherPanelStatus.ERROR
        return WeatherPanelStatus.UNAVAILABLE

    @staticmethod
    def _status_with_snapshot(state: PiForgeWeatherState) -> WeatherPanelStatus:
        if state.error_kind is not None:
            return WeatherPanelStatus.ERROR
        if state.stale:
            return WeatherPanelStatus.STALE
        if state.kind is PiForgeWeatherStateKind.RETAINED:
            return WeatherPanelStatus.RETAINED
        return WeatherPanelStatus.LIVE

    @staticmethod
    def _detail_without_snapshot(
        state: PiForgeWeatherState,
        status: WeatherPanelStatus,
    ) -> str:
        if status is WeatherPanelStatus.DISABLED:
            return "WEATHER DISABLED"
        if status is WeatherPanelStatus.ERROR:
            error = WeatherPanelController._error_label(state.error_kind)
            return f"WEATHER ERROR • {error}"
        return "WEATHER UNAVAILABLE"

    @staticmethod
    def _detail_with_snapshot(
        state: PiForgeWeatherState,
        status: WeatherPanelStatus,
        age: timedelta,
    ) -> str:
        age_text = WeatherPanelController._format_age(age)
        if status is WeatherPanelStatus.ERROR:
            error = WeatherPanelController._error_label(state.error_kind)
            return f"ERROR • {error} • RETAINED {age_text} OLD"
        if status is WeatherPanelStatus.STALE:
            return f"STALE • {age_text} OLD"
        if status is WeatherPanelStatus.RETAINED:
            return f"RETAINED • {age_text} OLD"
        return f"LIVE • {age_text} OLD"

    @staticmethod
    def _error_label(error_kind: PiForgeWeatherErrorKind | None) -> str:
        if error_kind is None:
            return "UNKNOWN"
        return error_kind.value.replace("_", " ").upper()

    @staticmethod
    def _format_age(age: timedelta) -> str:
        total_minutes = max(0, int(age.total_seconds() // 60))
        if total_minutes < 1:
            return "<1m"
        hours, minutes = divmod(total_minutes, 60)
        if hours == 0:
            return f"{minutes}m"
        if minutes == 0:
            return f"{hours}h"
        return f"{hours}h {minutes}m"

    def _hourly(
        self,
        snapshot: WeatherSnapshot,
        now: datetime,
        display_timezone: tzinfo,
    ) -> tuple[HourlyWeatherPresentation, ...]:
        future = [point for point in snapshot.hourly if point.forecast_at > now]
        cells = [
            HourlyWeatherPresentation(
                available=True,
                time=self._format_local_time(point.forecast_at, display_timezone),
                temperature_f=self._format_fahrenheit(point.temperature_c),
                temperature_c=self._format_celsius(point.temperature_c),
                precipitation=f"{round(point.precipitation_probability_percent):d}%",
            )
            for point in future[:3]
        ]
        while len(cells) < 3:
            cells.append(self._empty_hourly_cell())
        return tuple(cells)

    @staticmethod
    def _empty_hourly() -> tuple[HourlyWeatherPresentation, ...]:
        return tuple(WeatherPanelController._empty_hourly_cell() for _ in range(3))

    @staticmethod
    def _empty_hourly_cell() -> HourlyWeatherPresentation:
        return HourlyWeatherPresentation(
            available=False,
            time="--:--",
            temperature_f="--°F",
            temperature_c="--°C",
            precipitation="--%",
        )

    @staticmethod
    def _format_fahrenheit(temperature_c: float) -> str:
        return f"{round((temperature_c * 9.0 / 5.0) + 32.0):d}°F"

    @staticmethod
    def _format_celsius(temperature_c: float) -> str:
        return f"{round(temperature_c):d}°C"

    @staticmethod
    def _format_local_time(value: datetime, display_timezone: tzinfo) -> str:
        return value.astimezone(display_timezone).strftime("%I:%M %p").lstrip("0")

    def _timezone_for(self, now: datetime) -> tzinfo:
        if self._display_timezone is not None:
            return self._display_timezone
        local_timezone = now.astimezone().tzinfo
        if local_timezone is None:
            return UTC
        return local_timezone

    @staticmethod
    def _age(now: datetime, source_at: datetime) -> timedelta:
        return max(timedelta(0), now.astimezone(UTC) - source_at.astimezone(UTC))

    def _aware_now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Weather panel clock must return an aware datetime.")
        return now
