"""Tests for bounded Pi radar FRONT/BACK buffering and exact-frame retention."""

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
from rolling_thunder.map_tiles import MapTileKey, MapViewport, build_map_viewport
from rolling_thunder.radar_coverage import (
    build_radar_coverage_viewport,
    radar_viewport_is_covered,
)
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
_TILE_OUTPUT = BytesIO()
Image.new("RGBA", (256, 256), (40, 80, 120, 200)).save(_TILE_OUTPUT, format="PNG")
TILE_PNG = _TILE_OUTPUT.getvalue()


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
        self.on_tile_call: Callable[[str, MapTileKey], None] | None = None

    def fetch_manifest(self) -> ForgeRadarManifest:
        self.manifest_calls += 1
        if not self.manifests:
            raise ForgeRadarConnectionError("manifest offline")
        return self.manifests.pop(0)

    def fetch_tile(self, frame_token: str, key: MapTileKey) -> bytes:
        self.tile_calls.append((frame_token, key))
        callback = self.on_tile_call
        if callback is not None:
            callback(frame_token, key)
        if (frame_token, key) in self.failed_tiles:
            raise ForgeRadarConnectionError("tile offline")
        return TILE_PNG


def manifest(
    token: str,
    *,
    revision: int,
    observed_at: datetime = BASE_TIME,
    status: RadarProviderStatus = RadarProviderStatus.HEALTHY,
    renderable: bool = True,
) -> ForgeRadarManifest:
    frame = RadarFrame(
        frame_token=token,
        observed_at=observed_at,
        fetched_at=observed_at + timedelta(seconds=20),
        source=SOURCE,
    )
    return ForgeRadarManifest(
        api_schema_version="1",
        revision=revision,
        frame=frame,
        health=ForgeRadarRemoteHealth(
            status=status,
            stale=(status is not RadarProviderStatus.HEALTHY),
            renderable=renderable,
            revision=revision,
            last_attempt_at=observed_at + timedelta(seconds=20),
            last_success_at=observed_at + timedelta(seconds=20),
        ),
        received_at=observed_at + timedelta(seconds=21),
    )


def viewport(*, east_tiles: int = 0, zoom: int = 7) -> MapViewport:
    longitude = -84.06 + east_tiles * 360.0 / (1 << zoom)
    return build_map_viewport(
        GeoPoint(latitude=39.52, longitude=longitude),
        zoom=zoom,
        width_px=512,
        height_px=512,
    )


def build_service(
    client: FakeRadarClient,
    *,
    executor: DeferredExecutor | None = None,
    clock: MutableClock | None = None,
    monotonic_clock: MutableMonotonic | None = None,
) -> tuple[LiveRadarOverlayService, DeferredExecutor, MutableClock, MutableMonotonic]:
    resolved_executor = executor or DeferredExecutor()
    resolved_clock = clock or MutableClock(BASE_TIME + timedelta(minutes=1))
    resolved_monotonic = monotonic_clock or MutableMonotonic()
    service = LiveRadarOverlayService(
        cast(HttpForgeRadarClient, client),
        clock=resolved_clock,
        monotonic_clock=resolved_monotonic,
        executor=cast(Executor, resolved_executor),
    )
    service.start()
    return service, resolved_executor, resolved_clock, resolved_monotonic


def load_initial(
    service: LiveRadarOverlayService,
    executor: DeferredExecutor,
    target: MapViewport | None = None,
) -> MapViewport:
    resolved = target or viewport()
    service.request_viewport(resolved)
    executor.run_next()
    assert service.latest_state.status is RadarDataStatus.READY
    return resolved


def test_initial_visible_viewport_builds_larger_complete_coverage_buffer() -> None:
    token = "a" * 32
    client = FakeRadarClient([manifest(token, revision=1)])
    service, executor, _clock, _monotonic = build_service(client)
    visible = viewport()

    service.request_viewport(visible)
    loading = service.latest_state
    assert loading.status is RadarDataStatus.LOADING
    assert loading.tiles == ()

    executor.run_next()
    ready = service.latest_state
    assert ready.status is RadarDataStatus.READY
    assert ready.viewport == visible
    assert ready.coverage_viewport is not None
    assert ready.coverage_viewport.width_px == visible.width_px + 12 * 256
    assert ready.coverage_viewport.height_px == visible.height_px + 12 * 256
    assert radar_viewport_is_covered(visible, ready.coverage_viewport)
    assert len(ready.coverage_viewport.tile_keys) > len(visible.tile_keys)
    assert len(client.tile_calls) == len(ready.coverage_viewport.tile_keys)
    assert {frame_token for frame_token, _key in client.tile_calls} == {token}


