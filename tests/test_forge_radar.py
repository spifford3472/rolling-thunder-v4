"""Tests for provider-neutral Forge radar retention, freshness, cache, and API."""

from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import cast
from zipfile import ZipFile

import pytest
from PIL import Image

from rolling_thunder.forge_mobile_location import (
    ForgeMobileLocationService,
    MobileLocationRecord,
    MobileLocationState,
)
from rolling_thunder.forge_radar import (
    ForgeRadarProviderError,
    ForgeRadarService,
    RadarProvider,
    RadarProviderFrame,
)
from rolling_thunder.forge_radar_api import RadarAwareForgeSpotApiApplication
from rolling_thunder.forge_spot_api import ForgeSpotApiApplication
from rolling_thunder.map_tiles import MapTileKey
from rolling_thunder.radar_domain import (
    RadarProductToken,
    RadarProviderStatus,
    RadarSourceMetadata,
)

BASE_TIME = datetime(2026, 8, 9, 1, 30, tzinfo=UTC)
SOURCE = RadarSourceMetadata(
    provider_id="test_radar",
    provider_name="Test Radar",
    product=RadarProductToken.BASE_REFLECTIVITY,
    attribution_text="Radar: Test",
    attribution_url="https://example.invalid/radar",
)


class MutableClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


class FakeLocationSource:
    def get_state(self) -> MobileLocationState:
        return MobileLocationState(
            revision=3,
            location=MobileLocationRecord(
                latitude=39.524492,
                longitude=-84.062475,
                fix_at=BASE_TIME - timedelta(seconds=2),
                received_at=BASE_TIME - timedelta(seconds=1),
            ),
        )


class FakeRadarProvider:
    def __init__(self) -> None:
        self.discovery_error: Exception | None = None
        self.discovery_calls = 0
        self.tile_calls: list[tuple[str, MapTileKey]] = []
        self.coverage_calls: list[tuple[str, int, int, int, int, int]] = []
        self.provider_frame_id = "123"
        self.observed_at = BASE_TIME

    def discover_latest(self, location: MobileLocationRecord) -> RadarProviderFrame:
        self.discovery_calls += 1
        if self.discovery_error is not None:
            raise self.discovery_error
        return RadarProviderFrame(
            provider_frame_id=self.provider_frame_id,
            observed_at=self.observed_at,
            valid_until=self.observed_at + timedelta(minutes=5),
            source=SOURCE,
        )

    def fetch_tile(self, provider_frame_id: str, key: MapTileKey) -> bytes:
        self.tile_calls.append((provider_frame_id, key))
        return png_tile()

    def fetch_coverage(
        self,
        provider_frame_id: str,
        *,
        zoom: int,
        x_start: int,
        y_start: int,
        columns: int,
        rows: int,
    ) -> dict[MapTileKey, bytes]:
        self.coverage_calls.append((provider_frame_id, zoom, x_start, y_start, columns, rows))
        return {
            MapTileKey(zoom=zoom, x=x, y=y): png_tile()
            for x in range(x_start, x_start + columns)
            for y in range(y_start, y_start + rows)
        }


class FakeCoreApplication:
    def handle(self, *args: object, **kwargs: object):
        raise AssertionError("Radar route unexpectedly delegated to core API")


def png_tile() -> bytes:
    output = BytesIO()
    Image.new("RGBA", (256, 256), (20, 40, 60, 180)).save(output, format="PNG")
    return output.getvalue()


def build_service(provider: FakeRadarProvider, clock: MutableClock) -> ForgeRadarService:
    return ForgeRadarService(
        cast(RadarProvider, provider),
        cast(ForgeMobileLocationService, FakeLocationSource()),
        now=clock,
    )


def test_refresh_cache_and_freshness_boundaries() -> None:
    provider = FakeRadarProvider()
    clock = MutableClock(BASE_TIME + timedelta(minutes=1))
    service = build_service(provider, clock)
    key = MapTileKey(zoom=7, x=34, y=49)

    state = service.refresh()
    assert state.revision == 1
    assert state.provider_status is RadarProviderStatus.HEALTHY
    assert state.frame is not None
    assert service.is_stale() is False
    assert service.is_renderable() is True

    first = service.get_tile(state.frame.frame_token, key)
    second = service.get_tile(state.frame.frame_token, key)
    assert first == second
    assert provider.tile_calls == [("123", key)]

    clock.value = BASE_TIME + timedelta(minutes=16)
    assert service.is_stale() is True
    assert service.is_renderable() is True

    clock.value = BASE_TIME + timedelta(minutes=31)
    assert service.is_renderable() is False
    with pytest.raises(ForgeRadarProviderError, match="too old"):
        service.get_tile(state.frame.frame_token, key)


