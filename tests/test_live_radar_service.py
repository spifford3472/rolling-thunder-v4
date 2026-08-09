"""Tests for bounded Pi radar viewport coalescing and frame-atomic retention."""

from collections.abc import Callable
from concurrent.futures import Executor, Future
from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import Any, cast

from PIL import Image

from rolling_thunder.forge_radar_client import (
    ForgeRadarConnectionError,
    ForgeRadarManifest,
    ForgeRadarRemoteHealth,
    HttpForgeRadarClient,
)
from rolling_thunder.live_map import GeoPoint
from rolling_thunder.live_radar_service import LiveRadarOverlayService, RadarDataStatus
from rolling_thunder.map_tiles import MapTileKey, build_map_viewport
from rolling_thunder.radar_domain import (
    RadarFrame,
    RadarProductToken,
    RadarProviderStatus,
    RadarSourceMetadata,
)

BASE_TIME = datetime(2026, 8, 9, 1, 30, tzinfo=UTC)
SOURCE = RadarSourceMetadata(
    provider_id="forge_test",
    provider_name="Forge Test Radar",
    product=RadarProductToken.BASE_REFLECTIVITY,
    attribution_text="Radar: Test",
    attribution_url="https://example.invalid/radar",
)


class MutableClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


class MutableMonotonic:
    def __init__(self, value: float = 0.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


class DeferredExecutor:
    def __init__(self) -> None:
        self.tasks: list[Callable[[], object]] = []

    def submit(
        self,
        fn: Callable[..., object],
        /,
        *args: Any,
        **kwargs: Any,
    ) -> Future[object]:
        future: Future[object] = Future()

        def run() -> object:
            try:
                result = fn(*args, **kwargs)
            except BaseException as error:
                future.set_exception(error)
                raise
            future.set_result(result)
            return result

        self.tasks.append(run)
        return future

    def shutdown(self, wait: bool = True, *, cancel_futures: bool = False) -> None:
        if cancel_futures:
            self.tasks.clear()

    def run_next(self) -> None:
        self.tasks.pop(0)()


class ImmediateExecutor(DeferredExecutor):
    def submit(
        self,
        fn: Callable[..., object],
        /,
        *args: Any,
        **kwargs: Any,
    ) -> Future[object]:
        future = super().submit(fn, *args, **kwargs)
        self.run_next()
        return future


class FakeRadarClient:
    def __init__(self, manifests: list[ForgeRadarManifest]) -> None:
        self.manifests = manifests
        self.manifest_calls = 0
        self.tile_calls: list[tuple[str, MapTileKey]] = []
        self.failed_tiles: set[tuple[str, MapTileKey]] = set()

    def fetch_manifest(self) -> ForgeRadarManifest:
        self.manifest_calls += 1
        if not self.manifests:
            raise ForgeRadarConnectionError("manifest offline")
        return self.manifests.pop(0)

    def fetch_tile(self, frame_token: str, key: MapTileKey) -> bytes:
        self.tile_calls.append((frame_token, key))
        if (frame_token, key) in self.failed_tiles:
            raise ForgeRadarConnectionError("tile offline")
        output = BytesIO()
        Image.new("RGBA", (256, 256), (40, 80, 120, 200)).save(output, format="PNG")
        return output.getvalue()


def manifest(token: str, *, revision: int) -> ForgeRadarManifest:
    frame = RadarFrame(
        frame_token=token,
        observed_at=BASE_TIME,
        fetched_at=BASE_TIME + timedelta(seconds=20),
        source=SOURCE,
    )
    return ForgeRadarManifest(
        api_schema_version="1",
        revision=revision,
        frame=frame,
        health=ForgeRadarRemoteHealth(
            status=RadarProviderStatus.HEALTHY,
            stale=False,
            renderable=True,
            revision=revision,
            last_attempt_at=BASE_TIME + timedelta(seconds=20),
            last_success_at=BASE_TIME + timedelta(seconds=20),
        ),
        received_at=BASE_TIME + timedelta(seconds=21),
    )


def test_new_viewports_coalesce_to_one_queued_generation() -> None:
    client = FakeRadarClient([manifest("a" * 32, revision=1)])
    executor = DeferredExecutor()
    service = LiveRadarOverlayService(
        cast(HttpForgeRadarClient, client),
        clock=MutableClock(BASE_TIME + timedelta(minutes=1)),
        executor=cast(Executor, executor),
    )
    first = build_map_viewport(
        GeoPoint(latitude=39.52, longitude=-84.06),
        zoom=7,
        width_px=512,
        height_px=512,
    )
    second = build_map_viewport(
        GeoPoint(latitude=41.50, longitude=-81.69),
        zoom=7,
        width_px=512,
        height_px=512,
    )
    service.start()

    service.request_viewport(first)
    service.request_viewport(second)

    assert len(executor.tasks) == 1
    executor.run_next()
    assert len(executor.tasks) == 1
    executor.run_next()

    assert service.latest_state.viewport == second
    assert service.latest_state.status is RadarDataStatus.READY
    assert client.manifest_calls == 1


def test_partial_new_frame_retains_complete_prior_frame_for_same_viewport() -> None:
    token_one = "a" * 32
    token_two = "b" * 32
    client = FakeRadarClient(
        [
            manifest(token_one, revision=1),
            manifest(token_two, revision=2),
        ]
    )
    monotonic_clock = MutableMonotonic()
    service = LiveRadarOverlayService(
        cast(HttpForgeRadarClient, client),
        clock=MutableClock(BASE_TIME + timedelta(minutes=1)),
        monotonic_clock=monotonic_clock,
        executor=cast(Executor, ImmediateExecutor()),
    )
    viewport = build_map_viewport(
        GeoPoint(latitude=39.52, longitude=-84.06),
        zoom=7,
        width_px=512,
        height_px=512,
    )
    service.start()

    service.request_viewport(viewport)
    first_state = service.latest_state
    assert first_state.status is RadarDataStatus.READY
    assert first_state.frame is not None
    assert first_state.frame.frame_token == token_one
    assert all(tile.png is not None for tile in first_state.tiles)

    monotonic_clock.value = 61.0
    client.failed_tiles.add((token_two, viewport.tile_keys[0]))
    service.request_viewport(viewport)

    retained = service.latest_state
    assert retained.status is RadarDataStatus.STALE
    assert retained.frame is not None
    assert retained.frame.frame_token == token_one
    assert "RETAINING PRIOR FRAME" in retained.detail
    assert all(tile.png is not None for tile in retained.tiles)


def test_manifest_failure_keeps_renderable_cached_frame_but_reports_offline() -> None:
    token = "c" * 32
    client = FakeRadarClient([manifest(token, revision=1)])
    monotonic_clock = MutableMonotonic()
    service = LiveRadarOverlayService(
        cast(HttpForgeRadarClient, client),
        clock=MutableClock(BASE_TIME + timedelta(minutes=2)),
        monotonic_clock=monotonic_clock,
        executor=cast(Executor, ImmediateExecutor()),
    )
    viewport = build_map_viewport(
        GeoPoint(latitude=39.52, longitude=-84.06),
        zoom=7,
        width_px=512,
        height_px=512,
    )
    service.start()

    service.request_viewport(viewport)
    ready = service.latest_state
    assert ready.status is RadarDataStatus.READY
    assert ready.frame is not None
    assert ready.frame.frame_token == token

    monotonic_clock.value = 61.0
    service.request_viewport(viewport)

    degraded = service.latest_state
    assert degraded.status is RadarDataStatus.STALE
    assert degraded.frame is not None
    assert degraded.frame.frame_token == token
    assert degraded.detail == "RADAR OFFLINE — USING CACHED FRAME"
    assert all(tile.png is not None for tile in degraded.tiles)
    assert client.manifest_calls == 2
