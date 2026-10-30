"""Tests for pure Settings presentation helpers."""

from rolling_thunder.control_transport_health import TransportHealthState
from rolling_thunder.map_sources import MapPackageStyle
from rolling_thunder.map_zoom import MapZoomBounds, MapZoomSettingsState
from rolling_thunder.power_control import PowerAction, PowerConfirmationState
from rolling_thunder.settings_panel import DashboardSettingsState
from rolling_thunder.settings_selection import SettingsOption
from rolling_thunder.settings_ui import (
    _HEALTHY,
    _SETTINGS_CARD_FONT_SIZE,
    _SETTINGS_SECONDARY_FONT_SIZE,
    _SETTINGS_VALUE_FONT_SIZE,
    _map_style_presentation,
    _map_zoom_presentation,
    _power_presentation,
    _settings_window,
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
    assert instruction == "B2 OUT   B3 IN    Range 6-15"
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
    assert instruction == "B2 NIGHT   B3 DAY"
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
        "B2 OUT   B3 IN",
        "UNAVAILABLE",
    )
    assert _map_style_presentation(state) == (
        "MAP STYLE",
        "B2 NIGHT   B3 DAY",
        "UNAVAILABLE",
        False,
    )


def test_settings_cards_preserve_installed_readable_typography() -> None:
    assert _SETTINGS_CARD_FONT_SIZE == 30
    assert _SETTINGS_SECONDARY_FONT_SIZE == 18
    assert _SETTINGS_VALUE_FONT_SIZE == 36
    assert _SETTINGS_SECONDARY_FONT_SIZE < _SETTINGS_CARD_FONT_SIZE
    assert _SETTINGS_CARD_FONT_SIZE < _SETTINGS_VALUE_FONT_SIZE
    assert _HEALTHY == "#66ccff"


def test_four_row_window_always_contains_selected_row() -> None:
    assert _settings_window(SettingsOption.MAP_ZOOM) == tuple(SettingsOption)[:4]
    assert _settings_window(SettingsOption.MAP_STYLE) == tuple(SettingsOption)[:4]
    assert _settings_window(SettingsOption.REBOOT) == tuple(SettingsOption)[1:5]
    assert _settings_window(SettingsOption.SHUTDOWN) == tuple(SettingsOption)[2:]


def test_power_copy_is_truthful_available_staged_pending_and_failed() -> None:
    available = PowerConfirmationState(
        available=True,
        health=TransportHealthState.HEALTHY,
    )
    assert _power_presentation(SettingsOption.REBOOT, available) == (
        "SELECT",
        "B2 CANCEL   B3 SELECT",
    )
    staged = PowerConfirmationState(
        action=PowerAction.REBOOT,
        available=True,
        health=TransportHealthState.HEALTHY,
    )
    assert _power_presentation(SettingsOption.REBOOT, staged) == (
        "CONFIRM",
        "B2 CANCEL   B3 CONFIRM",
    )
    pending = PowerConfirmationState(action=PowerAction.REBOOT, pending=True)
    assert _power_presentation(SettingsOption.REBOOT, pending)[0] == "REBOOT PENDING"
    failed = PowerConfirmationState(last_error="permission denied by policy")
    assert _power_presentation(SettingsOption.SHUTDOWN, failed) == (
        "SHUTDOWN FAILED",
        "permission denied by policy",
    )
    unavailable = PowerConfirmationState(health=TransportHealthState.STALE)
    assert _power_presentation(SettingsOption.REBOOT, unavailable) == (
        "UNAVAILABLE",
        "STALE",
    )
