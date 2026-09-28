"""Tests for the typed Pi client of retained Forge weather."""

from collections.abc import Mapping
from datetime import UTC, datetime
from json import dumps
from urllib.error import URLError

import pytest

from rolling_thunder.forge_weather_client import (
    ForgeWeatherClientTransportError,
    ForgeWeatherClientValidationError,
    HttpForgeWeatherClient,
)
from rolling_thunder.http_home_platform import HttpResponse

BASE_TIME = datetime(2026, 8, 9, 3, 35, tzinfo=UTC)


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
    def __init__(
        self,
        response: HttpResponse | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.response = response or FakeResponse(200, response_body())
        self.error = error
        self.requests: list[
            tuple[str, str, Mapping[str, str], bytes | None, float]
        ] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout_s: float,
    ) -> HttpResponse:
        self.requests.append((method, url, dict(headers), body, timeout_s))
        if self.error is not None:
            raise self.error
        return self.response


def weather_payload() -> dict[str, object]:
    return {
        "api_schema_version": "1",
        "revision": 4,
        "stale": False,
        "snapshot": {
            "latitude": 39.52449,
            "longitude": -84.062475,
            "source_at": "2026-08-09T03:30:00Z",
            "fetched_at": "2026-08-09T03:31:00Z",
            "current": {
                "temperature_c": 21.5,
                "relative_humidity_percent": 66.0,
                "condition": "partly_cloudy",
                "icon": "partly_cloudy_night",
                "is_day": False,
            },
            "hourly": [
                {
                    "forecast_at": "2026-08-09T04:00:00Z",
                    "temperature_c": 21.0,
                    "precipitation_probability_percent": 10.0,
                },
                {
                    "forecast_at": "2026-08-09T05:00:00Z",
                    "temperature_c": 20.0,
                    "precipitation_probability_percent": 15.0,
                },
                {
                    "forecast_at": "2026-08-09T06:00:00Z",
                    "temperature_c": 19.0,
                    "precipitation_probability_percent": 20.0,
                },
            ],
            "solar": {
                "sunrise_at": "2026-08-09T10:43:00Z",
                "sunset_at": "2026-08-10T00:42:00Z",
            },
            "source": {
                "provider_id": "open_meteo",
                "provider_name": "Open-Meteo",
                "attribution_text": "Weather data by Open-Meteo.com",
                "attribution_url": "https://open-meteo.com/",
                "license_name": "CC BY 4.0",
                "license_url": "https://creativecommons.org/licenses/by/4.0/",
            },
        },
        "health": {
            "status": "healthy",
            "stale": False,
            "revision": 4,
            "last_attempt_at": "2026-08-09T03:31:00Z",
            "last_success_at": "2026-08-09T03:31:00Z",
            "last_error": None,
            "startup_storage_error": None,
            "persistence_error": None,
        },
    }


def response_body(value: object | None = None) -> bytes:
    return dumps(weather_payload() if value is None else value).encode("utf-8")


def client_for(
    transport: RecordingTransport,
    *,
    max_response_bytes: int = 1_048_576,
) -> HttpForgeWeatherClient:
    return HttpForgeWeatherClient(
        "http://forge.example.test:8766/",
        timeout_s=3.5,
        max_response_bytes=max_response_bytes,
        transport=transport,
        clock=lambda: BASE_TIME,
    )


def test_fetch_weather_builds_expected_request_and_validates_snapshot() -> None:
    transport = RecordingTransport()

    result = client_for(transport).fetch_weather()

    assert transport.requests == [
        (
            "GET",
            "http://forge.example.test:8766/api/v1/weather",
            {"Accept": "application/json", "User-Agent": "RollingThunder-v4.1"},
            None,
            3.5,
        )
    ]
    assert result.revision == 4
    assert result.stale is False
    assert result.snapshot is not None
    assert result.snapshot.current.temperature_c == 21.5
    assert result.snapshot.source_at == datetime(2026, 8, 9, 3, 30, tzinfo=UTC)
    assert result.received_at == BASE_TIME


def test_fetch_weather_accepts_versioned_no_data_response() -> None:
    payload = weather_payload()
    payload.update(
        {
            "revision": 0,
            "stale": True,
            "snapshot": None,
            "health": {
                "status": "starting",
                "stale": True,
                "revision": 0,
                "last_attempt_at": None,
                "last_success_at": None,
                "last_error": None,
                "startup_storage_error": None,
                "persistence_error": None,
            },
        }
    )
    result = client_for(RecordingTransport(FakeResponse(200, response_body(payload)))).fetch_weather()
    assert result.revision == 0
    assert result.snapshot is None
    assert result.stale is True


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update({"api_schema_version": "2"}),
        lambda value: value["health"].update({"revision": 99}),  # type: ignore[union-attr]
        lambda value: value["health"].update({"stale": True}),  # type: ignore[union-attr]
        lambda value: value.update({"revision": 0}),
    ],
)
def test_fetch_weather_rejects_contract_mismatch(mutation: object) -> None:
    payload = weather_payload()
    assert callable(mutation)
    mutation(payload)
    transport = RecordingTransport(FakeResponse(200, response_body(payload)))
    with pytest.raises(ForgeWeatherClientValidationError):
        client_for(transport).fetch_weather()


def test_fetch_weather_rejects_malformed_json_and_response_limit() -> None:
    with pytest.raises(ForgeWeatherClientValidationError):
        client_for(RecordingTransport(FakeResponse(200, b"not-json"))).fetch_weather()

    body = response_body()
    with pytest.raises(ForgeWeatherClientValidationError, match="byte limit"):
        client_for(
            RecordingTransport(FakeResponse(200, body)),
            max_response_bytes=len(body) - 1,
        ).fetch_weather()


def test_fetch_weather_maps_http_and_network_failures_to_transport_error() -> None:
    with pytest.raises(ForgeWeatherClientTransportError, match="HTTP 503"):
        client_for(RecordingTransport(FakeResponse(503, b"{}"))).fetch_weather()

    with pytest.raises(ForgeWeatherClientTransportError, match="could not be completed"):
        client_for(RecordingTransport(error=URLError("offline"))).fetch_weather()
