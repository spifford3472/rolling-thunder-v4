"""Open-Meteo adapter for provider-neutral retained Forge weather."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from json import JSONDecodeError, loads
from urllib.error import URLError
from urllib.parse import urlencode

from rolling_thunder.forge_mobile_location import MobileLocationRecord
from rolling_thunder.forge_weather import (
    ForgeWeatherProviderError,
    WeatherConditionToken,
    WeatherCurrent,
    WeatherHourlyPoint,
    WeatherIconToken,
    WeatherSnapshot,
    WeatherSolar,
    WeatherSourceMetadata,
)
from rolling_thunder.http_home_platform import HttpTransport, UrllibHttpTransport

_DEFAULT_ENDPOINT = "https://api.open-meteo.com/v1/forecast"
_JSON_ACCEPT = "application/json"
_MAX_RESPONSE_BYTES = 262_144
Clock = Callable[[], datetime]

_OPEN_METEO_SOURCE = WeatherSourceMetadata(
    provider_id="open_meteo",
    provider_name="Open-Meteo",
    attribution_text="Weather data by Open-Meteo.com",
    attribution_url="https://open-meteo.com/",
    license_name="CC BY 4.0",
    license_url="https://creativecommons.org/licenses/by/4.0/",
)


class OpenMeteoForgeWeatherProvider:
    """Synchronous Open-Meteo adapter intended only for a Forge worker."""

    def __init__(
        self,
        *,
        timeout_s: float = 5.0,
        transport: HttpTransport | None = None,
        endpoint: str = _DEFAULT_ENDPOINT,
        now: Clock | None = None,
    ) -> None:
        if timeout_s <= 0:
            raise ValueError("Open-Meteo weather timeout must be positive.")
        normalized_endpoint = endpoint.strip()
        if not normalized_endpoint:
            raise ValueError("Open-Meteo weather endpoint must not be blank.")
        self._timeout_s = timeout_s
        self._transport = transport or UrllibHttpTransport()
        self._endpoint = normalized_endpoint
        self._now = now or (lambda: datetime.now(UTC))

    def fetch_weather(self, location: MobileLocationRecord) -> WeatherSnapshot:
        """Fetch and normalize one complete current/hourly/solar forecast."""
        query = urlencode(
            {
                "latitude": location.latitude,
                "longitude": location.longitude,
                "current": (
                    "temperature_2m,relative_humidity_2m,weather_code,is_day"
                ),
                "hourly": "temperature_2m,precipitation_probability",
                "daily": "sunrise,sunset",
                "timezone": "UTC",
                "forecast_hours": 6,
                "forecast_days": 2,
            }
        )
        try:
            response = self._transport.request(
                "GET",
                f"{self._endpoint}?{query}",
                headers={"Accept": _JSON_ACCEPT},
                body=None,
                timeout_s=self._timeout_s,
            )
        except (TimeoutError, URLError, OSError) as error:
            raise ForgeWeatherProviderError("Open-Meteo could not be reached.") from error

        if not 200 <= response.status_code < 300:
            raise ForgeWeatherProviderError(
                f"Open-Meteo returned HTTP {response.status_code}."
            )
        if len(response.body) > _MAX_RESPONSE_BYTES:
            raise ForgeWeatherProviderError(
                "Open-Meteo response exceeded the 262144-byte safety bound."
            )

        payload = self._decode_json(response.body)
        if not isinstance(payload, Mapping):
            raise ForgeWeatherProviderError("Open-Meteo response must be a JSON object.")
        if payload.get("error") is True:
            raise ForgeWeatherProviderError("Open-Meteo rejected the weather request.")

        current_payload = self._mapping(payload, "current")
        source_at = self._parse_utc_timestamp(current_payload.get("time"), "current.time")
        current = self._parse_current(current_payload)
        hourly = self._parse_hourly(payload, source_at)
        solar = self._parse_solar(payload, source_at)
        fetched_at = self._aware_now()

        return WeatherSnapshot(
            latitude=location.latitude,
            longitude=location.longitude,
            source_at=source_at,
            fetched_at=fetched_at,
            current=current,
            hourly=hourly,
            solar=solar,
            source=_OPEN_METEO_SOURCE,
        )

    def _parse_current(self, current: Mapping[object, object]) -> WeatherCurrent:
        temperature = self._number(current.get("temperature_2m"), "current.temperature_2m")
        humidity = self._number(
            current.get("relative_humidity_2m"),
            "current.relative_humidity_2m",
        )
        weather_code = self._integer(current.get("weather_code"), "current.weather_code")
        is_day_raw = self._integer(current.get("is_day"), "current.is_day")
        if is_day_raw not in {0, 1}:
            raise ForgeWeatherProviderError("Open-Meteo current.is_day must be 0 or 1.")
        is_day = is_day_raw == 1
        condition = normalize_open_meteo_weather_code(weather_code)
        return WeatherCurrent(
            temperature_c=temperature,
            relative_humidity_percent=humidity,
            condition=condition,
            icon=weather_icon_for(condition, is_day=is_day),
            is_day=is_day,
        )

    def _parse_hourly(
        self,
        payload: Mapping[object, object],
        source_at: datetime,
    ) -> tuple[WeatherHourlyPoint, ...]:
        hourly = self._mapping(payload, "hourly")
        times = self._sequence(hourly.get("time"), "hourly.time")
        temperatures = self._sequence(
            hourly.get("temperature_2m"),
            "hourly.temperature_2m",
        )
        probabilities = self._sequence(
            hourly.get("precipitation_probability"),
            "hourly.precipitation_probability",
        )
        if not (len(times) == len(temperatures) == len(probabilities)):
            raise ForgeWeatherProviderError(
                "Open-Meteo hourly arrays must have matching lengths."
            )

        points: list[WeatherHourlyPoint] = []
        for index, raw_time in enumerate(times):
            forecast_at = self._parse_utc_timestamp(
                raw_time,
                f"hourly.time[{index}]",
            )
            if forecast_at <= source_at:
                continue
            points.append(
                WeatherHourlyPoint(
                    forecast_at=forecast_at,
                    temperature_c=self._number(
                        temperatures[index],
                        f"hourly.temperature_2m[{index}]",
                    ),
                    precipitation_probability_percent=self._number(
                        probabilities[index],
                        f"hourly.precipitation_probability[{index}]",
                    ),
                )
            )
            if len(points) == 6:
                break

        if len(points) < 3:
            raise ForgeWeatherProviderError(
                "Open-Meteo did not return at least three future hourly points."
            )
        return tuple(points)

    def _parse_solar(
        self,
        payload: Mapping[object, object],
        source_at: datetime,
    ) -> WeatherSolar:
        daily = self._mapping(payload, "daily")
        sunrises = self._sequence(daily.get("sunrise"), "daily.sunrise")
        sunsets = self._sequence(daily.get("sunset"), "daily.sunset")
        if len(sunrises) != len(sunsets) or not sunrises:
            raise ForgeWeatherProviderError(
                "Open-Meteo sunrise/sunset arrays must be non-empty and aligned."
            )

        fallback: WeatherSolar | None = None
        for index, raw_sunrise in enumerate(sunrises):
            sunrise = self._parse_utc_timestamp(
                raw_sunrise,
                f"daily.sunrise[{index}]",
            )
            sunset = self._parse_utc_timestamp(
                sunsets[index],
                f"daily.sunset[{index}]",
            )
            solar = WeatherSolar(sunrise_at=sunrise, sunset_at=sunset)
            if fallback is None:
                fallback = solar
            if sunrise.date() == source_at.date():
                return solar

        assert fallback is not None
        return fallback

    def _aware_now(self) -> datetime:
        value = self._now()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Open-Meteo provider clock must be timezone-aware.")
        return value.astimezone(UTC)

    @staticmethod
    def _decode_json(body: bytes) -> object:
        try:
            return loads(body.decode("utf-8"))
        except (UnicodeDecodeError, JSONDecodeError) as error:
            raise ForgeWeatherProviderError("Open-Meteo returned invalid JSON.") from error

    @staticmethod
    def _mapping(
        payload: Mapping[object, object],
        field_name: str,
    ) -> Mapping[object, object]:
        value = payload.get(field_name)
        if not isinstance(value, Mapping):
            raise ForgeWeatherProviderError(
                f"Open-Meteo response is missing {field_name}."
            )
        return value

    @staticmethod
    def _sequence(value: object, field_name: str) -> Sequence[object]:
        if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
            raise ForgeWeatherProviderError(
                f"Open-Meteo {field_name} must be an array."
            )
        return value

    @staticmethod
    def _number(value: object, field_name: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ForgeWeatherProviderError(
                f"Open-Meteo {field_name} must be numeric."
            )
        return float(value)

    @staticmethod
    def _integer(value: object, field_name: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ForgeWeatherProviderError(
                f"Open-Meteo {field_name} must be an integer."
            )
        return value

    @staticmethod
    def _parse_utc_timestamp(value: object, field_name: str) -> datetime:
        if not isinstance(value, str) or not value.strip():
            raise ForgeWeatherProviderError(
                f"Open-Meteo {field_name} must be an ISO-8601 timestamp."
            )
        normalized = value.strip()
        try:
            parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
        except ValueError as error:
            raise ForgeWeatherProviderError(
                f"Open-Meteo {field_name} is not a valid ISO-8601 timestamp."
            ) from error
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)


def normalize_open_meteo_weather_code(code: int) -> WeatherConditionToken:
    """Normalize WMO/Open-Meteo codes into Rolling Thunder-owned semantics."""
    if code == 0:
        return WeatherConditionToken.CLEAR
    if code in {1, 2}:
        return WeatherConditionToken.PARTLY_CLOUDY
    if code == 3:
        return WeatherConditionToken.CLOUDY
    if code in {45, 48}:
        return WeatherConditionToken.FOG
    if code in {51, 53, 55}:
        return WeatherConditionToken.DRIZZLE
    if code in {56, 57, 66, 67}:
        return WeatherConditionToken.FREEZING_RAIN
    if code in {61, 63, 65}:
        return WeatherConditionToken.RAIN
    if code in {71, 73, 75, 77, 85, 86}:
        return WeatherConditionToken.SNOW
    if code in {80, 81, 82}:
        return WeatherConditionToken.SHOWERS
    if code in {95, 96, 99}:
        return WeatherConditionToken.THUNDERSTORM
    return WeatherConditionToken.UNKNOWN


def weather_icon_for(
    condition: WeatherConditionToken,
    *,
    is_day: bool,
) -> WeatherIconToken:
    """Map normalized conditions to provider-independent display icon tokens."""
    if condition is WeatherConditionToken.CLEAR:
        return WeatherIconToken.CLEAR_DAY if is_day else WeatherIconToken.CLEAR_NIGHT
    if condition is WeatherConditionToken.PARTLY_CLOUDY:
        return (
            WeatherIconToken.PARTLY_CLOUDY_DAY
            if is_day
            else WeatherIconToken.PARTLY_CLOUDY_NIGHT
        )
    mapping = {
        WeatherConditionToken.CLOUDY: WeatherIconToken.CLOUDY,
        WeatherConditionToken.FOG: WeatherIconToken.FOG,
        WeatherConditionToken.DRIZZLE: WeatherIconToken.DRIZZLE,
        WeatherConditionToken.RAIN: WeatherIconToken.RAIN,
        WeatherConditionToken.FREEZING_RAIN: WeatherIconToken.FREEZING_RAIN,
        WeatherConditionToken.SNOW: WeatherIconToken.SNOW,
        WeatherConditionToken.SHOWERS: WeatherIconToken.SHOWERS,
        WeatherConditionToken.THUNDERSTORM: WeatherIconToken.THUNDERSTORM,
        WeatherConditionToken.UNKNOWN: WeatherIconToken.UNKNOWN,
    }
    return mapping[condition]