def test_one_and_two_tile_movement_reframes_front_with_zero_radar_http_work() -> None:
    token = "a" * 32
    client = FakeRadarClient([manifest(token, revision=1)])
    service, executor, _clock, _monotonic = build_service(client)
    initial = load_initial(service, executor)
    initial_calls = len(client.tile_calls)
    initial_manifest_calls = client.manifest_calls
    initial_observed = service.latest_state.frame.observed_at if service.latest_state.frame else None
    initial_coverage = service.latest_state.coverage_viewport

    one_tile = viewport(east_tiles=1)
    service.request_viewport(one_tile)
    one_state = service.latest_state
    assert one_state.status is RadarDataStatus.READY
    assert one_state.viewport == one_tile
    assert one_state.coverage_viewport == initial_coverage
    assert client.tile_calls[initial_calls:] == []
    assert client.manifest_calls == initial_manifest_calls

    two_tiles = viewport(east_tiles=2)
    service.request_viewport(two_tiles)
    two_state = service.latest_state
    assert two_state.status is RadarDataStatus.READY
    assert two_state.viewport == two_tiles
    assert two_state.coverage_viewport == initial_coverage
    assert client.tile_calls[initial_calls:] == []
    assert client.manifest_calls == initial_manifest_calls
    assert two_state.frame is not None
    assert two_state.frame.observed_at == initial_observed
    assert two_state.viewport != initial


def test_three_tile_threshold_keeps_front_visible_until_atomic_back_swap() -> None:
    token = "a" * 32
    client = FakeRadarClient([manifest(token, revision=1)])
    service, executor, _clock, _monotonic = build_service(client)
    load_initial(service, executor)
    old_coverage = service.latest_state.coverage_viewport
    old_call_count = len(client.tile_calls)

    moved = viewport(east_tiles=3)
    service.request_viewport(moved)

    during = service.latest_state
    assert len(executor.tasks) == 1
    assert during.status is RadarDataStatus.LOADING
    assert during.frame is not None
    assert during.frame.frame_token == token
    assert during.tiles
    assert all(tile.png is not None for tile in during.tiles)
    assert during.coverage_viewport == old_coverage
    assert client.manifest_calls == 1
    assert len(client.tile_calls) == old_call_count

    executor.run_next()

    swapped = service.latest_state
    assert swapped.status is RadarDataStatus.READY
    assert swapped.viewport == moved
    assert swapped.coverage_viewport is not None
    assert swapped.coverage_viewport != old_coverage
    assert radar_viewport_is_covered(moved, swapped.coverage_viewport)
    assert client.manifest_calls == 1
    added_calls = len(client.tile_calls) - old_call_count
    assert 0 < added_calls < len(swapped.coverage_viewport.tile_keys)
    assert swapped.frame is not None
    assert swapped.frame.frame_token == token


def test_failed_partial_back_load_retains_complete_usable_front() -> None:
    token = "a" * 32
    client = FakeRadarClient([manifest(token, revision=1)])
    service, executor, _clock, _monotonic = build_service(client)
    load_initial(service, executor)
    front_before = service.latest_state
    assert front_before.coverage_viewport is not None

    moved = viewport(east_tiles=3)
    new_coverage = build_radar_coverage_viewport(moved)
    missing = next(
        key
        for key in new_coverage.tile_keys
        if key not in set(front_before.coverage_viewport.tile_keys)
    )
    client.failed_tiles.add((token, missing))

    service.request_viewport(moved)
    during = service.latest_state
    assert during.status is RadarDataStatus.LOADING
    assert during.frame == front_before.frame
    assert during.tiles

    executor.run_next()

    retained = service.latest_state
    assert retained.status is RadarDataStatus.STALE
    assert retained.frame == front_before.frame
    assert retained.coverage_viewport == front_before.coverage_viewport
    assert retained.tiles
    assert all(tile.png is not None for tile in retained.tiles)
    assert "RETAINING PRIOR FRAME" in retained.detail


def test_failure_beyond_front_geographic_coverage_does_not_stretch_old_radar() -> None:
    token = "a" * 32
    client = FakeRadarClient([manifest(token, revision=1)])
    service, executor, _clock, _monotonic = build_service(client)
    load_initial(service, executor)

    front_coverage = service.latest_state.coverage_viewport
    assert front_coverage is not None
    far = viewport(east_tiles=8)
    target_coverage = build_radar_coverage_viewport(far)
    old_keys = set(front_coverage.tile_keys)
    failed_key = next(key for key in target_coverage.tile_keys if key not in old_keys)
    client.failed_tiles.add((token, failed_key))

    service.request_viewport(far)
    assert service.latest_state.status is RadarDataStatus.LOADING
    assert service.latest_state.tiles == ()
    executor.run_next()

    failed = service.latest_state
    assert failed.status is RadarDataStatus.UNAVAILABLE
    assert failed.tiles == ()
    assert failed.frame is None


