from collections.abc import Callable
from concurrent.futures import Executor, Future
from datetime import UTC, datetime, timedelta
from typing import Any

from rolling_thunder.pota_enrichment import (
    ParkDetailStatus,
    ParkImage,
    ParkWeather,
    PotaEnrichmentService,
)
from rolling_thunder.pota_spots import ParkReference


class ImmediateExecutor(Executor):
    def submit(
        self,
        fn: Callable[..., Any],
        /,
        *args: Any,
        **kwargs: Any,
    ) -> Future[Any]:
        future: Future[Any] = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except BaseException as error:
            future.set_exception(error)
        return future


class MutableClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


class FakeCallsignProvider:
    def __init__(self, names: dict[str, str | None]) -> None:
        self.names = names
        self.calls: list[str] = []

    def lookup_name(self, callsign: str) -> str | None:
        self.calls.append(callsign)
        return self.names.get(callsign)


class FakeWeatherProvider:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def fetch_weather(self, park: ParkReference) -> ParkWeather:
        self.calls.append(park.reference)
        return ParkWeather(
            temperature_c=20.0,
            temperature_f=68.0,
            local_time="01:30",
            timezone="America/New_York",
        )


class FakeImageProvider:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def fetch_image(self, park: ParkReference) -> ParkImage:
        self.calls.append(park.reference)
        return ParkImage(
            png_bytes=b"png",
            attribution="Test Photographer",
            license_name="CC BY 4.0",
            source_url="https://commons.example/image",
        )


def park() -> ParkReference:
    return ParkReference(
        reference="US-1940",
        name="Caesar Creek State Park",
        location_code="US-OH",
        latitude=39.489,
        longitude=-84.055,
    )


def test_callsign_names_are_prefetched_and_cached() -> None:
    provider = FakeCallsignProvider({"KI5VNB": "Geoff Kline"})
    service = PotaEnrichmentService(
        callsign_provider=provider,
        executor=ImmediateExecutor(),
    )
    service.start()

    service.prefetch_callsigns(["KI5VNB/P", "KI5VNB"])
    service.prefetch_callsigns(["KI5VNB"])

    assert service.get_callsign_name("KI5VNB") == "Geoff Kline"
    assert provider.calls == ["KI5VNB"]


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


def test_park_detail_combines_weather_and_image_in_background_cache() -> None:
    weather = FakeWeatherProvider()
    image = FakeImageProvider()
    service = PotaEnrichmentService(
        weather_provider=weather,
        image_provider=image,
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
    assert cached.image is not None
    assert cached.image.attribution == "Test Photographer"
    assert weather.calls == ["US-1940"]
    assert image.calls == ["US-1940"]


def test_unavailable_providers_degrade_without_starting_network_work() -> None:
    service = PotaEnrichmentService(executor=ImmediateExecutor())
    service.start()

    snapshot = service.request_park_detail(park())

    assert snapshot.status is ParkDetailStatus.UNAVAILABLE
    assert snapshot.weather_error == "Weather unavailable"
    assert snapshot.image_error == "Image unavailable"


def test_stopped_service_never_submits_new_work() -> None:
    provider = FakeCallsignProvider({"KI5VNB": "Geoff Kline"})
    service = PotaEnrichmentService(
        callsign_provider=provider,
        executor=ImmediateExecutor(),
    )

    service.prefetch_callsigns(["KI5VNB"])

    assert provider.calls == []
    assert service.get_callsign_name("KI5VNB") is None
