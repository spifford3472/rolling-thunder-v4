"""Tests for pure live-map UI presentation helpers."""

from datetime import UTC, datetime

import pytest

from rolling_thunder.live_map import (
    GeoPoint,
    LiveMapGpsStatus,
    LiveMapPresentation,
)
from rolling_thunder.live_map_service import (
    LiveMapSnapshot,
    MapDataStatus,
)
from rolling_thunder.live_map_ui import (
    LiveMapWidgets,
    live_map_status_color,
    live_map_status_lines,
    plan_pota_marker_updates,
    radar_matches_map,
    radar_status_color,
    rotate_marker_points,
)
from rolling_thunder.live_radar_service import LiveRadarSnapshot, RadarDataStatus
from rolling_thunder.map_tiles import build_map_viewport
from rolling_thunder.pota_map_markers import PotaMapMarker, PotaMapMarkerSnapshot

NOW = datetime(2026, 8, 2, 20, 0, tzinfo=UTC)


def presentation(
    status: LiveMapGpsStatus = LiveMapGpsStatus.READY,
) -> LiveMapPresentation:
    return LiveMapPresentation(
        status=status,
        position=GeoPoint(39.53, -84.08),
        grid="EM79xm",
        detail="GPS READY",
        fix_time=NOW,
        is_current=(status is LiveMapGpsStatus.READY),
    )


def snapshot(status: MapDataStatus) -> LiveMapSnapshot:
    return LiveMapSnapshot(
        status=status,
        viewport=None,
        tiles=(),
        detail={
            MapDataStatus.READY: "MAP READY",
            MapDataStatus.CACHE_ONLY: "MAP DATA OFFLINE — USING CACHE",
            MapDataStatus.PARTIAL: "MAP DATA PARTIAL",
            MapDataStatus.UNAVAILABLE: "MAP DATA UNAVAILABLE",
        }.get(status, "LOADING MAP DATA"),
        updated_at=NOW,
    )


def test_status_lines_include_gps_map_grid_and_coordinates() -> None:
    assert live_map_status_lines(
        presentation(),
        snapshot(MapDataStatus.READY),
    ) == (
        "GPS READY",
        "MAP READY",
        "GRID EM79XM",
        "39.53000, -84.08000",
    )


def test_status_lines_show_disabled_without_snapshot() -> None:
    assert live_map_status_lines(presentation(), None)[1] == "MAP DISABLED"


def test_ready_status_uses_success_color() -> None:
    assert (
        live_map_status_color(
            LiveMapGpsStatus.READY,
            MapDataStatus.READY,
        )
        == "#42ff72"
    )


def test_stale_or_cache_only_status_uses_warning_color() -> None:
    assert (
        live_map_status_color(
            LiveMapGpsStatus.STALE,
            MapDataStatus.READY,
        )
        == "#ffd24a"
    )
    assert (
        live_map_status_color(
            LiveMapGpsStatus.READY,
            MapDataStatus.CACHE_ONLY,
        )
        == "#ffd24a"
    )


def test_unavailable_status_uses_failure_color() -> None:
    assert (
        live_map_status_color(
            LiveMapGpsStatus.READY,
            MapDataStatus.UNAVAILABLE,
        )
        == "#ff7070"
    )


@pytest.mark.parametrize(
    ("heading", "expected"),
    [
        (0.0, (100.0, 90.0)),
        (90.0, (110.0, 100.0)),
        (180.0, (100.0, 110.0)),
        (270.0, (90.0, 100.0)),
    ],
)
def test_marker_rotation_follows_compass_heading(
    heading: float,
    expected: tuple[float, float],
) -> None:
    rotated = rotate_marker_points(
        ((0.0, -10.0),),
        center_x=100.0,
        center_y=100.0,
        heading_degrees=heading,
    )

    assert rotated == pytest.approx(expected)


