"""Tests for background live-map tile loading and degradation."""

from concurrent.futures import Executor, Future
from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import Any

from PIL import Image

from rolling_thunder.live_map import GeoPoint
from rolling_thunder.live_map_service import LiveMapService, MapDataStatus
from rolling_thunder.map_sources import (
    InstalledMapRegistry,
    MapTileResolver,
    MapTileSource,
    ResolvedMapTile,
)
from rolling_thunder.map_tiles import CachedMapTile, MapTileError, MapTileKey

NOW = datetime(2026, 8, 2, 20, 0, tzinfo=UTC)


def png_tile(value: int = 20) -> bytes:
    image = Image.new("RGB", (256, 256), (value, value, value))
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


class ImmediateExecutor(Executor):
    def submit(
        self,
        function: Any,
        /,
        *args: Any,
        **kwargs: Any,
    ) -> Future[Any]:
        future: Future[Any] = Future()
        future.set_result(function(*args, **kwargs))
        return future


class FakeCache:
    def __init__(
        self,
        entries: dict[MapTileKey, CachedMapTile] | None = None,
    ) -> None:
        self.entries = entries or {}
        self.reads: list[MapTileKey] = []
        self.writes: list[tuple[MapTileKey, bytes]] = []

    def read(self, key: MapTileKey) -> CachedMapTile | None:
        self.reads.append(key)
        return self.entries.get(key)

    def write(self, key: MapTileKey, png: bytes) -> None:
        self.writes.append((key, png))
        self.entries[key] = CachedMapTile(
            png=png,
            stored_at=NOW,
            is_fresh=True,
        )


class FakeClient:
    def __init__(
        self,
        *,
        body: bytes | None = None,
        failures: set[MapTileKey] | None = None,
    ) -> None:
        self.body = body or png_tile()
        self.failures = failures or set()
        self.requests: list[MapTileKey] = []

    def fetch(self, key: MapTileKey) -> bytes:
        self.requests.append(key)
        if key in self.failures:
            raise MapTileError("offline")
        return self.body


class OfflineCoverageResolver(MapTileResolver):
    """Return missing installed-coverage tiles without network authority."""

    def __init__(self) -> None:
        self.refreshes: list[MapTileKey] = []
        self.closed = False

    def read_local(self, key: MapTileKey) -> ResolvedMapTile:
        return ResolvedMapTile(
            png=None,
            source=MapTileSource.MISSING,
            online_refresh_allowed=False,
        )

    def refresh_online(
        self,
        key: MapTileKey,
        fallback: ResolvedMapTile,
    ) -> ResolvedMapTile:
        self.refreshes.append(key)
        return fallback

    def close(self) -> None:
        self.closed = True


def requested_keys() -> tuple[MapTileKey, ...]:
    from rolling_thunder.map_tiles import build_map_viewport

    return build_map_viewport(
        GeoPoint(39.53, -84.08),
        zoom=13,
        width_px=600,
        height_px=400,
    ).tile_keys


def service(
    client: FakeClient,
    cache: FakeCache,
) -> LiveMapService:
    return LiveMapService(
        MapTileResolver(
            InstalledMapRegistry(),
            cache,
            client,
        ),
        zoom=13,
        clock=lambda: NOW,
        executor=ImmediateExecutor(),
    )


def test_service_ignores_requests_until_started() -> None:
    client = FakeClient()
    live_map = service(client, FakeCache())

    live_map.request_viewport(
        GeoPoint(39.53, -84.08),
        width_px=600,
        height_px=400,
    )

    assert live_map.latest_state.status is MapDataStatus.IDLE
    assert client.requests == []


def test_service_loads_missing_tiles_and_publishes_ready_snapshot() -> None:
    client = FakeClient()
    cache = FakeCache()
    live_map = service(client, cache)
    live_map.start()

    live_map.request_viewport(
        GeoPoint(39.53, -84.08),
        width_px=600,
        height_px=400,
    )

    state = live_map.latest_state
    assert state.status is MapDataStatus.READY
    assert state.detail == "MAP READY"
    assert state.viewport is not None
    assert all(tile.png is not None for tile in state.tiles)
    assert {tile.source for tile in state.tiles} == {MapTileSource.NETWORK}
    assert set(client.requests) == set(requested_keys())
    assert {key for key, _ in cache.writes} == set(requested_keys())


