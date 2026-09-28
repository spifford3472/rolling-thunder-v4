from collections.abc import Callable
from concurrent.futures import Executor, Future
from datetime import UTC, datetime, timedelta
from typing import Any

from rolling_thunder.pota_enrichment import (
    ParkDetailStatus,
    ParkWeather,
    PotaEnrichmentService,
    StateOutline,
)
from rolling_thunder.pota_spots import ParkReference
from rolling_thunder.qrz_xml import QrzCallsignProfile


class ImmediateExecutor(Executor):
    def submit(
        self,
        fn: Callable[..., Any],
        /,
        *args: Any,
        **kwargs: Any,
    ) -> Future[Any]:
        future: Future[Any] = Future()
        future.set_result(fn(*args, **kwargs))
        return future


class MutableClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


class FakeCallsignProvider:
    def __init__(self, profiles: dict[str, QrzCallsignProfile | None]) -> None:
        self.profiles = profiles
        self.calls: list[str] = []

    def lookup_profile(self, callsign: str) -> QrzCallsignProfile | None:
        self.calls.append(callsign)
        return self.profiles.get(callsign)


class FakePhotoProvider:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def fetch_photo(self, image_url: str) -> bytes:
        self.calls.append(image_url)
        return b"profile-png"


class FakeWeatherProvider:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def fetch_weather(self, park: ParkReference) -> ParkWeather:
        self.calls.append(park.reference)
        return ParkWeather(
            temperature_c=20.0,
            temperature_f=68.0,
            local_time="01:30",
            weather_code=2,
            is_day=False,
            timezone="America/New_York",
        )


class FakeStateOutlineProvider:
    def __init__(self) -> None:
        self.calls: list[str | None] = []

    def fetch_outline(self, location_code: str | None) -> StateOutline:
        self.calls.append(location_code)
        return StateOutline(
            state_code="OH",
            state_name="Ohio",
            rings=(
                (
                    (-84.8, 38.4),
                    (-80.5, 38.4),
                    (-80.5, 42.0),
                    (-84.8, 42.0),
                    (-84.8, 38.4),
                ),
            ),
        )


def park() -> ParkReference:
    return ParkReference(
        reference="US-1940",
        name="Caesar Creek State Park",
        location_code="US-OH",
        latitude=39.489,
        longitude=-84.055,
    )


def profile(name: str | None = "Geoff Kline") -> QrzCallsignProfile:
    return QrzCallsignProfile(
        callsign="KI5VNB",
        name=name,
        image_url="https://cdn-xml.qrz.com/ki5vnb.jpg",
    )


def test_callsign_names_are_prefetched_and_cached_without_fetching_photos() -> None:
    provider = FakeCallsignProvider({"KI5VNB": profile()})
    photo_provider = FakePhotoProvider()
    service = PotaEnrichmentService(
        callsign_provider=provider,
        callsign_photo_provider=photo_provider,
        executor=ImmediateExecutor(),
    )
    service.start()

    service.prefetch_callsigns(["KI5VNB/P", "KI5VNB"])
    service.prefetch_callsigns(["KI5VNB"])

    assert service.get_callsign_name("KI5VNB") == "Geoff Kline"
    assert provider.calls == ["KI5VNB"]
    assert photo_provider.calls == []


def test_selected_callsign_photo_is_fetched_and_cached() -> None:
    provider = FakeCallsignProvider({"KI5VNB": profile()})
    photo_provider = FakePhotoProvider()
    service = PotaEnrichmentService(
        callsign_provider=provider,
        callsign_photo_provider=photo_provider,
        executor=ImmediateExecutor(),
    )
    service.start()
    service.prefetch_callsigns(["KI5VNB"])

    service.request_callsign_photo("KI5VNB")
    cached = service.get_callsign_profile("KI5VNB")

    assert cached is not None
    assert cached.photo_png == b"profile-png"
    assert photo_provider.calls == ["https://cdn-xml.qrz.com/ki5vnb.jpg"]


def test_negative_callsign_results_are_cached_until_expiry() -> None:
    clock = MutableClock(datetime(2026, 8, 2, 5, 0, tzinfo=UTC))
    provider = FakeCallsignProvider({})
    service = PotaEnrichmentService(
        callsign_provider=provider,
        negative_ttl=timedelta(minutes=10),
        clock=clock,
        executor=ImmediateExecutor(),
    )
    service.start()

    service.prefetch_callsigns(["W8O"])
    service.prefetch_callsigns(["W8O"])
    assert provider.calls == ["W8O"]

    clock.value += timedelta(minutes=11)
    service.prefetch_callsigns(["W8O"])
    assert provider.calls == ["W8O", "W8O"]


def test_park_detail_combines_weather_and_state_outline() -> None:
    weather = FakeWeatherProvider()
    outline = FakeStateOutlineProvider()
    service = PotaEnrichmentService(
        weather_provider=weather,
        state_outline_provider=outline,
        executor=ImmediateExecutor(),
    )
    service.start()

    initial = service.request_park_detail(park())
    cached = service.get_park_detail("US-1940")

    assert initial.status is ParkDetailStatus.LOADING
    assert cached is not None
    assert cached.status is ParkDetailStatus.READY
    assert cached.weather is not None
    assert cached.weather.temperature_f == 68.0
    assert cached.outline is not None
    assert cached.outline.state_code == "OH"
    assert weather.calls == ["US-1940"]
    assert outline.calls == ["US-OH"]


def test_unavailable_providers_degrade_without_starting_network_work() -> None:
    service = PotaEnrichmentService(executor=ImmediateExecutor())
    service.start()

    snapshot = service.request_park_detail(park())

    assert snapshot.status is ParkDetailStatus.UNAVAILABLE
    assert snapshot.weather_error == "Weather unavailable"
    assert snapshot.map_error == "Map unavailable"


def test_stopped_service_never_submits_new_work() -> None:
    provider = FakeCallsignProvider({"KI5VNB": profile()})
    service = PotaEnrichmentService(
        callsign_provider=provider,
        executor=ImmediateExecutor(),
    )

    service.prefetch_callsigns(["KI5VNB"])

    assert provider.calls == []
    assert service.get_callsign_name("KI5VNB") is None