def test_tile_update_plan_separates_remove_redraw_and_move() -> None:
    from rolling_thunder.live_map_service import MapTileSnapshot
    from rolling_thunder.live_map_ui import plan_tile_updates
    from rolling_thunder.map_sources import MapTileSource
    from rolling_thunder.map_tiles import (
        MapTileKey,
        MapTilePlacement,
    )

    removed_key = MapTileKey(zoom=13, x=100, y=200)
    moved_key = MapTileKey(zoom=13, x=101, y=200)
    changed_key = MapTileKey(zoom=13, x=102, y=200)
    new_key = MapTileKey(zoom=13, x=103, y=200)

    def tile(
        key: MapTileKey,
        *,
        x_px: int,
        png: bytes | None,
    ) -> MapTileSnapshot:
        return MapTileSnapshot(
            placement=MapTilePlacement(
                key=key,
                x_px=x_px,
                y_px=20,
            ),
            png=png,
            source=MapTileSource.CACHE,
        )

    previous = LiveMapSnapshot(
        status=MapDataStatus.READY,
        viewport=None,
        tiles=(
            tile(removed_key, x_px=0, png=b"removed"),
            tile(moved_key, x_px=256, png=b"same"),
            tile(changed_key, x_px=512, png=b"old"),
        ),
        detail="MAP READY",
        updated_at=NOW,
    )
    current = LiveMapSnapshot(
        status=MapDataStatus.LOADING,
        viewport=None,
        tiles=(
            tile(moved_key, x_px=240, png=b"same"),
            tile(changed_key, x_px=496, png=b"new"),
            tile(new_key, x_px=752, png=None),
        ),
        detail="LOADING MAP DATA",
        updated_at=NOW,
    )

    plan = plan_tile_updates(previous, current)

    assert plan.remove == (removed_key,)
    assert plan.redraw == (changed_key, new_key)
    assert plan.move == (moved_key,)


def test_radar_is_eligible_only_for_exact_published_map_viewport() -> None:
    map_viewport = build_map_viewport(
        GeoPoint(latitude=39.52, longitude=-84.06),
        zoom=7,
        width_px=512,
        height_px=512,
    )
    other_viewport = build_map_viewport(
        GeoPoint(latitude=39.52, longitude=-84.06),
        zoom=8,
        width_px=512,
        height_px=512,
    )
    map_snapshot = LiveMapSnapshot(
        status=MapDataStatus.READY,
        viewport=map_viewport,
        tiles=(),
        detail="MAP READY",
        updated_at=NOW,
    )
    matching = LiveRadarSnapshot(
        status=RadarDataStatus.READY,
        viewport=map_viewport,
        frame=None,
        tiles=(),
        detail="RADAR READY",
        updated_at=NOW,
    )
    mismatched = LiveRadarSnapshot(
        status=RadarDataStatus.READY,
        viewport=other_viewport,
        frame=None,
        tiles=(),
        detail="RADAR READY",
        updated_at=NOW,
    )

    assert radar_matches_map(matching, map_snapshot) is True
    assert radar_matches_map(mismatched, map_snapshot) is False
    assert radar_matches_map(None, map_snapshot) is False


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (None, "#a8b4ba"),
        (RadarDataStatus.DISABLED, "#a8b4ba"),
        (RadarDataStatus.IDLE, "#ffd24a"),
        (RadarDataStatus.LOADING, "#ffd24a"),
        (RadarDataStatus.STALE, "#ffd24a"),
        (RadarDataStatus.PARTIAL, "#ffd24a"),
        (RadarDataStatus.READY, "#66ccff"),
        (RadarDataStatus.UNAVAILABLE, "#ff7070"),
    ],
)
def test_radar_health_uses_color_only_state(
    status: RadarDataStatus | None,
    expected: str,
) -> None:
    assert radar_status_color(status) == expected


def test_empty_pota_viewport_does_not_raise_missing_canvas_tag() -> None:
    class EmptyPotaCanvas:
        def delete(self, _tag: str) -> None:
            return None

        def find_withtag(self, _tag: str) -> tuple[int, ...]:
            return ()

        def tag_raise(self, tag: str | int, above: str) -> None:
            if tag == "map-pota":
                raise AssertionError("empty POTA tag must not be raised")
            if above == "map-pota":
                raise AssertionError("nothing may be raised relative to empty POTA tag")

    viewport = build_map_viewport(
        GeoPoint(latitude=39.52, longitude=-84.06),
        zoom=17,
        width_px=512,
        height_px=512,
    )
    map_snapshot = LiveMapSnapshot(
        status=MapDataStatus.READY,
        viewport=viewport,
        tiles=(),
        detail="MAP READY",
        updated_at=NOW,
    )
    pota_snapshot = PotaMapMarkerSnapshot(
        viewport=viewport,
        markers=(),
        detail="POTA MARKERS READY",
        updated_at=NOW,
    )
    widgets = LiveMapWidgets.__new__(LiveMapWidgets)
    widgets._canvas = EmptyPotaCanvas()
    widgets._attribution_item = None
    widgets._pota_label_min_zoom = 14
    widgets._pota_dot_diameter_px = 12

    widgets._draw_pota_markers(pota_snapshot, map_snapshot)


