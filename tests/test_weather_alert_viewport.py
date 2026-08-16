"""Tests for deterministic weather-alert text scrolling."""

from rolling_thunder.weather_alert_panel import (
    WeatherAlertItemPresentation,
    WeatherAlertPanelPresentation,
    WeatherAlertPanelStatus,
)
from rolling_thunder.weather_alert_viewport import WeatherAlertViewportController


def presentation(
    *,
    alert_id: str = "warning-1",
    area: str = "Warren County and nearby communities",
    headline: str = (
        "Severe Thunderstorm Warning issued for a long test area with "
        "additional driving-safe summary words that require scrolling"
    ),
) -> WeatherAlertPanelPresentation:
    return WeatherAlertPanelPresentation(
        status=WeatherAlertPanelStatus.ACTIVE,
        status_line="1 ACTIVE WEATHER ALERT • VERIFIED CURRENT",
        verified_current=True,
        active_count=1,
        items=(
            WeatherAlertItemPresentation(
                alert_id=alert_id,
                event="Severe Thunderstorm Warning",
                severity="SEVERE",
                expires="8:30 PM",
                area=area,
                headline=headline,
            ),
        ),
        attribution="National Weather Service alerts",
    )


def test_long_alert_scrolls_by_one_line_and_preserves_offset_on_refresh() -> None:
    controller = WeatherAlertViewportController(wrap_width=24, visible_lines=3)
    alert = presentation()

    initial = controller.synchronize(alert)

    assert initial.overflowing is True
    assert initial.offset == 0
    assert initial.can_scroll_up is False
    assert initial.can_scroll_down is True

    assert controller.scroll_next() is True
    moved = controller.state
    assert moved.offset == 1
    assert moved.can_scroll_up is True
    assert moved.text != initial.text

    refreshed = controller.synchronize(alert)
    assert refreshed.offset == 1
    assert refreshed.text == moved.text

    assert controller.scroll_previous() is True
    assert controller.state.offset == 0
    assert controller.scroll_previous() is False


def test_scroll_is_bounded_and_resets_for_new_or_missing_alert() -> None:
    controller = WeatherAlertViewportController(wrap_width=18, visible_lines=2)
    controller.synchronize(presentation())

    moves = 0
    while controller.scroll_next():
        moves += 1

    assert moves > 0
    assert controller.state.can_scroll_down is False
    assert controller.scroll_next() is False

    changed = controller.synchronize(
        presentation(alert_id="warning-2", headline="A different alert headline")
    )
    assert changed.offset == 0

    empty = controller.synchronize(
        WeatherAlertPanelPresentation(
            status=WeatherAlertPanelStatus.NO_ACTIVE,
            status_line="NO ACTIVE WEATHER ALERTS",
            verified_current=True,
            active_count=0,
            items=(),
            attribution="National Weather Service alerts",
        )
    )
    assert empty.text == ""
    assert empty.offset == 0
    assert empty.overflowing is False
