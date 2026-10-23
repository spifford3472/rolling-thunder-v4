"""Deterministic hardware-free reproduction for issue #345 UI blocking."""

from __future__ import annotations

from collections import OrderedDict
from threading import Event, Thread

from rolling_thunder.live_map_service import MapTileSnapshot
from rolling_thunder.live_map_ui import LiveMapWidgets
from rolling_thunder.map_sources import MapTileSource
from rolling_thunder.map_tiles import MapTileKey, MapTilePlacement
from rolling_thunder.ui_timing import UiTiming


class _BlockingTk:
    """Model a Tk image materialization call that has entered but not returned."""

    def __init__(self, entered: Event, release: Event) -> None:
        self._entered = entered
        self._release = release

    def PhotoImage(self, *, data: str) -> object:
        assert data
        self._entered.set()
        if not self._release.wait(timeout=2.0):
            raise AssertionError("test did not release the PhotoImage barrier")
        return object()


class _Canvas:
    def delete(self, _item: object) -> None:
        return None

    def create_image(self, *_args: object, **_kwargs: object) -> int:
        return 1


def test_pending_base_tile_keeps_caller_blocked_until_photoimage_returns() -> None:
    """The real pending-tile path executes PhotoImage inline on its caller."""
    entered = Event()
    release = Event()
    finished = Event()
    failure: list[BaseException] = []

    key = MapTileKey(zoom=13, x=100, y=200)
    tile = MapTileSnapshot(
        placement=MapTilePlacement(key=key, x_px=0, y_px=0),
        png=b"isolated-png-payload",
        source=MapTileSource.CACHE,
    )
    widgets = LiveMapWidgets.__new__(LiveMapWidgets)
    widgets._tk = _BlockingTk(entered, release)
    widgets._canvas = _Canvas()
    widgets._pending_base_tiles = [tile]
    widgets._tile_items = {}
    widgets._tile_item_kinds = {}
    widgets._active_photos = {}
    widgets._photo_cache = OrderedDict()
    widgets._attribution_item = None
    timing = UiTiming(enabled=True)
    timing.begin_refresh()

    def render_one_refresh_slice() -> None:
        try:
            widgets._flush_pending_base_tiles(timing=timing)
        except (AssertionError, RuntimeError, TypeError, ValueError) as error:
            failure.append(error)
        finally:
            finished.set()

    worker = Thread(target=render_one_refresh_slice, name="issue-345-ui-caller")
    worker.start()
    try:
        assert entered.wait(timeout=2.0), "pending tile never reached PhotoImage"
        assert not finished.is_set(), "caller returned while PhotoImage was blocked"
        release.set()
        assert finished.wait(timeout=2.0), "caller did not resume after barrier release"
    finally:
        release.set()
        worker.join(timeout=2.0)

    assert not worker.is_alive()
    assert failure == []
    assert widgets._pending_base_tiles == []
    assert key in widgets._tile_items
    assert timing._subphase_durations["base_b64"][0] == 1
    assert timing._subphase_durations["base_photo"][0] == 1
    assert timing._subphase_durations["base_canvas"][0] == 2