def test_layer_ordering_handles_disabled_radar_without_missing_tag_error() -> None:
    calls: list[tuple[str | int, str]] = []

    class NoRadarCanvas:
        def find_withtag(self, tag: str) -> tuple[int, ...]:
            if tag == "map-pota":
                return (101,)
            if tag == "map-radar":
                return ()
            return ()

        def tag_raise(self, tag: str | int, above: str) -> None:
            if above == "map-radar":
                raise AssertionError("disabled radar tag must not be used as a reference")
            calls.append((tag, above))

    widgets = LiveMapWidgets.__new__(LiveMapWidgets)
    widgets._canvas = NoRadarCanvas()
    widgets._attribution_item = 999

    widgets._raise_radar_layer()

    assert calls == [(999, "map-pota")]



def test_pota_marker_update_plan_retains_stable_parks_across_viewport_refresh() -> None:
    viewport_a = build_map_viewport(
        GeoPoint(latitude=39.52, longitude=-84.06),
        zoom=10,
        width_px=512,
        height_px=512,
    )
    viewport_b = build_map_viewport(
        GeoPoint(latitude=39.53, longitude=-84.05),
        zoom=10,
        width_px=512,
        height_px=512,
    )
    retained = PotaMapMarker(
        reference="US-1234",
        name="Retained Park",
        latitude=39.60,
        longitude=-84.10,
    )
    removed = PotaMapMarker(
        reference="US-2222",
        name="Removed Park",
        latitude=39.10,
        longitude=-84.40,
    )
    added = PotaMapMarker(
        reference="US-3333",
        name="Added Park",
        latitude=39.80,
        longitude=-83.90,
    )
    previous = PotaMapMarkerSnapshot(
        viewport=viewport_a,
        markers=(retained, removed),
        detail="POTA MARKERS READY",
        updated_at=NOW,
    )
    current = PotaMapMarkerSnapshot(
        viewport=viewport_b,
        markers=(retained, added),
        detail="POTA MARKERS READY",
        updated_at=NOW,
    )

    plan = plan_pota_marker_updates(previous, current)

    assert plan.retain == (("US-1234", 39.6, -84.1),)
    assert plan.remove == (("US-2222", 39.1, -84.4),)
    assert plan.add == (("US-3333", 39.8, -83.9),)


def test_pota_marker_update_plan_does_not_treat_viewport_motion_as_marker_replacement() -> None:
    marker = PotaMapMarker(
        reference="US-1234",
        name="Stable Park",
        latitude=39.60,
        longitude=-84.10,
    )
    previous = PotaMapMarkerSnapshot(
        viewport=build_map_viewport(
            GeoPoint(latitude=39.52, longitude=-84.06),
            zoom=10,
            width_px=512,
            height_px=512,
        ),
        markers=(marker,),
        detail="POTA MARKERS READY",
        updated_at=NOW,
    )
    current = PotaMapMarkerSnapshot(
        viewport=build_map_viewport(
            GeoPoint(latitude=39.54, longitude=-84.04),
            zoom=10,
            width_px=512,
            height_px=512,
        ),
        markers=(marker,),
        detail="POTA MARKERS READY",
        updated_at=NOW,
    )

    plan = plan_pota_marker_updates(previous, current)

    assert plan.remove == ()
    assert plan.add == ()
    assert plan.retain == (("US-1234", 39.6, -84.1),)



def test_pota_markers_stay_visible_while_async_viewport_query_catches_up() -> None:
    class RecordingCanvas:
        def __init__(self) -> None:
            self.deleted: list[int | str] = []
            self.coords_calls: list[tuple[int, tuple[float, ...]]] = []

        def delete(self, item: int | str) -> None:
            self.deleted.append(item)

        def coords(self, item: int, *coords: float) -> None:
            self.coords_calls.append((item, coords))

        def find_withtag(self, tag: str) -> tuple[int, ...]:
            if tag == "map-pota":
                return (101,)
            return ()

        def tag_raise(self, _tag: int | str, _above: str) -> None:
            return None

    old_viewport = build_map_viewport(
        GeoPoint(latitude=39.5200, longitude=-84.0600),
        zoom=10,
        width_px=512,
        height_px=512,
    )
    current_viewport = build_map_viewport(
        GeoPoint(latitude=39.5205, longitude=-84.0595),
        zoom=10,
        width_px=512,
        height_px=512,
    )
    marker = PotaMapMarker(
        reference="US-1234",
        name="Stable Park",
        latitude=39.60,
        longitude=-84.10,
    )
    pota_snapshot = PotaMapMarkerSnapshot(
        viewport=old_viewport,
        markers=(marker,),
        detail="POTA MARKERS READY",
        updated_at=NOW,
    )
    map_snapshot = LiveMapSnapshot(
        status=MapDataStatus.READY,
        viewport=current_viewport,
        tiles=(),
        detail="MAP READY",
        updated_at=NOW,
    )

    canvas = RecordingCanvas()
    widgets = LiveMapWidgets.__new__(LiveMapWidgets)
    widgets._canvas = canvas
    widgets._attribution_item = None
    widgets._pota_label_min_zoom = 14
    widgets._pota_dot_diameter_px = 12
    widgets._pota_items = {
        ("US-1234", 39.6, -84.1): ("dot", (101,))
    }

    widgets._draw_pota_markers(pota_snapshot, map_snapshot)

    assert canvas.deleted == []
    assert canvas.coords_calls
    assert canvas.coords_calls[0][0] == 101


