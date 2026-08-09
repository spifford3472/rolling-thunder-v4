"""Tests for retained Forge weather refresh, health, and retention policy."""

from datetime import UTC, datetime, timedelta
from typing import cast

from rolling_thunder.forge_mobile_location import (
    ForgeMobileLocationService,
    MobileLocationRecord,
    MobileLocationState,
)
from rolling_thunder.forge_weather import (
    ForgeWeatherProviderError,
    ForgeWeatherService,
    ForgeWeatherState,
    ForgeWeatherStorageError,
    WeatherConditionToken,
    WeatherCurrent,
    WeatherHourlyPoint,
    WeatherIconToken,
    WeatherProviderStatus,
    WeatherSnapshot,
    WeatherSolar,
    WeatherSourceMetadata,
)

BASE_TIME = datetime(2026, 8, 9, 0, 35, tzinfo=UTC)
SOURCE = WeatherSourceMetadata(
    provider_id="test",
    provider_name="Test Weather",
    attribution_text="Test attribution",
    attribution_url="https://weather.example.invalid/",
    license_name="Test licence",
    license_url="https://weather.example.invalid/license",
)


class MutableClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


class MutableLocationSource:
    def __init__(self, location: MobileLocationRecord | None) -> None:
        self.location = location

    def get_state(self) -> MobileLocationState:
        return MobileLocationState(
            revision=0 if self.location is None else 1,
            location=self.location,
        )


class RecordingProvider:
    def __init__(self, responses: list[WeatherSnapshot | Exception]) -> None:
        self.responses = responses
        self.calls: list[MobileLocationRecord] = []

    def fetch_weather(self, location: MobileLocationRecord) -> WeatherSnapshot:
        self.calls.append(location)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class RecordingRepository:
    def __init__(self, state: ForgeWeatherState | None = None) -> None:
        self.state = state
        self.error: ForgeWeatherStorageError | None = None
        self.before_replace: list[int] = []
        self.on_replace = None

    def load(self) -> ForgeWeatherState | None:
        return self.state

    def replace(self, snapshot: WeatherSnapshot) -> ForgeWeatherState:
        if self.on_replace is not None:
            self.on_replace()
        if self.error is not None:
            raise self.error
        revision = 1 if self.state is None else self.state.revision + 1
        self.state = ForgeWeatherState(
            revision=revision,
            snapshot=snapshot,
            provider_status=WeatherProviderStatus.STARTING,
        )
        return self.state


def location(
    *,
    latitude: float = 39.524492,
    longitude: float = -84.062475,
) -> MobileLocationRecord:
    return MobileLocationRecord(
        latitude=latitude,
        longitude=longitude,
        fix_at=BASE_TIME - timedelta(seconds=2),
        received_at=BASE_TIME - timedelta(seconds=1),
    )


def snapshot(
    fetched_at: datetime,
    *,
    latitude: float = 39.524492,
    longitude: float = -84.062475,
) -> WeatherSnapshot:
    return WeatherSnapshot(
        latitude=latitude,
        longitude=longitude,
        source_at=fetched_at - timedelta(minutes=5),
        fetched_at=fetched_at,
        current=WeatherCurrent(
            temperature_c=22.0,
            relative_humidity_percent=70.0,
            condition=WeatherConditionToken.CLEAR,
            icon=WeatherIconToken.CLEAR_NIGHT,
            is_day=False,
        ),
        hourly=tuple(
            WeatherHourlyPoint(
                forecast_at=fetched_at + timedelta(hours=index),
                temperature_c=22.0 - index,
                precipitation_probability_percent=index * 10,
            )
            for index in range(1, 4)
        ),
        solar=WeatherSolar(
            sunrise_at=fetched_at.replace(hour=10, minute=42),
            sunset_at=(fetched_at + timedelta(days=1)).replace(hour=0, minute=41),
        ),
        source=SOURCE,
    )


def build_service(
    provider: RecordingProvider,
    repository: RecordingRepository,
    locations: MutableLocationSource,
    clock: MutableClock,
) -> ForgeWeatherService:
    return ForgeWeatherService(
        provider,
        repository,
        cast(ForgeMobileLocationService, locations),
        now=clock,
        max_forecast_age_s=1_800.0,
        movement_refresh_km=10.0,
    )