def test_service_never_refreshes_missing_installed_coverage() -> None:
    resolver = OfflineCoverageResolver()
    live_map = LiveMapService(
        resolver,
        zoom=13,
        clock=lambda: NOW,
        executor=ImmediateExecutor(),
    )
    live_map.start()

    live_map.request_viewport(
        GeoPoint(39.53, -84.08),
        width_px=600,
        height_px=400,
    )

    state = live_map.latest_state

    assert state.status is MapDataStatus.UNAVAILABLE
    assert state.detail == "MAP DATA UNAVAILABLE"
    assert state.tiles
    assert all(tile.png is None for tile in state.tiles)
    assert {tile.source for tile in state.tiles} == {MapTileSource.MISSING}
    assert resolver.refreshes == []

    live_map.stop()

    assert resolver.closed is True


def test_service_uses_fresh_cache_without_network() -> None:
    cached = CachedMapTile(
        png=png_tile(40),
        stored_at=NOW,
        is_fresh=True,
    )
    cache = FakeCache({key: cached for key in requested_keys()})
    client = FakeClient()
    live_map = service(client, cache)
    live_map.start()

    live_map.request_viewport(
        GeoPoint(39.53, -84.08),
        width_px=600,
        height_px=400,
    )

    state = live_map.latest_state
    assert state.status is MapDataStatus.READY
    assert {tile.source for tile in state.tiles} == {MapTileSource.CACHE}
    assert client.requests == []


def test_service_uses_stale_cache_when_refresh_fails() -> None:
    cached = CachedMapTile(
        png=png_tile(50),
        stored_at=NOW - timedelta(days=8),
        is_fresh=False,
    )
    keys = requested_keys()
    cache = FakeCache({key: cached for key in keys})
    client = FakeClient(failures=set(keys))
    live_map = service(client, cache)
    live_map.start()

    live_map.request_viewport(
        GeoPoint(39.53, -84.08),
        width_px=600,
        height_px=400,
    )

    state = live_map.latest_state
    assert state.status is MapDataStatus.CACHE_ONLY
    assert state.detail == "MAP DATA OFFLINE — USING CACHE"
    assert {tile.source for tile in state.tiles} == {MapTileSource.STALE_CACHE}


def test_service_publishes_partial_snapshot_when_some_tiles_fail() -> None:
    keys = requested_keys()
    failed = {keys[0]}
    client = FakeClient(failures=failed)
    live_map = service(client, FakeCache())
    live_map.start()

    live_map.request_viewport(
        GeoPoint(39.53, -84.08),
        width_px=600,
        height_px=400,
    )

    state = live_map.latest_state
    assert state.status is MapDataStatus.PARTIAL
    assert any(tile.source is MapTileSource.MISSING for tile in state.tiles)
    assert any(tile.png is not None for tile in state.tiles)


def test_service_publishes_unavailable_when_every_tile_fails() -> None:
    keys = requested_keys()
    client = FakeClient(failures=set(keys))
    live_map = service(client, FakeCache())
    live_map.start()

    live_map.request_viewport(
        GeoPoint(39.53, -84.08),
        width_px=600,
        height_px=400,
    )

    state = live_map.latest_state
    assert state.status is MapDataStatus.UNAVAILABLE
    assert state.detail == "MAP DATA UNAVAILABLE"
    assert all(tile.png is None for tile in state.tiles)


def test_service_reframes_same_tile_set_without_more_io() -> None:
    client = FakeClient()
    live_map = service(client, FakeCache())
    live_map.start()
    live_map.request_viewport(
        GeoPoint(39.53, -84.08),
        width_px=600,
        height_px=400,
    )
    first_state = live_map.latest_state
    request_count = len(client.requests)

    live_map.request_viewport(
        GeoPoint(39.5301, -84.0801),
        width_px=600,
        height_px=400,
    )

    second_state = live_map.latest_state
    assert len(client.requests) == request_count
    assert second_state.viewport is not None
    assert first_state.viewport is not None
    assert second_state.viewport.center != first_state.viewport.center
    assert second_state.status is MapDataStatus.READY


