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
    live_map_status_color,
    live_map_status_lines,
    rotate_marker_points,
)

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
    from rolling_thunder.live_map_service import (
        MapTileSnapshot,
        MapTileSource,
    )
    from rolling_thunder.live_map_ui import plan_tile_updates
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
