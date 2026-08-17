"""Tests for minimal Tk radar canvas work between immutable snapshots."""

from datetime import UTC, datetime

from rolling_thunder.live_map_ui import plan_radar_tile_updates
from rolling_thunder.live_radar_service import (
    LiveRadarSnapshot,
    RadarDataStatus,
    RadarTileSnapshot,
)
from rolling_thunder.map_tiles import MapTileKey, MapTilePlacement
from rolling_thunder.radar_domain import (
    RadarFrame,
    RadarProductToken,
    RadarSourceMetadata,
)

NOW = datetime(2026, 8, 9, 1, 30, tzinfo=UTC)
SOURCE = RadarSourceMetadata(
    provider_id="test",
    provider_name="Test",
    product=RadarProductToken.BASE_REFLECTIVITY,
    attribution_text="Radar: Test",
    attribution_url="https://example.invalid/radar",
)


def frame(token: str) -> RadarFrame:
    return RadarFrame(
        frame_token=token,
        observed_at=NOW,
        fetched_at=NOW,
        source=SOURCE,
    )


def snapshot(
    token: str,
    tiles: tuple[RadarTileSnapshot, ...],
) -> LiveRadarSnapshot:
    return LiveRadarSnapshot(
        status=RadarDataStatus.READY,
        viewport=None,
        frame=frame(token),
        tiles=tiles,
        detail="RADAR READY",
        updated_at=NOW,
    )


def tile(
    key: MapTileKey,
    *,
    x_px: int,
    png: bytes,
) -> RadarTileSnapshot:
    return RadarTileSnapshot(
        placement=MapTilePlacement(
            key=key,
            x_px=x_px,
            y_px=20,
        ),
        png=png,
    )


def test_same_frame_motion_moves_retained_radar_item_without_redraw() -> None:
    key = MapTileKey(zoom=13, x=100, y=200)
    previous = snapshot("a" * 32, (tile(key, x_px=256, png=b"same"),))
    current = snapshot("a" * 32, (tile(key, x_px=240, png=b"same"),))

    plan = plan_radar_tile_updates(previous, current)

    assert plan.remove == ()
    assert plan.redraw == ()
    assert plan.move == (key,)


def test_new_weather_frame_redraws_visible_radar_even_for_same_tile_keys() -> None:
    key = MapTileKey(zoom=13, x=100, y=200)
    previous = snapshot("a" * 32, (tile(key, x_px=256, png=b"same"),))
    current = snapshot("b" * 32, (tile(key, x_px=256, png=b"same"),))

    plan = plan_radar_tile_updates(previous, current)

    assert plan.remove == (key,)
    assert plan.redraw == (key,)
    assert plan.move == ()
