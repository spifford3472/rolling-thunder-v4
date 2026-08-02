"""Tests for background live-map tile loading and degradation."""

from concurrent.futures import Future
from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import Any

from PIL import Image

from rolling_thunder.live_map import GeoPoint
from rolling_thunder.live_map_service import LiveMapService, MapDataStatus, MapTileSource
from rolling_thunder.map_tiles import CachedMapTile, MapTileError, MapTileKey

NOW = datetime(2026, 8, 2, 20, 0, tzinfo=UTC)


def png_tile(value: int = 20) -> bytes:
    image = Image.new("RGB", (256, 256), (value, value, value))
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


class ImmediateExecutor:
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
        client,  # type: ignore[arg-type]
        cache,  # type: ignore[arg-type]
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
