"""Tests for pure live-map information overlay helpers."""

from rolling_thunder.live_map_info import (
    LiveMapHealthLevel,
    LiveMapInfoPresentation,
    LiveMapSubsystemHealth,
)
from rolling_thunder.live_map_ui import live_map_health_color, live_map_info_lines


def health(
    level: LiveMapHealthLevel,
    detail: str,
) -> LiveMapSubsystemHealth:
    return LiveMapSubsystemHealth(
        level=level,
        detail=detail,
        last_usable_at=None,
        age=None,
    )


def test_info_lines_show_required_map_information() -> None:
    info = LiveMapInfoPresentation(
        local_time="3:11 PM",
        utc_time="19:11 UTC",
        grid="EM79XM",
        temperature_f="--°F",
        temperature_c="--°C",
        temperature_detail="UNAVAILABLE",
        map_health=health(LiveMapHealthLevel.HEALTHY, "READY"),
        gps_health=health(LiveMapHealthLevel.HEALTHY, "READY"),
    )

    assert live_map_info_lines(info) == (
        "LOCAL  3:11 PM",
        "UTC    19:11 UTC",
        "GRID   EM79XM",
        "TEMP   --°F / --°C — UNAVAILABLE",
    )


def test_health_colors_use_green_yellow_and_gray() -> None:
    assert live_map_health_color(LiveMapHealthLevel.HEALTHY) == "#42ff72"
    assert live_map_health_color(LiveMapHealthLevel.DEGRADED) == "#ffd24a"
    assert live_map_health_color(LiveMapHealthLevel.UNAVAILABLE) == "#a8b4ba"