def test_service_ignores_an_identical_loaded_viewport() -> None:
    client = FakeClient()
    live_map = service(client, FakeCache())
    live_map.start()
    live_map.request_viewport(
        GeoPoint(39.53, -84.08),
        width_px=600,
        height_px=400,
    )
    first_state = live_map.latest_state
    request_count = len(client.requests)

    live_map.request_viewport(
        GeoPoint(39.53, -84.08),
        width_px=600,
        height_px=400,
    )

    assert live_map.latest_state is first_state
    assert len(client.requests) == request_count


def test_service_stop_is_idempotent() -> None:
    live_map = service(FakeClient(), FakeCache())
    live_map.start()

    live_map.stop()
    live_map.stop()

    assert live_map.is_running is False


class ManualExecutor(Executor):
    """Retain submitted work until a test explicitly runs it."""

    def __init__(self) -> None:
        self.tasks: list[
            tuple[
                Future[Any],
                Any,
                tuple[Any, ...],
                dict[str, Any],
            ]
        ] = []

    def submit(
        self,
        function: Any,
        /,
        *args: Any,
        **kwargs: Any,
    ) -> Future[Any]:
        future: Future[Any] = Future()
        self.tasks.append((future, function, args, kwargs))
        return future

    def run_next(self) -> None:
        future, function, args, kwargs = self.tasks.pop(0)
        try:
            future.set_result(function(*args, **kwargs))
        except BaseException as exc:
            future.set_exception(exc)
            raise


def test_newer_viewport_supersedes_obsolete_network_work() -> None:
    from rolling_thunder.map_tiles import build_map_viewport

    first_position = GeoPoint(39.53, -84.08)
    latest_position = GeoPoint(39.96, -82.99)
    executor = ManualExecutor()
    client = FakeClient()
    cache = FakeCache()
    live_map = LiveMapService(
        MapTileResolver(
            InstalledMapRegistry(),
            cache,
            client,
        ),
        zoom=13,
        clock=lambda: NOW,
        executor=executor,
    )
    live_map.start()

    live_map.request_viewport(
        first_position,
        width_px=600,
        height_px=400,
    )
    live_map.request_viewport(
        latest_position,
        width_px=600,
        height_px=400,
    )

    queued_state = live_map.latest_state
    assert queued_state.status is MapDataStatus.LOADING
    assert queued_state.viewport is not None
    assert queued_state.viewport.center == latest_position
    assert len(executor.tasks) == 1

    executor.run_next()

    assert client.requests == []
    assert len(executor.tasks) == 1
    assert live_map.latest_state.viewport is not None
    assert live_map.latest_state.viewport.center == latest_position

    executor.run_next()

    expected_keys = build_map_viewport(
        latest_position,
        zoom=13,
        width_px=600,
        height_px=400,
    ).tile_keys

    assert set(client.requests) == set(expected_keys)
    assert live_map.latest_state.status is MapDataStatus.READY
    assert live_map.latest_state.viewport is not None
    assert live_map.latest_state.viewport.center == latest_position


def test_repeated_queued_viewport_does_not_submit_duplicate_work() -> None:
    first_position = GeoPoint(39.53, -84.08)
    queued_position = GeoPoint(39.96, -82.99)
    moved_inside_same_tiles = GeoPoint(39.96001, -82.99001)
    executor = ManualExecutor()
    live_map = LiveMapService(
        MapTileResolver(
            InstalledMapRegistry(),
            FakeCache(),
            FakeClient(),
        ),
        zoom=13,
        clock=lambda: NOW,
        executor=executor,
    )
    live_map.start()

    live_map.request_viewport(
        first_position,
        width_px=600,
        height_px=400,
    )
    live_map.request_viewport(
        queued_position,
        width_px=600,
        height_px=400,
    )
    live_map.request_viewport(
        moved_inside_same_tiles,
        width_px=600,
        height_px=400,
    )

    assert len(executor.tasks) == 1
    assert live_map.latest_state.viewport is not None
    assert live_map.latest_state.viewport.center == moved_inside_same_tiles

    executor.run_next()

    assert len(executor.tasks) == 1

    executor.run_next()

    assert executor.tasks == []
    assert live_map.latest_state.status is MapDataStatus.READY
    assert live_map.latest_state.viewport is not None
    assert live_map.latest_state.viewport.center == moved_inside_same_tiles
