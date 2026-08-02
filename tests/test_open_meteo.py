from collections.abc import Mapping
from dataclasses import dataclass

import pytest

from rolling_thunder.open_meteo import (
    OpenMeteoError,
    OpenMeteoParkWeatherProvider,
)
from rolling_thunder.pota_spots import ParkReference


@dataclass(frozen=True)
class FakeResponse:
    status_code: int
    body: bytes


class FakeTransport:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.requests: list[tuple[str, Mapping[str, str]]] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout_s: float,
    ) -> FakeResponse:
        del method, body, timeout_s
        self.requests.append((url, headers))
        return self.response


def park() -> ParkReference:
    return ParkReference(
        reference="US-1940",
        name="Caesar Creek State Park",
        latitude=39.489,
        longitude=-84.055,
    )


def test_fetch_weather_returns_fahrenheit_celsius_and_local_time() -> None:
    transport = FakeTransport(
        FakeResponse(
            status_code=200,
            body=(
                b'{"latitude":39.489,"longitude":-84.055,'
                b'"timezone":"America/New_York",'
                b'"current":{"time":"2026-08-02T01:30",'
                b'"temperature_2m":20.0}}'
            ),
        )
    )
    provider = OpenMeteoParkWeatherProvider(transport=transport)

    weather = provider.fetch_weather(park())

    assert weather.temperature_c == 20.0
    assert weather.temperature_f == 68.0
    assert weather.local_time == "01:30"
    assert weather.timezone == "America/New_York"
    assert "timezone=auto" in transport.requests[0][0]
    assert "current=temperature_2m" in transport.requests[0][0]


def test_missing_coordinates_are_rejected_before_http() -> None:
    transport = FakeTransport(FakeResponse(status_code=200, body=b"{}"))
    provider = OpenMeteoParkWeatherProvider(transport=transport)

    with pytest.raises(ValueError, match="coordinates are required"):
        provider.fetch_weather(
            ParkReference(reference="US-1940", name="Caesar Creek State Park")
        )

    assert transport.requests == []


def test_invalid_current_weather_is_actionable() -> None:
    provider = OpenMeteoParkWeatherProvider(
        transport=FakeTransport(FakeResponse(status_code=200, body=b"{}"))
    )

    with pytest.raises(OpenMeteoError, match="missing current weather"):
        provider.fetch_weather(park())
