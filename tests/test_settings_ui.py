"""Tests for pure Settings presentation helpers."""

import sys
from types import SimpleNamespace
from typing import Any

from rolling_thunder.control_transport_health import TransportHealthState
from rolling_thunder.map_sources import MapPackageStyle
from rolling_thunder.map_zoom import MapZoomBounds, MapZoomSettingsState
from rolling_thunder.power_control import PowerAction, PowerConfirmationState
from rolling_thunder.settings_panel import DashboardSettingsState
from rolling_thunder.settings_selection import SettingsOption, SettingsSelection
from rolling_thunder.settings_ui import (
    _HEALTHY,
    _SETTINGS_CARD_FONT_SIZE,
    _SETTINGS_SECONDARY_FONT_SIZE,
    _SETTINGS_SWITCH_HEIGHT_PX,
    _SETTINGS_VALUE_FONT_SIZE,
    SettingsWidgets,
    _map_style_presentation,
    _map_zoom_presentation,
    _power_presentation,
)


class FakeWidget:
    def __init__(self, *args: object, **kwargs: object) -> None:
        self.grid_removed = False

    def grid(self, **kwargs: object) -> None:
        self.grid_removed = False

    def grid_remove(self) -> None:
        self.grid_removed = True

    def grid_columnconfigure(self, *args: object, **kwargs: object) -> None:
        pass

    def grid_rowconfigure(self, *args: object, **kwargs: object) -> None:
        pass

    def configure(self, **kwargs: object) -> None:
        pass

    def delete(self, *args: object) -> None:
        pass

    def create_oval(self, *args: object, **kwargs: object) -> None:
        pass

    def create_rectangle(self, *args: object, **kwargs: object) -> None:
        pass

    def create_text(self, *args: object, **kwargs: object) -> None:
        pass


class FakeStringVar:
    def __init__(self, *, value: str) -> None:
        self.value = value

    def set(self, value: str) -> None:
        self.value = value


def fake_tk_module() -> Any:
    return SimpleNamespace(
        Frame=FakeWidget,
        Label=FakeWidget,
        Canvas=FakeWidget,
        StringVar=FakeStringVar,
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


def test_six_row_layout_keeps_readable_fonts_with_compact_switches() -> None:
    assert len(tuple(SettingsOption)) == 6
    assert _SETTINGS_CARD_FONT_SIZE == 30
    assert _SETTINGS_SECONDARY_FONT_SIZE == 18
    assert _SETTINGS_VALUE_FONT_SIZE == 36
    assert _SETTINGS_SWITCH_HEIGHT_PX == 40


def test_all_six_rows_remain_visible_when_shutdown_is_selected(monkeypatch: Any) -> None:
    monkeypatch.setitem(sys.modules, "tkinter", fake_tk_module())
    widgets = SettingsWidgets(None)
    state = DashboardSettingsState(
        map_zoom=None,
        radar_available=False,
        radar_image_enabled=False,
        selection=SettingsSelection(SettingsOption.SHUTDOWN),
    )

    widgets.update(state)

    assert len(widgets._cards) == 6
    assert all(not card.grid_removed for card in widgets._cards.values())
    assert "MORE" not in widgets._action_text.value
    assert widgets._action_text.value == "NO TRUSTED INPUT"


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
