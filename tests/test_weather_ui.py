"""Tests for pure weather UI color semantics."""

import pytest

from rolling_thunder.weather_panel import WeatherPanelStatus
from rolling_thunder.weather_ui import weather_status_color


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (WeatherPanelStatus.LIVE, "#66ccff"),
        (WeatherPanelStatus.RETAINED, "#ffd24a"),
        (WeatherPanelStatus.STALE, "#ffd24a"),
        (WeatherPanelStatus.DISABLED, "#777777"),
        (WeatherPanelStatus.UNAVAILABLE, "#777777"),
        (WeatherPanelStatus.ERROR, "#ff7070"),
    ],
)
def test_weather_state_uses_approved_color_semantics(
    status: WeatherPanelStatus,
    expected: str,
) -> None:
    assert weather_status_color(status) == expected
