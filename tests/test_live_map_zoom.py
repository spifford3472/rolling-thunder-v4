"""Tests for changing live-map zoom without UI-thread tile I/O."""

from concurrent.futures import Executor, Future
from datetime import UTC, datetime
from typing import Any

from rolling_thunder.live_map import GeoPoint
from rolling_thunder.live_map_service import LiveMapService
from rolling_thunder.map_sources import MapTileSource, ResolvedMapTile
from rolling_thunder.map_tiles import MapTileKey

NOW = datetime(2026, 8, 8, 19, 0, tzinfo=UTC)


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


class LocalResolver:
    installed_packages: tuple[()] = ()
    diagnostics: tuple[str, ...] = ()

    def __init__(self) -> None:
        self.reads: list[MapTileKey] = []

    def start_background_refresh(self) -> None:
        pass

    def observe_installed_tile(self, *args: object, **kwargs: object) -> None:
        pass

    def observe_gps_position(self, *args: object, **kwargs: object) -> None:
        pass

    def read_local(self, key: MapTileKey) -> ResolvedMapTile:
        self.reads.append(key)
        return ResolvedMapTile(
            png=b"tile",
            source=MapTileSource.CACHE,
            online_refresh_allowed=False,
        )

    def refresh_online(
        self,
        key: MapTileKey,
        fallback: ResolvedMapTile,
    ) -> ResolvedMapTile:
        return fallback

    def close(self) -> None:
        pass


def test_zoom_changes_in_memory_then_next_viewport_uses_new_zoom() -> None:
    resolver = LocalResolver()
    live_map = LiveMapService(
        resolver,  # type: ignore[arg-type]
        zoom=15,
        clock=lambda: NOW,
        executor=ImmediateExecutor(),
    )
    live_map.start()
    position = GeoPoint(39.53, -84.08)

    live_map.request_viewport(position, width_px=600, height_px=400)
    first = live_map.latest_state.viewport
    assert first is not None
    assert first.zoom == 15

    reads_before_change = len(resolver.reads)
    assert live_map.set_zoom(14) is True
    assert live_map.zoom == 14
    assert len(resolver.reads) == reads_before_change

    live_map.request_viewport(position, width_px=600, height_px=400)
    second = live_map.latest_state.viewport
    assert second is not None
    assert second.zoom == 14
    assert len(resolver.reads) > reads_before_change


def test_setting_same_zoom_is_noop() -> None:
    live_map = LiveMapService(
        LocalResolver(),  # type: ignore[arg-type]
        zoom=15,
        clock=lambda: NOW,
        executor=ImmediateExecutor(),
    )

    assert live_map.set_zoom(15) is False
    assert live_map.zoom == 15
