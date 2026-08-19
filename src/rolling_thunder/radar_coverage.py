"""Pure geometry for decoupling visible map and buffered radar coverage."""

from __future__ import annotations

import math
from dataclasses import dataclass

from rolling_thunder.map_tiles import (
    TILE_SIZE_PX,
    MapViewport,
    build_map_viewport,
    web_mercator_world_pixel,
)

DEFAULT_RADAR_COVERAGE_MARGIN_TILES = 6
DEFAULT_RADAR_RECENTER_THRESHOLD_TILES = DEFAULT_RADAR_COVERAGE_MARGIN_TILES // 2


@dataclass(frozen=True)
class RadarCoverageMargins:
    """Whole tile reserves between one visible viewport and radar coverage."""

    left: int
    right: int
    top: int
    bottom: int

    @property
    def minimum(self) -> int:
        """Return the smallest remaining reserve on any side."""
        return min(self.left, self.right, self.top, self.bottom)

    @property
    def fully_covered(self) -> bool:
        """Return whether the complete visible tile rectangle lies in coverage."""
        return self.minimum >= 0


def build_radar_coverage_viewport(
    visible: MapViewport,
    *,
    margin_tiles: int = DEFAULT_RADAR_COVERAGE_MARGIN_TILES,
) -> MapViewport:
    """Build a radar viewport with a fixed tile reserve around the visible map."""
    if margin_tiles < 1:
        raise ValueError("Radar coverage margin must be at least one tile.")
    extra_px = margin_tiles * TILE_SIZE_PX * 2
    return build_map_viewport(
        visible.center,
        zoom=visible.zoom,
        width_px=visible.width_px + extra_px,
        height_px=visible.height_px + extra_px,
    )


def radar_coverage_margins(
    visible: MapViewport,
    coverage: MapViewport,
) -> RadarCoverageMargins | None:
    """Return deterministic tile reserves, or ``None`` for different zooms."""
    if visible.zoom != coverage.zoom:
        return None

    visible_left, visible_right, visible_top, visible_bottom = _display_tile_bounds(visible)
    coverage_left, coverage_right, coverage_top, coverage_bottom = _display_tile_bounds(
        coverage
    )

    visible_left, visible_right = _align_horizontal_bounds(
        visible_left,
        visible_right,
        coverage_left,
        coverage_right,
        world_tiles=1 << visible.zoom,
    )

    return RadarCoverageMargins(
        left=visible_left - coverage_left,
        right=coverage_right - visible_right,
        top=visible_top - coverage_top,
        bottom=coverage_bottom - visible_bottom,
    )


def radar_viewport_is_covered(
    visible: MapViewport,
    coverage: MapViewport,
) -> bool:
    """Return whether radar coverage truthfully contains the visible tile rectangle."""
    margins = radar_coverage_margins(visible, coverage)
    return margins is not None and margins.fully_covered


def radar_viewport_needs_recenter(
    visible: MapViewport,
    coverage: MapViewport,
    *,
    threshold_tiles: int = DEFAULT_RADAR_RECENTER_THRESHOLD_TILES,
) -> bool:
    """Return whether the visible map has consumed the safe radar reserve."""
    if threshold_tiles < 0:
        raise ValueError("Radar recenter threshold must not be negative.")
    margins = radar_coverage_margins(visible, coverage)
    if margins is None or not margins.fully_covered:
        return True
    return margins.minimum <= threshold_tiles


def radar_viewport_is_usefully_centered(
    visible: MapViewport,
    coverage: MapViewport,
    *,
    threshold_tiles: int = DEFAULT_RADAR_RECENTER_THRESHOLD_TILES,
) -> bool:
    """Return whether coverage contains the map with reserve beyond refresh threshold."""
    if threshold_tiles < 0:
        raise ValueError("Radar recenter threshold must not be negative.")
    margins = radar_coverage_margins(visible, coverage)
    return (
        margins is not None
        and margins.fully_covered
        and margins.minimum > threshold_tiles
    )


def _display_tile_bounds(viewport: MapViewport) -> tuple[int, int, int, int]:
    center_x, center_y = web_mercator_world_pixel(viewport.center, viewport.zoom)
    left_px = center_x - viewport.width_px / 2.0
    top_px = center_y - viewport.height_px / 2.0
    first_x = math.floor(left_px / TILE_SIZE_PX)
    last_x = math.floor((left_px + viewport.width_px - 1) / TILE_SIZE_PX)
    first_y = math.floor(top_px / TILE_SIZE_PX)
    last_y = math.floor((top_px + viewport.height_px - 1) / TILE_SIZE_PX)
    tile_limit = 1 << viewport.zoom
    return (
        first_x,
        last_x,
        max(0, first_y),
        min(tile_limit - 1, last_y),
    )


def _align_horizontal_bounds(
    first: int,
    last: int,
    reference_first: int,
    reference_last: int,
    *,
    world_tiles: int,
) -> tuple[int, int]:
    """Align wrapped display bounds to the copy of the world nearest coverage."""
    if world_tiles < 1:
        return first, last
    center = (first + last) / 2.0
    reference_center = (reference_first + reference_last) / 2.0
    world_shift = round((reference_center - center) / world_tiles)
    offset = world_shift * world_tiles
    return first + offset, last + offset
