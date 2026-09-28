"""Tests for Pi retained Forge weather state and failure retention."""

from datetime import UTC, datetime, timedelta

from rolling_thunder.forge_weather import (
    WeatherConditionToken,
    WeatherCurrent,
    WeatherHourlyPoint,
    WeatherIconToken,
    WeatherProviderStatus,
    WeatherSnapshot,
    WeatherSolar,
    WeatherSourceMetadata,
)
from rolling_thunder.forge_weather_client import (
    ForgeRemoteWeatherHealth,
    ForgeWeatherClientResult,
    ForgeWeatherClientTransportError,
    ForgeWeatherClientValidationError,
)
from rolling_thunder.pi_forge_weather_service import (
    PiForgeWeatherErrorKind,
    PiForgeWeatherService,
    PiForgeWeatherStateKind,
)
from rolling_thunder.storage import StorageError

BASE_TIME = datetime(2026, 8, 9, 3, 35, tzinfo=UTC)
SOURCE = WeatherSourceMetadata(
    provider_id="test",
    provider_name="Test Weather",
    attribution_text="Test weather",
    attribution_url="https://example.invalid/weather",
    license_name="Test License",
    license_url="https://example.invalid/license",
)


def snapshot(*, source_at: datetime = BASE_TIME - timedelta(minutes=5), temp: float = 21.0) -> WeatherSnapshot:
    return WeatherSnapshot(
        latitude=39.52449,
        longitude=-84.062475,
        source_at=source_at,
        fetched_at=source_at + timedelta(minutes=1),
        current=WeatherCurrent(
            temperature_c=temp,
            relative_humidity_percent=65.0,
            condition=WeatherConditionToken.CLEAR,
            icon=WeatherIconToken.CLEAR_NIGHT,
            is_day=False,
        ),
        hourly=tuple(
            WeatherHourlyPoint(
                forecast_at=source_at + timedelta(hours=hour),
                temperature_c=temp - hour,
                precipitation_probability_percent=float(hour * 5),
            )
            for hour in (1, 2, 3)
        ),
        solar=WeatherSolar(
            sunrise_at=source_at + timedelta(hours=7),
            sunset_at=source_at + timedelta(hours=20),
        ),
        source=SOURCE,
    )


def result(
    *,
    revision: int = 4,
    weather_snapshot: WeatherSnapshot | None = None,
    stale: bool = False,
    received_at: datetime = BASE_TIME,
) -> ForgeWeatherClientResult:
    weather_snapshot = weather_snapshot if weather_snapshot is not None else snapshot()
    return ForgeWeatherClientResult(
        revision=revision,
        stale=stale,
        snapshot=weather_snapshot,
        health=ForgeRemoteWeatherHealth(
            status=WeatherProviderStatus.HEALTHY,
            stale=stale,
            revision=revision,
            last_attempt_at=received_at - timedelta(seconds=5),
            last_success_at=received_at - timedelta(seconds=5),
        ),
        received_at=received_at,
    )


def no_data_result(*, received_at: datetime = BASE_TIME) -> ForgeWeatherClientResult:
    return ForgeWeatherClientResult(
        revision=0,
        stale=True,
        snapshot=None,
        health=ForgeRemoteWeatherHealth(
            status=WeatherProviderStatus.STARTING,
            stale=True,
            revision=0,
        ),
        received_at=received_at,
    )


class FakeClient:
    def __init__(self, values: list[ForgeWeatherClientResult | BaseException]) -> None:
        self.values = values
        self.calls = 0

    def fetch_weather(self) -> ForgeWeatherClientResult:
        self.calls += 1
        value = self.values.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value


class FakeCache:
    def __init__(
        self,
        stored: ForgeWeatherClientResult | None = None,
        *,
        load_error: StorageError | None = None,
        replace_error: StorageError | None = None,
    ) -> None:
        self.stored = stored
        self.load_error = load_error
        self.replace_error = replace_error
        self.replacements: list[ForgeWeatherClientResult] = []

    def load(self) -> ForgeWeatherClientResult | None:
        if self.load_error is not None:
            raise self.load_error
        return self.stored

    def replace(self, value: ForgeWeatherClientResult) -> None:
        self.replacements.append(value)
        if self.replace_error is not None:
            raise self.replace_error
        self.stored = value


def test_startup_without_cache_is_no_data() -> None:
    service = PiForgeWeatherService(FakeClient([]), FakeCache(), now=lambda: BASE_TIME)
    state = service.get_state()
    assert state.kind is PiForgeWeatherStateKind.NO_DATA
    assert state.snapshot is None
    assert state.last_attempt_at is None


