"""Tests for pure Settings presentation helpers."""

from rolling_thunder.map_sources import MapPackageStyle
from rolling_thunder.map_zoom import MapZoomBounds, MapZoomSettingsState
from rolling_thunder.settings_panel import DashboardSettingsState
from rolling_thunder.settings_ui import (
    _HEALTHY,
    _SETTINGS_CARD_FONT_SIZE,
    _SETTINGS_SECONDARY_FONT_SIZE,
    _SETTINGS_VALUE_FONT_SIZE,
    _map_style_presentation,
    _map_zoom_presentation,
)


def settings_state(
    map_zoom: MapZoomSettingsState | None,
) -> DashboardSettingsState:
    return DashboardSettingsState(
        map_zoom=map_zoom,
        radar_available=True,
        radar_image_enabled=True,
    )


def test_zoom_presentation_places_current_value_apart_from_instruction() -> None:
    state = settings_state(
        MapZoomSettingsState(
            zoom=13,
            bounds=MapZoomBounds(6, 15),
            style=MapPackageStyle.DAY,
            available_styles=(MapPackageStyle.DAY, MapPackageStyle.NIGHT),
        )
    )

    title, instruction, value = _map_zoom_presentation(state)

    assert title == "MAP ZOOM"
    assert instruction == "Turn encoder: OUT / IN    Range 6-15"
    assert value == "13"


def test_style_presentation_exposes_current_selection_and_button_instruction() -> None:
    state = settings_state(
        MapZoomSettingsState(
            zoom=13,
            bounds=MapZoomBounds(6, 15),
            style=MapPackageStyle.NIGHT,
            available_styles=(MapPackageStyle.DAY, MapPackageStyle.NIGHT),
        )
    )

    title, instruction, value, emphasized = _map_style_presentation(state)

    assert title == "MAP STYLE"
    assert instruction == "Context Button #2: DAY / NIGHT"
    assert value == "NIGHT"
    assert emphasized is True


def test_current_style_remains_emphasized_when_switching_is_unavailable() -> None:
    state = settings_state(
        MapZoomSettingsState(
            zoom=13,
            bounds=MapZoomBounds(6, 15),
            style=MapPackageStyle.DAY,
            available_styles=(MapPackageStyle.DAY,),
        )
    )

    _, instruction, value, emphasized = _map_style_presentation(state)

    assert instruction == "Style switch unavailable"
    assert value == "DAY"
    assert emphasized is True


def test_disabled_map_controls_have_truthful_values() -> None:
    state = settings_state(None)

    assert _map_zoom_presentation(state) == (
        "MAP ZOOM",
        "Turn encoder: OUT / IN",
        "DISABLED",
    )
    assert _map_style_presentation(state) == (
        "MAP STYLE",
        "Context Button #2",
        "UNAVAILABLE",
        False,
    )


def test_settings_cards_share_compact_typography() -> None:
    assert _SETTINGS_CARD_FONT_SIZE == 30
    assert _SETTINGS_SECONDARY_FONT_SIZE == 18
    assert _SETTINGS_VALUE_FONT_SIZE == 36
    assert _SETTINGS_SECONDARY_FONT_SIZE < _SETTINGS_CARD_FONT_SIZE
    assert _SETTINGS_CARD_FONT_SIZE < _SETTINGS_VALUE_FONT_SIZE
    assert _HEALTHY == "#66ccff"