def test_rapid_movement_coalesces_to_one_active_and_one_newest_target() -> None:
    token = "a" * 32
    client = FakeRadarClient([manifest(token, revision=1)])
    service, executor, _clock, _monotonic = build_service(client)
    load_initial(service, executor)

    service.request_viewport(viewport(east_tiles=3))
    service.request_viewport(viewport(east_tiles=6))
    service.request_viewport(viewport(east_tiles=9))

    assert len(executor.tasks) == 1
    executor.run_next()
    assert len(executor.tasks) == 1
    executor.run_next()

    final = service.latest_state
    assert final.status is RadarDataStatus.READY
    assert final.viewport == viewport(east_tiles=9)
    assert final.coverage_viewport is not None
    assert radar_viewport_is_covered(viewport(east_tiles=9), final.coverage_viewport)


def test_superseded_worker_stops_requesting_obsolete_tiles_after_newest_target_arrives() -> None:
    token = "a" * 32
    client = FakeRadarClient([manifest(token, revision=1)])
    service, executor, _clock, _monotonic = build_service(client)
    load_initial(service, executor)
    base_calls = len(client.tile_calls)
    fired = False

    def supersede(_token: str, _key: MapTileKey) -> None:
        nonlocal fired
        if fired:
            return
        fired = True
        service.request_viewport(viewport(east_tiles=9))

    client.on_tile_call = supersede
    service.request_viewport(viewport(east_tiles=3))
    executor.run_next()

    obsolete_calls = len(client.tile_calls) - base_calls
    assert obsolete_calls == 1
    assert len(executor.tasks) == 1

    client.on_tile_call = None
    executor.run_next()
    assert service.latest_state.viewport == viewport(east_tiles=9)


def test_temporal_refresh_can_adopt_new_frame_without_spatial_movement() -> None:
    token_one = "a" * 32
    token_two = "b" * 32
    client = FakeRadarClient(
        [
            manifest(token_one, revision=1),
            manifest(
                token_two,
                revision=2,
                observed_at=BASE_TIME + timedelta(minutes=2),
            ),
        ]
    )
    service, executor, _clock, monotonic_clock = build_service(client)
    target = load_initial(service, executor)
    first_tile_count = len(client.tile_calls)

    monotonic_clock.value = 61.0
    service.request_viewport(target)

    during = service.latest_state
    assert during.status is RadarDataStatus.LOADING
    assert during.frame is not None
    assert during.frame.frame_token == token_one
    assert during.tiles
    executor.run_next()

    refreshed = service.latest_state
    assert refreshed.status is RadarDataStatus.READY
    assert refreshed.frame is not None
    assert refreshed.frame.frame_token == token_two
    assert refreshed.frame.observed_at == BASE_TIME + timedelta(minutes=2)
    assert client.manifest_calls == 2
    assert refreshed.coverage_viewport is not None
    assert len(client.tile_calls) - first_tile_count == len(
        refreshed.coverage_viewport.tile_keys
    )


def test_temporal_manifest_check_same_frame_reuses_complete_front_without_tile_calls() -> None:
    token = "a" * 32
    client = FakeRadarClient(
        [
            manifest(token, revision=1),
            manifest(token, revision=1),
        ]
    )
    service, executor, _clock, monotonic_clock = build_service(client)
    target = load_initial(service, executor)
    initial_tile_calls = len(client.tile_calls)

    monotonic_clock.value = 61.0
    service.request_viewport(target)
    executor.run_next()

    assert service.latest_state.status is RadarDataStatus.READY
    assert client.manifest_calls == 2
    assert len(client.tile_calls) == initial_tile_calls


def test_spatial_recenter_uses_cached_manifest_independently_of_weather_check() -> None:
    token = "a" * 32
    client = FakeRadarClient([manifest(token, revision=1)])
    service, executor, _clock, _monotonic = build_service(client)
    load_initial(service, executor)

    service.request_viewport(viewport(east_tiles=3))
    executor.run_next()

    assert service.latest_state.status is RadarDataStatus.READY
    assert client.manifest_calls == 1


def test_manifest_failure_retains_renderable_front_and_reports_degraded() -> None:
    token = "c" * 32
    client = FakeRadarClient([manifest(token, revision=1)])
    service, executor, _clock, monotonic_clock = build_service(client)
    target = load_initial(service, executor)
    initial_tile_calls = len(client.tile_calls)

    monotonic_clock.value = 61.0
    service.request_viewport(target)
    executor.run_next()

    degraded = service.latest_state
    assert degraded.status is RadarDataStatus.STALE
    assert degraded.frame is not None
    assert degraded.frame.frame_token == token
    assert degraded.detail == "RADAR OFFLINE — USING CACHED FRAME"
    assert degraded.tiles
    assert client.manifest_calls == 2
    assert len(client.tile_calls) == initial_tile_calls


