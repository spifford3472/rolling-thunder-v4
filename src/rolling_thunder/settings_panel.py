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


class RadarImagePersistence(Protocol):
    """Nonblocking persistence capability for the radar-image preference."""

    def persist_radar_image_enabled(self, enabled: bool) -> bool:
        """Queue durable persistence for the radar-image setting."""
        ...


@dataclass(frozen=True, slots=True)
class DashboardSettingsState:
    """Immutable Settings presentation state."""

    map_zoom: MapZoomSettingsState | None
    radar_available: bool
    radar_image_enabled: bool


class DashboardSettingsController:
    """Own nonblocking operator controls displayed on the Settings page."""

    def __init__(
        self,
        map_zoom: MapZoomSettingsController | None,
        radar: RadarImageTarget | None,
        persistence: RadarImagePersistence,
    ) -> None:
        self._map_zoom = map_zoom
        self._radar = radar
        self._persistence = persistence

    @property
    def state(self) -> DashboardSettingsState:
        """Return immutable current Settings state without I/O."""
        radar = self._radar
        return DashboardSettingsState(
            map_zoom=self._map_zoom.state if self._map_zoom is not None else None,
            radar_available=radar is not None,
            radar_image_enabled=radar.display_enabled if radar is not None else False,
        )

    def zoom_out(self) -> bool:
        """Decrease map zoom when the live map is available."""
        return self._map_zoom is not None and self._map_zoom.zoom_out()

    def zoom_in(self) -> bool:
        """Increase map zoom when the live map is available."""
        return self._map_zoom is not None and self._map_zoom.zoom_in()

    def toggle_map_style(self) -> bool:
        """Switch between installed day/night packages without network I/O."""
        return self._map_zoom is not None and self._map_zoom.toggle_style()

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