def test_radar_tile_conversion_is_limited_per_refresh() -> None:
    """A frame burst never constructs all radar images in one UI refresh."""
    widgets = LiveMapWidgets.__new__(LiveMapWidgets)
    tiles = [object() for _ in range(7)]
    widgets._pending_radar_tiles = [("frame-a", tile) for tile in tiles]
    rendered: list[tuple[str, object]] = []
    widgets._upsert_radar_tile = lambda token, tile: rendered.append((token, tile))
    widgets._raise_radar_layer = lambda: None
    widgets._trim_radar_photo_cache = lambda token: None

    widgets._flush_pending_radar_tiles()
    assert rendered == [("frame-a", tiles[0]), ("frame-a", tiles[1])]
    assert len(widgets._pending_radar_tiles) == 5

    for _ in range(3):
        widgets._flush_pending_radar_tiles()
    assert rendered == [("frame-a", tile) for tile in tiles]
    assert widgets._pending_radar_tiles == []


def test_radar_clear_discards_pending_tiles() -> None:
    """A changed or disabled viewport must not display queued stale tiles."""
    class Canvas:
        def delete(self, _tag: str) -> None:
            return None

    widgets = LiveMapWidgets.__new__(LiveMapWidgets)
    widgets._canvas = Canvas()
    widgets._pending_radar_tiles = [("old-frame", object())]
    widgets._radar_items = {object(): 1}
    widgets._radar_active_photos = {object(): object()}

    widgets._clear_radar()

    assert widgets._pending_radar_tiles == []
    assert widgets._radar_items == {}
    assert widgets._radar_active_photos == {}


def test_base_tile_rendering_is_bounded_and_clears_on_viewport_rebuild() -> None:
    widgets = LiveMapWidgets.__new__(LiveMapWidgets)
    tiles = [object() for _ in range(7)]
    widgets._pending_base_tiles = list(tiles)
    rendered: list[object] = []
    widgets._upsert_tile = rendered.append

    widgets._flush_pending_base_tiles()
    assert rendered == tiles[:2]
    assert widgets._pending_base_tiles == tiles[2:]
    for _ in range(3):
        widgets._flush_pending_base_tiles()
    assert rendered == tiles
    assert widgets._pending_base_tiles == []

    widgets._pending_base_tiles = list(tiles)
    class Canvas:
        def delete(self, _tag: str) -> None:
            pass
        def create_rectangle(self, *_args, **_kwargs) -> int:
            return 1
        def create_text(self, *_args, **_kwargs) -> int:
            return 2
        def create_line(self, *_args, **_kwargs) -> int:
            return 3
    widgets._canvas = Canvas()
    widgets._tile_items = {}
    widgets._tile_item_kinds = {}
    widgets._active_photos = {}
    widgets._attribution_item = None
    widgets._draw_base(None, 100, 100)
    assert widgets._pending_base_tiles == []


def test_live_map_update_records_base_map_timing_when_enabled() -> None:
    """Capture base-map time even if no new snapshot arrives."""
    from unittest.mock import Mock

    widgets = LiveMapWidgets.__new__(LiveMapWidgets)
    widgets._canvas = Mock()
    widgets._canvas.winfo_width.return_value = 800
    widgets._canvas.winfo_height.return_value = 480
    widgets._last_size = (800, 480)
    widgets._last_snapshot = None
    widgets._last_radar_snapshot = None
    widgets._last_pota_snapshot = None
    widgets._pending_base_tiles = []
    widgets._pending_radar_tiles = []
    widgets._flush_pending_base_tiles = Mock()
    widgets._flush_pending_radar_tiles = Mock()
    widgets._draw_vehicle_marker = Mock()
    widgets._draw_status = Mock()
    from rolling_thunder.ui_timing import UiTiming

    now = [1.0]
    timing = UiTiming(enabled=True, clock=lambda: now[0])
    widgets.update(presentation(), None, timing=timing)
    assert len(timing._samples["base_map"]) == 1
    assert len(timing._samples["radar"]) == 1
    assert set(timing._subphase_durations) == {
        "base_plan",
        "overlay_status_canvas",
        "pota_canvas",
        "radar_plan",
    }