def test_first_refresh_persists_before_publishing_and_reports_healthy() -> None:
    clock = MutableClock(BASE_TIME)
    locations = MutableLocationSource(location())
    provider = RecordingProvider([snapshot(BASE_TIME)])
    repository = RecordingRepository()
    service = build_service(provider, repository, locations, clock)
    observed_revisions: list[int] = []
    repository.on_replace = lambda: observed_revisions.append(service.get_state().revision)

    state = service.refresh_if_needed()

    assert observed_revisions == [0]
    assert state.revision == 1
    assert state.snapshot == snapshot(BASE_TIME)
    assert state.provider_status is WeatherProviderStatus.HEALTHY
    assert state.last_attempt_at == BASE_TIME
    assert state.last_success_at == BASE_TIME
    assert state.last_error is None
    assert state.persistence_error is None
    assert service.is_stale() is False


def test_fresh_nearby_snapshot_is_not_refetched_but_movement_triggers_refresh() -> None:
    clock = MutableClock(BASE_TIME)
    locations = MutableLocationSource(location())
    moved_location = location(latitude=39.70, longitude=-84.062475)
    provider = RecordingProvider(
        [
            snapshot(BASE_TIME),
            snapshot(BASE_TIME + timedelta(minutes=1), latitude=39.70),
        ]
    )
    repository = RecordingRepository()
    service = build_service(provider, repository, locations, clock)

    assert service.refresh_if_needed().revision == 1
    assert service.refresh_if_needed().revision == 1
    assert len(provider.calls) == 1

    locations.location = moved_location
    clock.value = BASE_TIME + timedelta(minutes=1)

    assert service.is_stale() is True
    moved = service.refresh_if_needed()
    assert moved.revision == 2
    assert moved.snapshot is not None
    assert moved.snapshot.latitude == 39.70
    assert len(provider.calls) == 2


def test_forecast_age_triggers_refresh() -> None:
    clock = MutableClock(BASE_TIME)
    locations = MutableLocationSource(location())
    provider = RecordingProvider(
        [snapshot(BASE_TIME), snapshot(BASE_TIME + timedelta(minutes=31))]
    )
    repository = RecordingRepository()
    service = build_service(provider, repository, locations, clock)

    assert service.refresh_if_needed().revision == 1
    clock.value = BASE_TIME + timedelta(minutes=31)

    assert service.is_stale() is True
    refreshed = service.refresh_if_needed()
    assert refreshed.revision == 2
    assert refreshed.provider_status is WeatherProviderStatus.HEALTHY


def test_provider_failure_retains_prior_snapshot_and_exposes_degraded_health() -> None:
    clock = MutableClock(BASE_TIME)
    locations = MutableLocationSource(location())
    provider = RecordingProvider(
        [snapshot(BASE_TIME), ForgeWeatherProviderError("provider offline")]
    )
    repository = RecordingRepository()
    service = build_service(provider, repository, locations, clock)
    accepted = service.refresh_if_needed()
    clock.value = BASE_TIME + timedelta(minutes=31)

    failed = service.refresh_if_needed()

    assert failed.revision == accepted.revision
    assert failed.snapshot == accepted.snapshot
    assert failed.provider_status is WeatherProviderStatus.DEGRADED
    assert failed.last_error == "provider offline"
    assert failed.last_success_at == BASE_TIME
    assert service.is_stale() is True


def test_persistence_failure_retains_prior_snapshot_and_exposes_storage_error() -> None:
    clock = MutableClock(BASE_TIME)
    locations = MutableLocationSource(location())
    provider = RecordingProvider(
        [snapshot(BASE_TIME), snapshot(BASE_TIME + timedelta(minutes=31))]
    )
    repository = RecordingRepository()
    service = build_service(provider, repository, locations, clock)
    accepted = service.refresh_if_needed()
    repository.error = ForgeWeatherStorageError("disk full")
    clock.value = BASE_TIME + timedelta(minutes=31)

    failed = service.refresh_if_needed()

    assert failed.revision == accepted.revision
    assert failed.snapshot == accepted.snapshot
    assert failed.provider_status is WeatherProviderStatus.DEGRADED
    assert failed.persistence_error == "disk full"
    assert failed.last_success_at == BASE_TIME


def test_missing_location_never_calls_provider_and_reports_unavailable() -> None:
    clock = MutableClock(BASE_TIME)
    locations = MutableLocationSource(None)
    provider = RecordingProvider([])
    repository = RecordingRepository()
    service = build_service(provider, repository, locations, clock)

    state = service.refresh_if_needed()

    assert provider.calls == []
    assert state.revision == 0
    assert state.provider_status is WeatherProviderStatus.UNAVAILABLE
    assert state.last_error is not None
    assert "No retained mobile location" in state.last_error