def test_cached_weather_retains_original_source_age_across_restart() -> None:
    old_source = BASE_TIME - timedelta(minutes=40)
    cached = result(
        weather_snapshot=snapshot(source_at=old_source),
        received_at=BASE_TIME - timedelta(minutes=35),
    )
    service = PiForgeWeatherService(
        FakeClient([]),
        FakeCache(cached),
        now=lambda: BASE_TIME,
        stale_after_s=1_800.0,
    )

    state = service.get_state()
    assert state.kind is PiForgeWeatherStateKind.RETAINED
    assert state.stale is True
    assert state.source_at == old_source
    assert state.last_success_at == BASE_TIME - timedelta(minutes=35)


def test_refresh_persists_before_publishing_new_live_snapshot() -> None:
    candidate = result(revision=5, weather_snapshot=snapshot(temp=25.0))
    cache = FakeCache()
    service = PiForgeWeatherService(FakeClient([candidate]), cache, now=lambda: BASE_TIME)

    state = service.refresh()

    assert cache.replacements == [candidate]
    assert state.kind is PiForgeWeatherStateKind.LIVE
    assert state.snapshot_revision == 5
    assert state.snapshot is not None
    assert state.snapshot.current.temperature_c == 25.0
    assert state.last_success_at == BASE_TIME


def test_failed_cache_write_does_not_publish_unpersisted_candidate() -> None:
    prior = result(revision=4, weather_snapshot=snapshot(temp=20.0))
    candidate = result(revision=5, weather_snapshot=snapshot(temp=30.0))
    cache = FakeCache(prior, replace_error=StorageError("disk full"))
    service = PiForgeWeatherService(FakeClient([candidate]), cache, now=lambda: BASE_TIME)

    state = service.refresh()

    assert state.kind is PiForgeWeatherStateKind.RETAINED
    assert state.snapshot_revision == 4
    assert state.snapshot is not None
    assert state.snapshot.current.temperature_c == 20.0
    assert state.error_kind is PiForgeWeatherErrorKind.STORAGE_WRITE
    assert state.last_error == "disk full"


def test_transport_and_validation_failures_retain_last_good_snapshot() -> None:
    prior = result(revision=4)
    client = FakeClient(
        [
            ForgeWeatherClientTransportError("offline"),
            ForgeWeatherClientValidationError("bad schema"),
        ]
    )
    service = PiForgeWeatherService(client, FakeCache(prior), now=lambda: BASE_TIME)

    transport = service.refresh()
    assert transport.kind is PiForgeWeatherStateKind.RETAINED
    assert transport.snapshot_revision == 4
    assert transport.error_kind is PiForgeWeatherErrorKind.TRANSPORT

    validation = service.refresh()
    assert validation.kind is PiForgeWeatherStateKind.RETAINED
    assert validation.snapshot_revision == 4
    assert validation.error_kind is PiForgeWeatherErrorKind.VALIDATION


def test_live_no_data_is_truthful_without_erasing_last_good_weather() -> None:
    service = PiForgeWeatherService(
        FakeClient([no_data_result()]),
        FakeCache(),
        now=lambda: BASE_TIME,
    )
    no_data = service.refresh()
    assert no_data.kind is PiForgeWeatherStateKind.NO_DATA
    assert no_data.snapshot is None
    assert no_data.stale is True
    assert no_data.last_success_at == BASE_TIME

    prior = result(revision=4)
    retained_service = PiForgeWeatherService(
        FakeClient([no_data_result()]),
        FakeCache(prior),
        now=lambda: BASE_TIME,
    )
    retained = retained_service.refresh()
    assert retained.kind is PiForgeWeatherStateKind.RETAINED
    assert retained.snapshot_revision == 4
    assert retained.snapshot is not None
    assert retained.stale is True
    assert retained.health is not None
    assert retained.health.revision == 0


def test_cache_read_error_is_distinct_storage_state() -> None:
    service = PiForgeWeatherService(
        FakeClient([]),
        FakeCache(load_error=StorageError("corrupt cache")),
        now=lambda: BASE_TIME,
    )
    state = service.get_state()
    assert state.kind is PiForgeWeatherStateKind.NO_DATA
    assert state.error_kind is PiForgeWeatherErrorKind.STORAGE_READ
    assert state.last_error == "corrupt cache"
