"""Typed Settings-panel controls for map zoom/style and optional radar image."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from rolling_thunder.callsign_info_service import CallsignInfoLookupService
from rolling_thunder.map_sources import MapPackageStyle
from rolling_thunder.map_zoom import MapZoomSettingsController, MapZoomSettingsState
from rolling_thunder.power_control import PowerConfirmationState
from rolling_thunder.settings_selection import SettingId, SettingsSelection


class PowerConfirmationCommands(Protocol):
    @property
    def state(self) -> PowerConfirmationState: ...
    def cancel(self) -> bool: ...


class RadarImageTarget(Protocol):
    """Runtime radar-image visibility capability used by Settings."""

    @property
    def display_enabled(self) -> bool:
        """Return whether Pi-side radar image work is currently enabled."""
        ...

    def set_display_enabled(self, enabled: bool) -> bool:
        """Change Pi-side radar image work and return whether it changed."""
        ...


class MapStyleAutomation(Protocol):
    """Automatic map-style policy notified by explicit operator overrides."""

    def note_manual_override(self) -> None:
        """Keep the manual style until the next real solar transition."""
        ...


class RadarImagePersistence(Protocol):
    """Nonblocking persistence capability for the radar-image preference."""

    def persist_radar_image_enabled(self, enabled: bool) -> bool:
        """Queue durable persistence for the radar-image setting."""
        ...

    def persist_callsign_info_enabled(self, enabled: bool) -> bool:
        """Queue durable persistence for the callsign-info setting."""
        ...


@dataclass(frozen=True, slots=True)
class DashboardSettingsState:
    """Immutable Settings presentation state."""

    map_zoom: MapZoomSettingsState | None
    radar_available: bool
    radar_image_enabled: bool
    callsign_info_available: bool = False
    callsign_info_enabled: bool = False
    selection: SettingsSelection = field(default_factory=SettingsSelection)
    power_confirmation: PowerConfirmationState = field(default_factory=PowerConfirmationState)


class DashboardSettingsController:
    """Own nonblocking operator controls displayed on the Settings page."""

    def __init__(
        self,
        map_zoom: MapZoomSettingsController | None,
        radar: RadarImageTarget | None,
        persistence: RadarImagePersistence,
        map_style_automation: MapStyleAutomation | None = None,
        callsign_info: CallsignInfoLookupService | None = None,
        power_confirmation: PowerConfirmationCommands | None = None,
    ) -> None:
        self._map_zoom = map_zoom
        self._radar = radar
        self._persistence = persistence
        self._map_style_automation = map_style_automation
        self._callsign_info = callsign_info
        self._selection = SettingsSelection()
        self._power_confirmation = power_confirmation

    @property
    def state(self) -> DashboardSettingsState:
        """Return immutable current Settings state without I/O."""
        radar = self._radar
        callsign_info = self._callsign_info
        callsign_enabled = (
            callsign_info.state.enabled if callsign_info is not None else False
        )
        return DashboardSettingsState(
            map_zoom=self._map_zoom.state if self._map_zoom is not None else None,
            radar_available=radar is not None,
            radar_image_enabled=radar.display_enabled if radar is not None else False,
            callsign_info_available=callsign_info is not None,
            callsign_info_enabled=callsign_enabled,
            selection=self._selection,
            power_confirmation=(
                PowerConfirmationState()
                if self._power_confirmation is None
                else self._power_confirmation.state
            ),
        )

    def attach_power_confirmation(self, owner: PowerConfirmationCommands) -> None:
        """Attach the single typed power-confirmation owner during composition."""
        self._power_confirmation = owner

    def cancel_power_confirmation(self) -> bool:
        """Cancel staged power work on Settings departure."""
        return self._power_confirmation is not None and self._power_confirmation.cancel()

    def move_selection(self, delta: int) -> bool:
        """Move only the highlighted Settings row."""
        moved = self._selection.moved(delta)
        if moved == self._selection:
            return False
        if self._power_confirmation is not None:
            self._power_confirmation.cancel()
        self._selection = moved
        return True

    def lower_selected(self) -> bool:
        """Apply Button 2's explicit lower/off choice to the selected row."""
        selected = self._selection.selected
        if selected is SettingId.MAP_ZOOM:
            return self.zoom_out()
        if selected is SettingId.RADAR:
            return self.set_radar(False)
        if selected is SettingId.CALLSIGN_INFO:
            return self.set_callsign_info(False)
        if selected is SettingId.MAP_STYLE:
            return self.set_map_style(MapPackageStyle.NIGHT)
        return False

    def higher_selected(self) -> bool:
        """Apply Button 3's explicit higher/on choice to the selected row."""
        selected = self._selection.selected
        if selected is SettingId.MAP_ZOOM:
            return self.zoom_in()
        if selected is SettingId.RADAR:
            return self.set_radar(True)
        if selected is SettingId.CALLSIGN_INFO:
            return self.set_callsign_info(True)
        if selected is SettingId.MAP_STYLE:
            return self.set_map_style(MapPackageStyle.DAY)
        return False

    def set_map_style(self, style: MapPackageStyle) -> bool:
        """Set DAY/NIGHT explicitly and arm the solar manual override on change."""
        if self._map_zoom is None or not self._map_zoom.set_style(style):
            return False
        if self._map_style_automation is not None:
            self._map_style_automation.note_manual_override()
        return True

    def set_callsign_info(self, enabled: bool) -> bool:
        """Set callsign information explicitly and persist only actual changes."""
        if not isinstance(enabled, bool):
            raise TypeError("Callsign-info state must be boolean.")
        target = self._callsign_info
        if target is None or target.state.enabled == enabled:
            return False
        if not target.set_enabled(enabled):
            return False
        self._persistence.persist_callsign_info_enabled(enabled)
        return True

    def set_radar(self, enabled: bool) -> bool:
        """Set radar explicitly and persist only actual changes."""
        if not isinstance(enabled, bool):
            raise TypeError("Radar state must be boolean.")
        radar = self._radar
        if radar is None or radar.display_enabled == enabled:
            return False
        if not radar.set_display_enabled(enabled):
            return False
        self._persistence.persist_radar_image_enabled(enabled)
        return True

    def zoom_out(self) -> bool:
        """Decrease map zoom when the live map is available."""
        return self._map_zoom is not None and self._map_zoom.zoom_out()

    def zoom_in(self) -> bool:
        """Increase map zoom when the live map is available."""
        return self._map_zoom is not None and self._map_zoom.zoom_in()

    def toggle_map_style(self) -> bool:
        """Apply an immediate manual style override until the next solar transition."""
        if self._map_zoom is None or not self._map_zoom.toggle_style():
            return False
        if self._map_style_automation is not None:
            self._map_style_automation.note_manual_override()
        return True

    def toggle_callsign_info(self) -> bool:
        """Toggle callsign information immediately and persist the operator choice."""
        target = self._callsign_info
        if target is None:
            return False
        return self.set_callsign_info(not target.state.enabled)

    def toggle_radar(self) -> bool:
        """Toggle only Pi-side radar image work and persist the operator choice."""
        radar = self._radar
        if radar is None:
            return False
        return self.set_radar(not radar.display_enabled)
