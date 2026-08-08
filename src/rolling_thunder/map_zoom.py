"""Typed live-map zoom bounds, fallback, and Settings commands."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Protocol

from rolling_thunder.map_sources import InstalledMapMetadata, MapPackageStyle

OPERATOR_MINIMUM_MAP_ZOOM: Final = 6
OPERATOR_MAXIMUM_MAP_ZOOM: Final = 22


@dataclass(frozen=True, slots=True)
class MapZoomBounds:
    """Effective operator-selectable zoom interval."""

    minimum: int
    maximum: int

    def __post_init__(self) -> None:
        if not OPERATOR_MINIMUM_MAP_ZOOM <= self.minimum <= OPERATOR_MAXIMUM_MAP_ZOOM:
            raise ValueError(
                "Minimum operator map zoom must be between "
                f"{OPERATOR_MINIMUM_MAP_ZOOM} and {OPERATOR_MAXIMUM_MAP_ZOOM}."
            )
        if not OPERATOR_MINIMUM_MAP_ZOOM <= self.maximum <= OPERATOR_MAXIMUM_MAP_ZOOM:
            raise ValueError(
                "Maximum operator map zoom must be between "
                f"{OPERATOR_MINIMUM_MAP_ZOOM} and {OPERATOR_MAXIMUM_MAP_ZOOM}."
            )
        if self.minimum > self.maximum:
            raise ValueError("Minimum map zoom must not exceed maximum map zoom.")

    def contains(self, zoom: int) -> bool:
        """Return whether one zoom is inside the effective interval."""
        return self.minimum <= zoom <= self.maximum

    def clamp(self, zoom: int) -> int:
        """Clamp one zoom into the effective interval."""
        return min(max(zoom, self.minimum), self.maximum)


def effective_map_zoom_bounds(
    packages: tuple[InstalledMapMetadata, ...],
    *,
    style: MapPackageStyle,
) -> MapZoomBounds:
    """Use installed metadata while enforcing the useful operator minimum zoom."""
    matching = tuple(package for package in packages if package.style is style)
    if not matching:
        return MapZoomBounds(OPERATOR_MINIMUM_MAP_ZOOM, OPERATOR_MAXIMUM_MAP_ZOOM)

    package_minimum = min(package.min_zoom for package in matching)
    package_maximum = max(package.max_zoom for package in matching)
    return MapZoomBounds(
        max(OPERATOR_MINIMUM_MAP_ZOOM, package_minimum),
        package_maximum,
    )


def resolve_initial_map_zoom(
    stored_zoom: int | None,
    configured_zoom: int,
    bounds: MapZoomBounds,
) -> int:
    """Prefer a valid stored operator value, otherwise safely clamp configuration."""
    if stored_zoom is not None and bounds.contains(stored_zoom):
        return stored_zoom
    return bounds.clamp(configured_zoom)


class LiveMapZoomTarget(Protocol):
    """In-memory live-map zoom capability used by Settings."""

    @property
    def zoom(self) -> int:
        """Return the active zoom."""

    def set_zoom(self, zoom: int) -> bool:
        """Change the in-memory zoom, returning whether it changed."""


class MapZoomPersistence(Protocol):
    """Nonblocking persistence capability used by Settings."""

    def persist_map_zoom(self, zoom: int) -> bool:
        """Queue durable persistence for one zoom."""


@dataclass(frozen=True, slots=True)
class MapZoomSettingsState:
    """Immutable Settings presentation state."""

    zoom: int
    bounds: MapZoomBounds

    @property
    def lines(self) -> tuple[str, ...]:
        """Return compact operator-facing Settings text."""
        return (
            "MAP ZOOM",
            str(self.zoom),
            f"RANGE {self.bounds.minimum}-{self.bounds.maximum}",
            "TURN ENCODER: OUT / IN",
        )


class MapZoomSettingsController:
    """Apply encoder zoom commands immediately and persist them asynchronously."""

    def __init__(
        self,
        live_map: LiveMapZoomTarget,
        bounds: MapZoomBounds,
        persistence: MapZoomPersistence,
    ) -> None:
        if not bounds.contains(live_map.zoom):
            raise ValueError("Initial live-map zoom must be inside effective bounds.")
        self._live_map = live_map
        self._bounds = bounds
        self._persistence = persistence

    @property
    def state(self) -> MapZoomSettingsState:
        """Return current immutable Settings state without I/O."""
        return MapZoomSettingsState(self._live_map.zoom, self._bounds)

    def zoom_out(self) -> bool:
        """Decrease zoom one step without wrapping."""
        return self._set_zoom(self._live_map.zoom - 1)

    def zoom_in(self) -> bool:
        """Increase zoom one step without wrapping."""
        return self._set_zoom(self._live_map.zoom + 1)

    def _set_zoom(self, requested: int) -> bool:
        target = self._bounds.clamp(requested)
        if not self._live_map.set_zoom(target):
            return False
        self._persistence.persist_map_zoom(target)
        return True