def test_provider_failure_retains_prior_frame_and_degrades_health() -> None:
    provider = FakeRadarProvider()
    clock = MutableClock(BASE_TIME + timedelta(minutes=1))
    service = build_service(provider, clock)
    accepted = service.refresh()
    provider.discovery_error = RuntimeError("provider offline")
    clock.value = BASE_TIME + timedelta(minutes=2)

    failed = service.refresh()

    assert failed.revision == accepted.revision
    assert failed.frame == accepted.frame
    assert failed.provider_status is RadarProviderStatus.DEGRADED
    assert failed.last_error == "provider offline"


def test_previous_frame_remains_retrievable_during_new_frame_handoff() -> None:
    provider = FakeRadarProvider()
    clock = MutableClock(BASE_TIME + timedelta(minutes=1))
    service = build_service(provider, clock)
    first = service.refresh()
    assert first.frame is not None

    provider.provider_frame_id = "124"
    provider.observed_at = BASE_TIME + timedelta(minutes=5)
    clock.value = BASE_TIME + timedelta(minutes=6)
    second = service.refresh()
    assert second.frame is not None
    assert second.frame.frame_token != first.frame.frame_token

    key = MapTileKey(zoom=7, x=34, y=49)
    service.get_tile(first.frame.frame_token, key)

    assert provider.tile_calls[-1] == ("123", key)


def test_bulk_coverage_uses_one_provider_call_and_is_cached() -> None:
    provider = FakeRadarProvider()
    clock = MutableClock(BASE_TIME + timedelta(minutes=1))
    service = build_service(provider, clock)
    state = service.refresh()
    assert state.frame is not None

    first = service.get_coverage(
        state.frame.frame_token,
        zoom=7,
        x_start=34,
        y_start=49,
        columns=2,
        rows=2,
    )
    second = service.get_coverage(
        state.frame.frame_token,
        zoom=7,
        x_start=34,
        y_start=49,
        columns=2,
        rows=2,
    )

    assert first == second
    assert provider.coverage_calls == [("123", 7, 34, 49, 2, 2)]


def test_radar_api_manifest_tile_coverage_and_read_only_contract() -> None:
    provider = FakeRadarProvider()
    clock = MutableClock(BASE_TIME + timedelta(minutes=1))
    service = build_service(provider, clock)
    state = service.refresh()
    assert state.frame is not None
    application = RadarAwareForgeSpotApiApplication(
        cast(ForgeSpotApiApplication, FakeCoreApplication()),
        service,
    )

    manifest = application.handle("GET", "/api/v1/radar")
    assert manifest.status_code == 200
    assert b'"status":"healthy"' in manifest.body
    assert state.frame.frame_token.encode() in manifest.body

    tile = application.handle(
        "GET",
        f"/api/v1/radar/tiles/{state.frame.frame_token}/7/34/49.png",
    )
    assert tile.status_code == 200
    assert tile.body.startswith(b"\x89PNG\r\n\x1a\n")
    assert dict(tile.headers)["X-Rolling-Thunder-Radar-Frame"] == state.frame.frame_token

    coverage = application.handle(
        "GET",
        f"/api/v1/radar/coverage/{state.frame.frame_token}/7/34/49/2/2.zip",
    )
    assert coverage.status_code == 200
    assert dict(coverage.headers)["Content-Type"] == "application/zip"
    with ZipFile(BytesIO(coverage.body)) as archive:
        assert set(archive.namelist()) == {
            "7/34/49.png",
            "7/34/50.png",
            "7/35/49.png",
            "7/35/50.png",
        }

    method = application.handle("POST", "/api/v1/radar")
    assert method.status_code == 405
    assert dict(method.headers)["Allow"] == "GET"

    wrong_frame = application.handle(
        "GET",
        "/api/v1/radar/tiles/0000000000000000/7/34/49.png",
    )
    assert wrong_frame.status_code == 409
