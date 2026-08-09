"""Tests for routing generic Settings controls to map zoom and radar image."""

from rolling_thunder.active_panel_commands import SharedSpotActivePanelCommandController
from rolling_thunder.context_navigation import ContextId, ContextNavigationController
from rolling_thunder.domain import Frequency
from rolling_thunder.spot_domain import SpotIdentity, SpotProvider
from rolling_thunder.spot_selection import StagedSpotAction


class FakeSharedPanel:
    provider = SpotProvider.POTA
    selected_identity: SpotIdentity | None = None
    staged_identity: SpotIdentity | None = None
    staged_action: StagedSpotAction | None = None

    def activate(
        self,
        provider: SpotProvider,
        *,
        current_frequency: Frequency | None = None,
    ) -> None:
        del current_frequency
        self.provider = provider

    def select_previous(self) -> None:
        pass

    def select_next(self) -> None:
        pass

    def clear_selection(self) -> None:
        pass

    def stage_selected(self) -> None:
        pass

    def cancel_staging(self) -> None:
        self.staged_identity = None
        self.staged_action = None

    def invalidate_radio(self) -> None:
        self.cancel_staging()

    def next_pota_band(self) -> None:
        pass

    def next_pota_mode(self) -> None:
        pass

    def next_dx_band(self) -> None:
        pass

    def next_dx_mode(self) -> None:
        pass


class FakeSettings:
    def __init__(self) -> None:
        self.out_count = 0
        self.in_count = 0
        self.radar_toggle_count = 0

    def toggle_radar(self) -> bool:
        self.radar_toggle_count += 1
        return True

    def zoom_out(self) -> bool:
        self.out_count += 1
        return True

    def zoom_in(self) -> bool:
        self.in_count += 1
        return True


def test_settings_context_routes_previous_next_to_map_zoom() -> None:
    navigation = ContextNavigationController(ContextId.SETTINGS)
    settings = FakeSettings()
    controller = SharedSpotActivePanelCommandController(
        navigation,
        FakeSharedPanel(),
        current_frequency=lambda: None,
        settings_panel=settings,
    )

    assert controller.move_previous() is True
    assert controller.move_next() is True
    assert settings.out_count == 1
    assert settings.in_count == 1


def test_settings_context_routes_primary_to_radar_image_toggle() -> None:
    navigation = ContextNavigationController(ContextId.SETTINGS)
    settings = FakeSettings()
    controller = SharedSpotActivePanelCommandController(
        navigation,
        FakeSharedPanel(),
        current_frequency=lambda: None,
        settings_panel=settings,
    )

    assert controller.primary() is True
    assert settings.radar_toggle_count == 1


def test_non_settings_context_does_not_change_settings() -> None:
    navigation = ContextNavigationController(ContextId.AI)
    settings = FakeSettings()
    controller = SharedSpotActivePanelCommandController(
        navigation,
        FakeSharedPanel(),
        current_frequency=lambda: None,
        settings_panel=settings,
    )

    assert controller.primary() is False
    assert controller.move_previous() is False
    assert controller.move_next() is False
    assert settings.radar_toggle_count == 0
    assert settings.out_count == 0
    assert settings.in_count == 0
