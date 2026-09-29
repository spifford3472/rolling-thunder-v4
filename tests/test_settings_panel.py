"""Tests for nonblocking Settings map/radar controls."""

from dataclasses import dataclass

from rolling_thunder.settings_panel import DashboardSettingsController


@dataclass
class FakeMapZoomState:
    lines: tuple[str, ...] = ("MAP ZOOM", "12")


class FakeMapZoom:
    def __init__(self) -> None:
        self.state = FakeMapZoomState()
        self.out_count = 0
        self.in_count = 0

    def zoom_out(self) -> bool:
        self.out_count += 1
        return True

    def zoom_in(self) -> bool:
        self.in_count += 1
        return True

    def toggle_style(self) -> bool:
        self.style_toggle_count = getattr(self, "style_toggle_count", 0) + 1
        return True


class FakeRadar:
    def __init__(self, enabled: bool = True) -> None:
        self._enabled = enabled

    @property
    def display_enabled(self) -> bool:
        return self._enabled

    def set_display_enabled(self, enabled: bool) -> bool:
        if self._enabled is enabled:
            return False
        self._enabled = enabled
        return True


class FakePersistence:
    def __init__(self) -> None:
        self.values: list[bool] = []
        self.callsign_values: list[bool] = []

    def persist_radar_image_enabled(self, enabled: bool) -> bool:
        self.values.append(enabled)
        return True

    def persist_callsign_info_enabled(self, enabled: bool) -> bool:
        self.callsign_values.append(enabled)
        return True


class FakeCallsignInfo:
    def __init__(self, enabled: bool = True) -> None:
        self._enabled = enabled

    @property
    def state(self) -> object:
        return type("State", (), {"enabled": self._enabled})()

    def set_enabled(self, enabled: bool) -> bool:
        if enabled == self._enabled:
            return False
        self._enabled = enabled
        return True


def test_settings_state_reports_radar_image_and_map_zoom() -> None:
    map_zoom = FakeMapZoom()
    radar = FakeRadar(enabled=True)
    persistence = FakePersistence()
    controller = DashboardSettingsController(map_zoom, radar, persistence)  # type: ignore[arg-type]

    state = controller.state

    assert state.radar_available is True
    assert state.radar_image_enabled is True
    assert state.map_zoom is map_zoom.state


def test_context_radar_toggle_updates_runtime_and_queues_persistence() -> None:
    radar = FakeRadar(enabled=True)
    persistence = FakePersistence()
    controller = DashboardSettingsController(None, radar, persistence)

    assert controller.toggle_radar() is True
    assert radar.display_enabled is False
    assert persistence.values == [False]

    assert controller.toggle_radar() is True
    assert radar.display_enabled is True
    assert persistence.values == [False, True]


def test_unavailable_radar_does_not_toggle_or_persist() -> None:
    persistence = FakePersistence()
    controller = DashboardSettingsController(None, None, persistence)

    assert controller.state.radar_available is False
    assert controller.state.radar_image_enabled is False
    assert controller.toggle_radar() is False
    assert persistence.values == []


class FakeMapStyleAutomation:
    def __init__(self) -> None:
        self.override_count = 0

    def note_manual_override(self) -> None:
        self.override_count += 1


def test_manual_map_style_toggle_notifies_automatic_policy() -> None:
    map_zoom = FakeMapZoom()
    persistence = FakePersistence()
    automation = FakeMapStyleAutomation()
    controller = DashboardSettingsController(
        map_zoom,  # type: ignore[arg-type]
        None,
        persistence,
        automation,
    )

    assert controller.toggle_map_style() is True
    assert map_zoom.style_toggle_count == 1
    assert automation.override_count == 1



def test_callsign_info_toggle_updates_runtime_and_persists() -> None:
    persistence = FakePersistence()
    callsign = FakeCallsignInfo(enabled=True)
    controller = DashboardSettingsController(
        None,
        None,
        persistence,
        callsign_info=callsign,  # type: ignore[arg-type]
    )

    assert controller.state.callsign_info_available is True
    assert controller.state.callsign_info_enabled is True
    assert controller.toggle_callsign_info() is True
    assert controller.state.callsign_info_enabled is False
    assert persistence.callsign_values == [False]
