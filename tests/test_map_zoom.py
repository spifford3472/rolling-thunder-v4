"""Tests for persistent Map Zoom domain behavior."""

from rolling_thunder.map_sources import InstalledMapMetadata, MapPackageStyle
from rolling_thunder.map_zoom import (
    MapZoomBounds,
    MapZoomSettingsController,
    effective_map_zoom_bounds,
    resolve_initial_map_zoom,
)


def metadata(
    identifier: str,
    *,
    style: MapPackageStyle,
    minimum: int,
    maximum: int,
) -> InstalledMapMetadata:
    return InstalledMapMetadata(
        identifier=identifier,
        name=identifier,
        bounds=(-85.0, 39.0, -82.0, 41.0),
        min_zoom=minimum,
        max_zoom=maximum,
        attribution="TEST",
        version="1",
        style=style,
        priority=0,
    )


class FakeLiveMap:
    def __init__(self, zoom: int) -> None:
        self._zoom = zoom
        self.changes: list[int] = []

    @property
    def zoom(self) -> int:
        return self._zoom

    def set_zoom(self, zoom: int) -> bool:
        if zoom == self._zoom:
            return False
        self._zoom = zoom
        self.changes.append(zoom)
        return True


class FakePersistence:
    def __init__(self) -> None:
        self.values: list[int] = []

    def persist_map_zoom(self, zoom: int) -> bool:
        self.values.append(zoom)
        return True


def test_installed_active_style_defines_effective_zoom_bounds() -> None:
    packages = (
        metadata("night", style=MapPackageStyle.NIGHT, minimum=0, maximum=15),
        metadata("day", style=MapPackageStyle.DAY, minimum=3, maximum=18),
    )

    assert effective_map_zoom_bounds(
        packages,
        style=MapPackageStyle.NIGHT,
    ) == MapZoomBounds(0, 15)


def test_no_installed_active_style_uses_generic_xyz_bounds() -> None:
    packages = (
        metadata("day", style=MapPackageStyle.DAY, minimum=3, maximum=18),
    )

    assert effective_map_zoom_bounds(
        packages,
        style=MapPackageStyle.NIGHT,
    ) == MapZoomBounds(0, 22)


def test_valid_stored_zoom_wins_over_configured_zoom() -> None:
    assert resolve_initial_map_zoom(12, 15, MapZoomBounds(0, 15)) == 12


def test_invalid_stored_zoom_falls_back_to_clamped_configuration() -> None:
    assert resolve_initial_map_zoom(16, 17, MapZoomBounds(0, 15)) == 15
    assert resolve_initial_map_zoom(None, 17, MapZoomBounds(0, 15)) == 15


def test_settings_encoder_changes_zoom_and_queues_persistence() -> None:
    live_map = FakeLiveMap(15)
    persistence = FakePersistence()
    settings = MapZoomSettingsController(
        live_map,
        MapZoomBounds(0, 15),
        persistence,
    )

    assert settings.zoom_out() is True
    assert settings.state.zoom == 14
    assert live_map.changes == [14]
    assert persistence.values == [14]

    assert settings.zoom_in() is True
    assert settings.state.zoom == 15
    assert live_map.changes == [14, 15]
    assert persistence.values == [14, 15]


def test_settings_zoom_does_not_wrap_past_effective_bounds() -> None:
    live_map = FakeLiveMap(15)
    persistence = FakePersistence()
    settings = MapZoomSettingsController(
        live_map,
        MapZoomBounds(0, 15),
        persistence,
    )

    assert settings.zoom_in() is False
    assert live_map.zoom == 15
    assert persistence.values == []


def test_settings_state_exposes_compact_operator_text() -> None:
    settings = MapZoomSettingsController(
        FakeLiveMap(13),
        MapZoomBounds(0, 15),
        FakePersistence(),
    )

    assert settings.state.lines == (
        "MAP ZOOM",
        "13",
        "RANGE 0-15",
        "TURN ENCODER: OUT / IN",
    )
