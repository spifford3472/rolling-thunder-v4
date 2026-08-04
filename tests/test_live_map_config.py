"""Tests for typed live-map configuration."""

from pathlib import Path

import pytest

from rolling_thunder.config import (
    ApplicationConfig,
    ConfigurationValidationError,
    load_config,
)


def write_config(tmp_path: Path, map_yaml: str) -> Path:
    path = tmp_path / "rolling-thunder.yaml"
    path.write_text(
        f"""
operator:
  callsign: KI5VNB
  home_grid: EM79xm
map:
{map_yaml}
""",
        encoding="utf-8",
    )
    return path


def test_map_defaults_are_safe_and_disabled() -> None:
    config = ApplicationConfig.model_validate(
        {
            "operator": {
                "callsign": "KI5VNB",
                "home_grid": "EM79xm",
            }
        }
    )

    assert config.map.enabled is False
    assert config.map.zoom == 17
    assert config.map.cache_retention_days == 7
    assert config.map.installed_packages == ()
    assert config.map.style.value == "day"
    assert config.map.online_attribution == "© OpenStreetMap contributors"


def test_map_configuration_loads_and_resolves_cache_path(tmp_path: Path) -> None:
    config = load_config(
        write_config(
            tmp_path,
            """  enabled: true
  zoom: 12
  cache_directory: cache/map
  installed_packages:
    - maps/ohio.mbtiles
    - /opt/rolling-thunder/maps/corridor.mbtiles
  style: night
  online_attribution: © Example Map Provider
""",
        )
    )

    assert config.map.enabled is True
    assert config.map.zoom == 12
    assert config.map.cache_directory == (tmp_path / "cache/map").resolve()
    assert config.map.installed_packages == (
        (tmp_path / "maps/ohio.mbtiles").resolve(),
        Path("/opt/rolling-thunder/maps/corridor.mbtiles"),
    )
    assert config.map.style.value == "night"
    assert config.map.online_attribution == "© Example Map Provider"


@pytest.mark.parametrize(
    ("map_yaml", "expected"),
    [
        (
            """  enabled: true
  tile_url_template: https://tiles.example.invalid/{z}/{x}.png
""",
            "map.tile_url_template",
        ),
        (
            """  enabled: true
  cache_retention_days: 6
""",
            "map.cache_retention_days",
        ),
        (
            """  enabled: true
  cache_directory: ""
""",
            "map.cache_directory",
        ),
        (
            """  enabled: true
  installed_packages:
    - maps/ohio.sqlite
""",
            "map.installed_packages",
        ),
        (
            """  enabled: true
  online_attribution: "   "
""",
            "map.online_attribution",
        ),
    ],
)
def test_invalid_map_configuration_is_actionable(
    tmp_path: Path,
    map_yaml: str,
    expected: str,
) -> None:
    with pytest.raises(ConfigurationValidationError, match=expected):
        load_config(write_config(tmp_path, map_yaml))
