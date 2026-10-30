"""Tests for the pure Settings selection domain."""

import pytest

from rolling_thunder.settings_selection import SettingId, SettingsOption, SettingsSelection


def test_initial_selection_and_order_are_fixed() -> None:
    assert SettingId is SettingsOption
    selection = SettingsSelection()
    assert selection.selected is SettingId.MAP_ZOOM
    assert selection.ORDER == (
        SettingId.MAP_ZOOM,
        SettingId.RADAR,
        SettingId.CALLSIGN_INFO,
        SettingId.MAP_STYLE,
        SettingId.REBOOT,
        SettingId.SHUTDOWN,
    )


def test_movement_is_clamped_and_does_not_mutate() -> None:
    initial = SettingsSelection()
    assert initial.moved(-1) == initial
    assert initial.moved(3).selected is SettingId.MAP_STYLE
    assert initial.moved(99).selected is SettingId.SHUTDOWN
    assert initial.selected is SettingId.MAP_ZOOM


@pytest.mark.parametrize("invalid", [True, False, 1.5, "1", None])
def test_movement_rejects_bool_and_non_integer_values(invalid: object) -> None:
    with pytest.raises(TypeError):
        SettingsSelection().moved(invalid)  # type: ignore[arg-type]


def test_selection_rejects_non_enum_values() -> None:
    with pytest.raises(TypeError):
        SettingsSelection(True)  # type: ignore[arg-type]
