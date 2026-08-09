"""Tests for retained, applicability-safe Pi Forge weather alerts."""

from datetime import UTC, datetime, timedelta

from rolling_thunder.forge_weather_alert_client import (
    ForgeRemoteWeatherAlertHealth,
    ForgeWeatherAlertClientResult,
    ForgeWeatherAlertClientTransportError,
)
from rolling_thunder.forge_weather_alerts import (
    WeatherAlertApplicability,
    WeatherAlertProviderStatus,
    WeatherAlertSnapshot,
    WeatherAlertSourceMetadata,
)
from rolling_thunder.pi_forge_weather_alert_service import (
    PiForgeWeatherAlertService,
    PiForgeWeatherAlertStateKind,
)

NOW = datetime(2026, 8, 9, 6, 20, tzinfo=UTC)


def result(
    *,
    revision: int = 4,
    applicability: WeatherAlertApplicability = (
        WeatherAlertApplicability.VERIFIED_CURRENT
    ),
) -> ForgeWeatherAlertClientResult:
    return ForgeWeatherAlertClientResult(
        revision=revision,
        snapshot=WeatherAlertSnapshot(
            latitude=39.5245,
            longitude=-84.0625,
            fetched_at=NOW - timedelta(seconds=2),
            alerts=(),
            source=WeatherAlertSourceMetadata(
                provider_id="nws",
                provider_name="National Weather Service",
                attribution_text="National Weather Service alerts",
                attribution_url="https://www.weather.gov/",
            ),
        ),
        health=ForgeRemoteWeatherAlertHealth(
            status=WeatherAlertProviderStatus.HEALTHY,
            applicability=applicability,
            revision=revision,
            last_attempt_at=NOW,
            last_success_at=NOW,
        ),
        received_at=NOW,
    )


class FakeClient:
    def __init__(
        self,
        current: ForgeWeatherAlertClientResult,
    ) -> None:
        self.current = current
        self.error: Exception | None = None

    def fetch_alerts(
        self,
    ) -> ForgeWeatherAlertClientResult:
        if self.error is not None:
            raise self.error
        return self.current


class MemoryCache:
    def __init__(
        self,
        stored: ForgeWeatherAlertClientResult | None = None,
    ) -> None:
        self.stored = stored
        self.replacements = 0

    def load(
        self,
    ) -> ForgeWeatherAlertClientResult | None:
        return self.stored

    def replace(
        self,
        value: ForgeWeatherAlertClientResult,
    ) -> None:
        self.stored = value
        self.replacements += 1


def test_restart_downgrades_cached_verified_state_to_unverified() -> None:
    service = PiForgeWeatherAlertService(
        FakeClient(result()),
        MemoryCache(result()),
        now=lambda: NOW,
    )

    state = service.get_state()

    assert state.kind is PiForgeWeatherAlertStateKind.RETAINED
    assert (
        state.applicability
        is WeatherAlertApplicability.RETAINED_UNVERIFIED
    )
    assert state.is_verified_current is False


def test_successful_verified_refresh_persists_then_publishes_live() -> None:
    cache = MemoryCache()
    service = PiForgeWeatherAlertService(
        FakeClient(result()),
        cache,
        now=lambda: NOW,
    )

    state = service.refresh()

    assert cache.replacements == 1
    assert state.kind is PiForgeWeatherAlertStateKind.LIVE
    assert (
        state.applicability
        is WeatherAlertApplicability.VERIFIED_CURRENT
    )
    assert state.is_verified_current is True


def test_successful_unverified_forge_result_never_becomes_verified() -> None:
    service = PiForgeWeatherAlertService(
        FakeClient(
            result(
                applicability=(
                    WeatherAlertApplicability.RETAINED_UNVERIFIED
                )
            )
        ),
        MemoryCache(),
        now=lambda: NOW,
    )

    state = service.refresh()

    assert state.kind is PiForgeWeatherAlertStateKind.LIVE
    assert (
        state.applicability
        is WeatherAlertApplicability.RETAINED_UNVERIFIED
    )
    assert state.is_verified_current is False


def test_transport_failure_retains_data_but_removes_applicability() -> None:
    cached = result()
    client = FakeClient(cached)
    service = PiForgeWeatherAlertService(
        client,
        MemoryCache(cached),
        now=lambda: NOW,
    )

    # First prove the state can become freshly verified.
    assert service.refresh().is_verified_current is True

    client.error = ForgeWeatherAlertClientTransportError(
        "Forge unavailable"
    )

    failed = service.refresh()

    assert failed.kind is PiForgeWeatherAlertStateKind.RETAINED
    assert failed.snapshot == cached.snapshot
    assert (
        failed.applicability
        is WeatherAlertApplicability.RETAINED_UNVERIFIED
    )
    assert failed.is_verified_current is False
    assert failed.last_error == "Forge unavailable"
