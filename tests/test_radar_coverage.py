"""Tests for pure visible-map versus radar-buffer coverage geometry."""

from rolling_thunder.live_map import GeoPoint
from rolling_thunder.map_tiles import build_map_viewport
from rolling_thunder.radar_coverage import (
    DEFAULT_RADAR_COVERAGE_MARGIN_TILES,
    DEFAULT_RADAR_RECENTER_THRESHOLD_TILES,
    build_radar_coverage_viewport,
    radar_coverage_margins,
    radar_viewport_is_covered,
    radar_viewport_is_usefully_centered,
    radar_viewport_needs_recenter,
)


def visible_viewport(*, longitude: float = -84.06, zoom: int = 7):
    return build_map_viewport(
        GeoPoint(latitude=39.52, longitude=longitude),
        zoom=zoom,
        width_px=512,
        height_px=512,
    )


def shifted_longitude(longitude: float, *, zoom: int, tiles: int) -> float:
    return longitude + tiles * 360.0 / (1 << zoom)


def test_default_coverage_adds_six_whole_tile_reserves_on_every_side() -> None:
    visible = visible_viewport()
    coverage = build_radar_coverage_viewport(visible)

    margins = radar_coverage_margins(visible, coverage)

    assert DEFAULT_RADAR_COVERAGE_MARGIN_TILES == 6
    assert DEFAULT_RADAR_RECENTER_THRESHOLD_TILES == 3
    assert margins is not None
    assert margins.left == 6
    assert margins.right == 6
    assert margins.top == 6
    assert margins.bottom == 6
    assert radar_viewport_is_covered(visible, coverage) is True
    assert radar_viewport_is_usefully_centered(visible, coverage) is True


def test_one_and_two_tile_movement_remain_inside_safe_region() -> None:
    initial = visible_viewport()
    coverage = build_radar_coverage_viewport(initial)

    for tiles in (1, 2):
        moved = visible_viewport(
            longitude=shifted_longitude(-84.06, zoom=initial.zoom, tiles=tiles)
        )
        margins = radar_coverage_margins(moved, coverage)
        assert margins is not None
        assert margins.fully_covered is True
        assert radar_viewport_needs_recenter(moved, coverage) is False


def test_three_tile_movement_crosses_refresh_threshold_but_remains_covered() -> None:
    initial = visible_viewport()
    coverage = build_radar_coverage_viewport(initial)
    moved = visible_viewport(
        longitude=shifted_longitude(-84.06, zoom=initial.zoom, tiles=3)
    )

    margins = radar_coverage_margins(moved, coverage)

    assert margins is not None
    assert margins.minimum == 3
    assert margins.fully_covered is True
    assert radar_viewport_needs_recenter(moved, coverage) is True
    assert radar_viewport_is_usefully_centered(moved, coverage) is False


def test_zoom_change_is_never_treated_as_covered_radar() -> None:
    visible = visible_viewport(zoom=7)
    coverage = build_radar_coverage_viewport(visible)
    zoomed = visible_viewport(zoom=8)

    assert radar_coverage_margins(zoomed, coverage) is None
    assert radar_viewport_is_covered(zoomed, coverage) is False
    assert radar_viewport_needs_recenter(zoomed, coverage) is True
    assert radar_viewport_is_usefully_centered(zoomed, coverage) is False


def test_coverage_geometry_handles_longitude_wrap_near_dateline() -> None:
    visible = visible_viewport(longitude=179.9, zoom=7)
    coverage = build_radar_coverage_viewport(visible)
    moved = visible_viewport(
        longitude=-179.9,
        zoom=7,
    )

    margins = radar_coverage_margins(moved, coverage)

    assert margins is not None
    assert margins.fully_covered is True
