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

    def persist_radar_image_enabled(self, enabled: bool) -> bool:
        self.values.append(enabled)
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
