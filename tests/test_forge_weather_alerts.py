"""Tests for retained Forge weather-alert applicability and failure policy."""

from datetime import UTC, datetime, timedelta
from typing import cast

from rolling_thunder.forge_mobile_location import (
    ForgeMobileLocationService,
    MobileLocationRecord,
    MobileLocationState,
)
from rolling_thunder.forge_weather_alerts import (
    ForgeWeatherAlertProviderError,
    ForgeWeatherAlertService,
    ForgeWeatherAlertState,
    ForgeWeatherAlertStorageError,
    WeatherAlertApplicability,
    WeatherAlertCertainty,
    WeatherAlertProviderStatus,
    WeatherAlertRecord,
    WeatherAlertSeverity,
    WeatherAlertSnapshot,
    WeatherAlertSourceMetadata,
    WeatherAlertUrgency,
)

BASE_TIME = datetime(2026, 8, 9, 5, 30, tzinfo=UTC)
SOURCE = WeatherAlertSourceMetadata(
    provider_id="test",
    provider_name="Test Alerts",
    attribution_text="Test alert attribution",
    attribution_url="https://alerts.example.invalid/",
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
    def __init__(self, responses: list[WeatherAlertSnapshot | Exception]) -> None:
        self.responses = responses
        self.calls: list[MobileLocationRecord] = []

    def fetch_alerts(self, location: MobileLocationRecord) -> WeatherAlertSnapshot:
        self.calls.append(location)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class PointAwareProvider:
    def __init__(self) -> None:
        self.calls: list[MobileLocationRecord] = []

    def fetch_alerts(self, location: MobileLocationRecord) -> WeatherAlertSnapshot:
        self.calls.append(location)
        alerts = (alert(),) if 39.60 <= location.latitude < 39.70 else ()
        return snapshot(
            latitude=location.latitude,
            longitude=location.longitude,
            alerts=alerts,
        )


class RecordingRepository:
    def __init__(self, state: ForgeWeatherAlertState | None = None) -> None:
        self.state = state
        self.error: ForgeWeatherAlertStorageError | None = None
        self.on_replace = None

    def load(self) -> ForgeWeatherAlertState | None:
        return self.state

    def replace(self, snapshot: WeatherAlertSnapshot) -> ForgeWeatherAlertState:
        if self.on_replace is not None:
            self.on_replace()
        if self.error is not None:
            raise self.error
        revision = 1 if self.state is None else self.state.revision + 1
        self.state = ForgeWeatherAlertState(
            revision=revision,
            snapshot=snapshot,
            provider_status=WeatherAlertProviderStatus.STARTING,
            applicability=WeatherAlertApplicability.RETAINED_UNVERIFIED,
        )
        return self.state


def location(
    *,
    latitude: float = 39.5245,
    longitude: float = -84.0625,
    received_at: datetime = BASE_TIME - timedelta(seconds=1),
) -> MobileLocationRecord:
    return MobileLocationRecord(
        latitude=latitude,
        longitude=longitude,
        fix_at=received_at - timedelta(seconds=1),
        received_at=received_at,
    )


def alert() -> WeatherAlertRecord:
    return WeatherAlertRecord(
        alert_id="https://api.weather.gov/alerts/test-tornado",
        event="Tornado Warning",
        severity=WeatherAlertSeverity.EXTREME,
        urgency=WeatherAlertUrgency.IMMEDIATE,
        certainty=WeatherAlertCertainty.OBSERVED,
        headline="Tornado Warning issued for the test area",
        area_description="Test Area",
        sent_at=BASE_TIME - timedelta(minutes=2),
        effective_at=BASE_TIME - timedelta(minutes=2),
        onset_at=BASE_TIME - timedelta(minutes=1),
        ends_at=BASE_TIME + timedelta(minutes=28),
        expires_at=BASE_TIME + timedelta(minutes=30),
    )


def snapshot(
    *,
    latitude: float = 39.5245,
    longitude: float = -84.0625,
    alerts: tuple[WeatherAlertRecord, ...] = (),
) -> WeatherAlertSnapshot:
    return WeatherAlertSnapshot(
        latitude=latitude,
        longitude=longitude,
        fetched_at=BASE_TIME,
        alerts=alerts,
        source=SOURCE,
    )


def build_service(
    provider: RecordingProvider | PointAwareProvider,
    repository: RecordingRepository,
    locations: MutableLocationSource,
    clock: MutableClock,
) -> ForgeWeatherAlertService:
    return ForgeWeatherAlertService(
        provider,
        repository,
        cast(ForgeMobileLocationService, locations),
        now=clock,
        location_max_age_s=120.0,
    )


def test_current_location_refresh_persists_before_verified_publication() -> None:
    clock = MutableClock(BASE_TIME)
    locations = MutableLocationSource(location())
    provider = RecordingProvider([snapshot(alerts=(alert(),))])
    repository = RecordingRepository()
    service = build_service(provider, repository, locations, clock)
    observed_revisions: list[int] = []
    repository.on_replace = lambda: observed_revisions.append(service.get_state().revision)

    state = service.refresh()

    assert observed_revisions == [0]
    assert state.revision == 1
    assert state.snapshot is not None
    assert state.snapshot.alerts == (alert(),)
    assert state.provider_status is WeatherAlertProviderStatus.HEALTHY
    assert state.applicability is WeatherAlertApplicability.VERIFIED_CURRENT
    assert state.last_attempt_at == BASE_TIME
    assert state.last_success_at == BASE_TIME
    assert state.last_error is None


def test_missing_location_never_calls_provider_or_claims_applicability() -> None:
    clock = MutableClock(BASE_TIME)
    locations = MutableLocationSource(None)
    provider = RecordingProvider([])
    service = build_service(provider, RecordingRepository(), locations, clock)

    state = service.refresh()

    assert provider.calls == []
    assert state.provider_status is WeatherAlertProviderStatus.UNAVAILABLE
    assert state.applicability is WeatherAlertApplicability.UNAVAILABLE
    assert state.snapshot is None
    assert state.last_error is not None
    assert "No retained mobile location" in state.last_error


def test_stale_location_never_calls_provider_or_claims_applicability() -> None:
    clock = MutableClock(BASE_TIME)
    locations = MutableLocationSource(
        location(received_at=BASE_TIME - timedelta(seconds=121))
    )
    provider = RecordingProvider([])
    service = build_service(provider, RecordingRepository(), locations, clock)

    state = service.refresh()

    assert provider.calls == []
    assert state.applicability is WeatherAlertApplicability.UNAVAILABLE
    assert state.last_error is not None
    assert "too old" in state.last_error


def test_provider_failure_retains_data_but_marks_applicability_unverified() -> None:
    clock = MutableClock(BASE_TIME)
    locations = MutableLocationSource(location())
    provider = RecordingProvider(
        [
            snapshot(alerts=(alert(),)),
            ForgeWeatherAlertProviderError("NWS offline"),
        ]
    )
    repository = RecordingRepository()
    service = build_service(provider, repository, locations, clock)
    accepted = service.refresh()
    clock.value = BASE_TIME + timedelta(seconds=30)
    locations.location = location(received_at=clock.value - timedelta(seconds=1))

    failed = service.refresh()

    assert failed.revision == accepted.revision
    assert failed.snapshot == accepted.snapshot
    assert failed.provider_status is WeatherAlertProviderStatus.DEGRADED
    assert failed.applicability is WeatherAlertApplicability.RETAINED_UNVERIFIED
    assert failed.last_error == "NWS offline"
    assert failed.last_success_at == BASE_TIME


def test_startup_retained_snapshot_is_unverified_until_successful_refresh() -> None:
    retained = ForgeWeatherAlertState(
        revision=4,
        snapshot=snapshot(alerts=(alert(),)),
        provider_status=WeatherAlertProviderStatus.HEALTHY,
        applicability=WeatherAlertApplicability.VERIFIED_CURRENT,
    )
    repository = RecordingRepository(retained)
    service = build_service(
        RecordingProvider([]),
        repository,
        MutableLocationSource(None),
        MutableClock(BASE_TIME),
    )

    state = service.get_state()

    assert state.revision == 4
    assert state.snapshot == retained.snapshot
    assert state.provider_status is WeatherAlertProviderStatus.STARTING
    assert state.applicability is WeatherAlertApplicability.RETAINED_UNVERIFIED


def test_enter_and_leave_are_derived_from_successive_trusted_point_results() -> None:
    clock = MutableClock(BASE_TIME)
    locations = MutableLocationSource(location(latitude=39.55))
    provider = PointAwareProvider()
    repository = RecordingRepository()
    service = build_service(provider, repository, locations, clock)

    outside = service.refresh()
    assert outside.snapshot is not None
    assert outside.snapshot.alerts == ()
    assert outside.applicability is WeatherAlertApplicability.VERIFIED_CURRENT

    clock.value += timedelta(seconds=30)
    locations.location = location(
        latitude=39.65,
        received_at=clock.value - timedelta(seconds=1),
    )
    inside = service.refresh()
    assert inside.snapshot is not None
    assert [item.event for item in inside.snapshot.alerts] == ["Tornado Warning"]
    assert inside.applicability is WeatherAlertApplicability.VERIFIED_CURRENT

    clock.value += timedelta(seconds=30)
    locations.location = location(
        latitude=39.75,
        received_at=clock.value - timedelta(seconds=1),
    )
    left = service.refresh()
    assert left.snapshot is not None
    assert left.snapshot.alerts == ()
    assert left.applicability is WeatherAlertApplicability.VERIFIED_CURRENT
    assert len(provider.calls) == 3
