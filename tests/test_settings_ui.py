"""Tests for pure Settings presentation helpers."""

from rolling_thunder.map_sources import MapPackageStyle
from rolling_thunder.map_zoom import MapZoomBounds, MapZoomSettingsState
from rolling_thunder.settings_panel import DashboardSettingsState
from rolling_thunder.settings_ui import (
    _DISABLED,
    _HEALTHY,
    _SETTINGS_CARD_FONT_SIZE,
    _SETTINGS_INSTRUCTION_FONT_SIZE,
    _SETTINGS_PRIMARY_FONT_SIZE,
    _SETTINGS_SECONDARY_FONT_SIZE,
    _SETTINGS_ZOOM_FONT_SIZE,
    _zoom_presentation,
)


def settings_state(
    map_zoom: MapZoomSettingsState | None,
) -> DashboardSettingsState:
    return DashboardSettingsState(
        map_zoom=map_zoom,
        radar_available=True,
        radar_image_enabled=True,
    )


def test_zoom_presentation_separates_value_from_instructions() -> None:
    state = settings_state(
        MapZoomSettingsState(
            zoom=13,
            bounds=MapZoomBounds(6, 15),
            style=MapPackageStyle.DAY,
            available_styles=(MapPackageStyle.DAY, MapPackageStyle.NIGHT),
        )
    )

    title, value, instructions, value_color = _zoom_presentation(state)

    assert title == "MAP ZOOM"
    assert value == "13"
    assert instructions == (
        "RANGE 6-15\n"
        "TURN ENCODER: OUT / IN\n"
        "MAP STYLE: DAY\n"
        "BUTTON #2: DAY / NIGHT"
    )
    assert value_color == _HEALTHY


def test_disabled_zoom_uses_muted_disabled_value() -> None:
    title, value, instructions, value_color = _zoom_presentation(
        settings_state(None)
    )

    assert title == "MAP ZOOM"
    assert value == "DISABLED"
    assert instructions == ""
    assert value_color == _DISABLED


def test_settings_typography_is_reduced_and_instructions_are_smallest() -> None:
    assert _SETTINGS_PRIMARY_FONT_SIZE == 28
    assert _SETTINGS_ZOOM_FONT_SIZE == 36
    assert _SETTINGS_CARD_FONT_SIZE == 30
    assert _SETTINGS_SECONDARY_FONT_SIZE == 18
    assert _SETTINGS_INSTRUCTION_FONT_SIZE == 20
    assert _SETTINGS_SECONDARY_FONT_SIZE < _SETTINGS_INSTRUCTION_FONT_SIZE
    assert _SETTINGS_INSTRUCTION_FONT_SIZE < _SETTINGS_PRIMARY_FONT_SIZE
