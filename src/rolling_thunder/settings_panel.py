"""Typed Settings-panel controls for map zoom/style and optional radar image."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from rolling_thunder.map_zoom import MapZoomSettingsController, MapZoomSettingsState


class RadarImageTarget(Protocol):
    """Runtime radar-image visibility capability used by Settings."""

    @property
    def display_enabled(self) -> bool:
        """Return whether Pi-side radar image work is currently enabled."""
        ...

    def set_display_enabled(self, enabled: bool) -> bool:
        """Change Pi-side radar image work and return whether it changed."""
        ...


class CallsignInfoToggleState(Protocol):
    """Small immutable state view needed by Settings."""

    enabled: bool


class CallsignInfoTarget(Protocol):
    """Runtime callsign-info visibility capability used by Settings."""

    @property
    def state(self) -> CallsignInfoToggleState:
        ...

    def set_enabled(self, enabled: bool) -> bool:
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


class DashboardSettingsController:
    """Own nonblocking operator controls displayed on the Settings page."""

    def __init__(
        self,
        map_zoom: MapZoomSettingsController | None,
        radar: RadarImageTarget | None,
        persistence: RadarImagePersistence,
        map_style_automation: MapStyleAutomation | None = None,
        callsign_info: CallsignInfoTarget | None = None,
    ) -> None:
        self._map_zoom = map_zoom
        self._radar = radar
        self._persistence = persistence
        self._map_style_automation = map_style_automation
        self._callsign_info = callsign_info

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
        )

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
        automation = self._map_style_automation
        if automation is not None:
            automation.note_manual_override()
        return True

    def toggle_callsign_info(self) -> bool:
        """Toggle callsign information immediately and persist the operator choice."""
        target = self._callsign_info
        if target is None:
            return False
        current = target.state.enabled
        enabled = not current
        if not target.set_enabled(enabled):
            return False
        self._persistence.persist_callsign_info_enabled(enabled)
        return True

    def toggle_radar(self) -> bool:
        """Toggle only Pi-side radar image work and persist the operator choice."""
        radar = self._radar
        if radar is None:
            return False
        enabled = not radar.display_enabled
        if not radar.set_display_enabled(enabled):
            return False
        self._persistence.persist_radar_image_enabled(enabled)
        return True
