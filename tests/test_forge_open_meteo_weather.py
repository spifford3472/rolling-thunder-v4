"""Tests for the Forge Open-Meteo weather provider boundary."""

from collections.abc import Mapping
from datetime import UTC, datetime
from json import dumps
from urllib.parse import parse_qs, urlsplit

import pytest

from rolling_thunder.forge_mobile_location import MobileLocationRecord
from rolling_thunder.forge_open_meteo_weather import (
    OpenMeteoForgeWeatherProvider,
    normalize_open_meteo_weather_code,
)
from rolling_thunder.forge_weather import (
    ForgeWeatherProviderError,
    WeatherConditionToken,
    WeatherIconToken,
)
from rolling_thunder.http_home_platform import HttpResponse

FETCHED_AT = datetime(2026, 8, 9, 0, 34, 55, tzinfo=UTC)


class FakeResponse:
    def __init__(self, status_code: int, body: bytes) -> None:
        self._status_code = status_code
        self._body = body

    @property
    def status_code(self) -> int:
        return self._status_code

    @property
    def body(self) -> bytes:
        return self._body


class RecordingTransport:
    def __init__(self, response: HttpResponse) -> None:
        self.response = response
        self.requests: list[tuple[str, str, Mapping[str, str], float]] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout_s: float,
    ) -> HttpResponse:
        assert body is None
        self.requests.append((method, url, headers, timeout_s))
        return self.response


def location() -> MobileLocationRecord:
    return MobileLocationRecord(
        latitude=39.524492,
        longitude=-84.062475,
        fix_at=datetime(2026, 8, 9, 0, 34, 50, tzinfo=UTC),
        received_at=datetime(2026, 8, 9, 0, 34, 51, tzinfo=UTC),
    )


def valid_payload(*, weather_code: int = 2, is_day: int = 0) -> bytes:
    return dumps(
        {
            "latitude": 39.52,
            "longitude": -84.06,
            "timezone": "GMT",
            "utc_offset_seconds": 0,
            "current": {
                "time": "2026-08-09T00:30",
                "temperature_2m": 22.4,
                "relative_humidity_2m": 78,
                "weather_code": weather_code,
                "is_day": is_day,
            },
            "hourly": {
                "time": [
                    "2026-08-09T01:00",
                    "2026-08-09T02:00",
                    "2026-08-09T03:00",
                    "2026-08-09T04:00",
                    "2026-08-09T05:00",
                    "2026-08-09T06:00",
                ],
                "temperature_2m": [22.1, 21.7, 21.0, 20.4, 19.8, 19.4],
                "precipitation_probability": [10, 20, 30, 40, 50, 60],
            },
            "daily": {
                "sunrise": ["2026-08-09T10:42", "2026-08-10T10:43"],
                "sunset": ["2026-08-10T00:41", "2026-08-11T00:40"],
            },
        }
    ).encode("utf-8")


def test_provider_requests_bounded_fields_and_normalizes_snapshot() -> None:
    transport = RecordingTransport(FakeResponse(200, valid_payload()))
    provider = OpenMeteoForgeWeatherProvider(
        transport=transport,
        timeout_s=3.5,
        now=lambda: FETCHED_AT,
    )

    snapshot = provider.fetch_weather(location())

    assert len(transport.requests) == 1
    method, url, headers, timeout_s = transport.requests[0]
    assert method == "GET"
    assert headers["Accept"] == "application/json"
    assert timeout_s == 3.5
    query = parse_qs(urlsplit(url).query)
    assert query["current"] == [
        "temperature_2m,relative_humidity_2m,weather_code,is_day"
    ]
    assert query["hourly"] == ["temperature_2m,precipitation_probability"]
    assert query["daily"] == ["sunrise,sunset"]
    assert query["timezone"] == ["UTC"]
    assert query["forecast_hours"] == ["6"]

    assert snapshot.latitude == 39.524492
    assert snapshot.longitude == -84.062475
    assert snapshot.source_at == datetime(2026, 8, 9, 0, 30, tzinfo=UTC)
    assert snapshot.fetched_at == FETCHED_AT
    assert snapshot.current.temperature_c == 22.4
    assert snapshot.current.relative_humidity_percent == 78
    assert snapshot.current.condition is WeatherConditionToken.PARTLY_CLOUDY
    assert snapshot.current.icon is WeatherIconToken.PARTLY_CLOUDY_NIGHT
    assert len(snapshot.hourly) == 6
    assert snapshot.hourly[0].forecast_at == datetime(2026, 8, 9, 1, 0, tzinfo=UTC)
    assert snapshot.hourly[2].precipitation_probability_percent == 30
    assert snapshot.solar.sunrise_at == datetime(2026, 8, 9, 10, 42, tzinfo=UTC)
    assert snapshot.solar.sunset_at == datetime(2026, 8, 10, 0, 41, tzinfo=UTC)
    assert snapshot.source.provider_id == "open_meteo"
    assert snapshot.source.attribution_text == "Weather data by Open-Meteo.com"
    assert snapshot.source.license_name == "CC BY 4.0"


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (0, WeatherConditionToken.CLEAR),
        (3, WeatherConditionToken.CLOUDY),
        (45, WeatherConditionToken.FOG),
        (53, WeatherConditionToken.DRIZZLE),
        (63, WeatherConditionToken.RAIN),
        (66, WeatherConditionToken.FREEZING_RAIN),
        (75, WeatherConditionToken.SNOW),
        (81, WeatherConditionToken.SHOWERS),
        (95, WeatherConditionToken.THUNDERSTORM),
        (1234, WeatherConditionToken.UNKNOWN),
    ],
)
def test_provider_codes_are_normalized_to_owned_condition_tokens(
    code: int,
    expected: WeatherConditionToken,
) -> None:
    assert normalize_open_meteo_weather_code(code) is expected


def test_provider_rejects_incomplete_hourly_payload() -> None:
    payload = valid_payload()
    raw = __import__("json").loads(payload)
    raw["hourly"]["precipitation_probability"] = [10, 20]
    transport = RecordingTransport(FakeResponse(200, dumps(raw).encode("utf-8")))
    provider = OpenMeteoForgeWeatherProvider(
        transport=transport,
        now=lambda: FETCHED_AT,
    )

    with pytest.raises(ForgeWeatherProviderError, match="matching lengths"):
        provider.fetch_weather(location())


def test_provider_rejects_non_success_and_invalid_json() -> None:
    failed = OpenMeteoForgeWeatherProvider(
        transport=RecordingTransport(FakeResponse(503, b"{}")),
        now=lambda: FETCHED_AT,
    )
    malformed = OpenMeteoForgeWeatherProvider(
        transport=RecordingTransport(FakeResponse(200, b"not-json")),
        now=lambda: FETCHED_AT,
    )

    with pytest.raises(ForgeWeatherProviderError, match="HTTP 503"):
        failed.fetch_weather(location())
    with pytest.raises(ForgeWeatherProviderError, match="invalid JSON"):
        malformed.fetch_weather(location())
