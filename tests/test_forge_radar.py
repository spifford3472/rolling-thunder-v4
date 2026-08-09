"""Tests for provider-neutral Forge radar retention, freshness, cache, and API."""

from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import cast

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

    def discover_latest(self, location: MobileLocationRecord) -> RadarProviderFrame:
        self.discovery_calls += 1
        if self.discovery_error is not None:
            raise self.discovery_error
        return RadarProviderFrame(
            provider_frame_id="123",
            observed_at=BASE_TIME,
            valid_until=BASE_TIME + timedelta(minutes=5),
            source=SOURCE,
        )

    def fetch_tile(self, provider_frame_id: str, key: MapTileKey) -> bytes:
        self.tile_calls.append((provider_frame_id, key))
        output = BytesIO()
        Image.new("RGBA", (256, 256), (20, 40, 60, 180)).save(output, format="PNG")
        return output.getvalue()


class FakeCoreApplication:
    def handle(self, *args: object, **kwargs: object):
        raise AssertionError("Radar route unexpectedly delegated to core API")


def build_service(
    provider: FakeRadarProvider,
    clock: MutableClock,
) -> ForgeRadarService:
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


def test_radar_api_manifest_tile_and_read_only_contract() -> None:
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

    method = application.handle("POST", "/api/v1/radar")
    assert method.status_code == 405
    assert dict(method.headers)["Allow"] == "GET"

    wrong_frame = application.handle(
        "GET",
        "/api/v1/radar/tiles/0000000000000000/7/34/49.png",
    )
    assert wrong_frame.status_code == 409