def test_stale_and_hide_age_policies_remain_based_on_provider_observation_time() -> None:
    token = "a" * 32
    client = FakeRadarClient([manifest(token, revision=1)])
    clock = MutableClock(BASE_TIME + timedelta(minutes=1))
    service, executor, _clock, _monotonic = build_service(client, clock=clock)
    target = load_initial(service, executor)

    clock.value = BASE_TIME + timedelta(minutes=16)
    service.request_viewport(target)
    stale = service.latest_state
    assert stale.status is RadarDataStatus.STALE
    assert stale.frame is not None
    assert stale.frame.observed_at == BASE_TIME
    assert stale.tiles

    clock.value = BASE_TIME + timedelta(minutes=31)
    service.request_viewport(target)
    hidden = service.latest_state
    assert hidden.status is RadarDataStatus.LOADING
    assert hidden.frame is None
    assert hidden.tiles == ()


def test_zoom_change_hides_old_zoom_until_correct_back_buffer_is_complete() -> None:
    token = "a" * 32
    client = FakeRadarClient([manifest(token, revision=1)])
    service, executor, _clock, _monotonic = build_service(client)
    load_initial(service, executor)

    zoomed = viewport(zoom=8)
    service.request_viewport(zoomed)

    during = service.latest_state
    assert during.status is RadarDataStatus.LOADING
    assert during.viewport == zoomed
    assert during.frame is None
    assert during.tiles == ()

    executor.run_next()
    ready = service.latest_state
    assert ready.status is RadarDataStatus.READY
    assert ready.viewport == zoomed
    assert ready.coverage_viewport is not None
    assert ready.coverage_viewport.zoom == 8
    assert all(tile.placement.key.zoom == 8 for tile in ready.tiles)


def test_disable_suppresses_inflight_publication_and_reenable_builds_fresh_buffer() -> None:
    token = "d" * 32
    client = FakeRadarClient(
        [
            manifest(token, revision=1),
            manifest(token, revision=1),
        ]
    )
    service, executor, _clock, _monotonic = build_service(client)
    target = viewport()

    service.request_viewport(target)
    assert service.latest_state.status is RadarDataStatus.LOADING
    assert service.set_display_enabled(False) is True
    assert service.latest_state.status is RadarDataStatus.DISABLED
    executor.run_next()
    assert service.latest_state.status is RadarDataStatus.DISABLED
    assert service.latest_state.tiles == ()

    assert service.set_display_enabled(True) is True
    service.request_viewport(target)
    assert len(executor.tasks) == 1
    executor.run_next()
    assert service.latest_state.status is RadarDataStatus.READY
    assert service.latest_state.tiles


def test_disabled_service_skips_all_radar_network_work_until_enabled() -> None:
    client = FakeRadarClient([manifest("a" * 32, revision=1)])
    executor = DeferredExecutor()
    service = LiveRadarOverlayService(
        cast(HttpForgeRadarClient, client),
        display_enabled=False,
        clock=MutableClock(BASE_TIME + timedelta(minutes=1)),
        executor=cast(Executor, executor),
    )
    target = viewport()
    service.start()

    service.request_viewport(target)
    assert executor.tasks == []
    assert client.manifest_calls == 0
    assert client.tile_calls == []

    assert service.set_display_enabled(True) is True
    service.request_viewport(target)
    executor.run_next()
    assert service.latest_state.status is RadarDataStatus.READY


def test_failed_back_retry_is_bounded_instead_of_queuing_every_ui_refresh() -> None:
    token = "a" * 32
    client = FakeRadarClient([manifest(token, revision=1)])
    service, executor, _clock, monotonic_clock = build_service(client)
    load_initial(service, executor)
    moved = viewport(east_tiles=3)
    new_coverage = build_radar_coverage_viewport(moved)
    old_coverage = service.latest_state.coverage_viewport
    assert old_coverage is not None
    old_keys = set(old_coverage.tile_keys)
    failed_key = next(key for key in new_coverage.tile_keys if key not in old_keys)
    client.failed_tiles.add((token, failed_key))

    service.request_viewport(moved)
    executor.run_next()
    assert service.latest_state.status is RadarDataStatus.STALE

    for _ in range(10):
        service.request_viewport(moved)
    assert executor.tasks == []

    monotonic_clock.value = 5.1
    service.request_viewport(moved)
    assert len(executor.tasks) == 1
