"""Tests for the optional Forge weather-alert REST route."""

from collections.abc import Mapping
from datetime import UTC, datetime
from json import loads
from typing import cast

from rolling_thunder.forge_spot_api import ForgeHttpResponse, ForgeSpotApiApplication
from rolling_thunder.forge_weather_alert_api import (
    WeatherAlertAwareForgeSpotApiApplication,
)
from rolling_thunder.forge_weather_alerts import (
    ForgeWeatherAlertService,
    ForgeWeatherAlertState,
    WeatherAlertApplicability,
    WeatherAlertProviderStatus,
    WeatherAlertSnapshot,
    WeatherAlertSourceMetadata,
)

BASE_TIME = datetime(2026, 8, 9, 5, 30, tzinfo=UTC)
SOURCE = WeatherAlertSourceMetadata(
    provider_id="nws",
    provider_name="National Weather Service",
    attribution_text="National Weather Service alerts",
    attribution_url="https://www.weather.gov/",
)


class FakeCore:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def handle(
        self,
        method: str,
        target: str,
        *,
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
    ) -> ForgeHttpResponse:
        del headers, body
        self.calls.append((method, target))
        return ForgeHttpResponse(
            status_code=299,
            headers=(("Content-Length", "0"),),
            body=b"",
        )


class FakeAlertService:
    def __init__(self, state: ForgeWeatherAlertState) -> None:
        self.state = state

    def get_state(self) -> ForgeWeatherAlertState:
        return self.state


def snapshot() -> WeatherAlertSnapshot:
    return WeatherAlertSnapshot(
        latitude=39.5245,
        longitude=-84.0625,
        fetched_at=BASE_TIME,
        alerts=(),
        source=SOURCE,
    )


def app(
    service: FakeAlertService | None,
) -> tuple[WeatherAlertAwareForgeSpotApiApplication, FakeCore]:
    core = FakeCore()
    return (
        WeatherAlertAwareForgeSpotApiApplication(
            cast(ForgeSpotApiApplication, core),
            None if service is None else cast(ForgeWeatherAlertService, service),
        ),
        core,
    )


def test_get_returns_verified_empty_active_set_as_successful_data() -> None:
    application, core = app(
        FakeAlertService(
            ForgeWeatherAlertState(
                revision=7,
                snapshot=snapshot(),
                provider_status=WeatherAlertProviderStatus.HEALTHY,
                applicability=WeatherAlertApplicability.VERIFIED_CURRENT,
                last_attempt_at=BASE_TIME,
                last_success_at=BASE_TIME,
            )
        )
    )

    response = application.handle("GET", "/api/v1/weather-alerts")
    payload = loads(response.body)

    assert response.status_code == 200
    assert core.calls == []
    assert payload["api_schema_version"] == "1"
    assert payload["revision"] == 7
    assert payload["snapshot"]["alerts"] == []
    assert payload["health"]["status"] == "healthy"
    assert payload["health"]["applicability"] == "verified_current"
    assert payload["health"]["revision"] == 7


def test_retained_snapshot_is_exposed_with_unverified_applicability() -> None:
    application, _ = app(
        FakeAlertService(
            ForgeWeatherAlertState(
                revision=3,
                snapshot=snapshot(),
                provider_status=WeatherAlertProviderStatus.DEGRADED,
                applicability=WeatherAlertApplicability.RETAINED_UNVERIFIED,
                last_error="NWS offline",
            )
        )
    )

    payload = loads(application.handle("GET", "/api/v1/weather-alerts").body)

    assert payload["snapshot"] is not None
    assert payload["health"]["applicability"] == "retained_unverified"
    assert payload["health"]["last_error"] == "NWS offline"


def test_disabled_endpoint_returns_503_and_post_returns_405() -> None:
    disabled, _ = app(None)
    enabled, _ = app(FakeAlertService(ForgeWeatherAlertState(revision=0)))

    unavailable = disabled.handle("GET", "/api/v1/weather-alerts")
    wrong_method = enabled.handle("POST", "/api/v1/weather-alerts")

    assert unavailable.status_code == 503
    assert loads(unavailable.body)["error"] == "weather_alerts_unavailable"
    assert wrong_method.status_code == 405
    assert dict(wrong_method.headers)["Allow"] == "GET"


def test_non_alert_routes_delegate_unchanged_to_core_application() -> None:
    application, core = app(None)

    response = application.handle("GET", "/api/v1/spots?provider=pota")

    assert response.status_code == 299
    assert core.calls == [("GET", "/api/v1/spots?provider=pota")]
