"""Tests for explicit Pi radar activation and runtime composition."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from rolling_thunder.application_runtime import ApplicationRuntime
from rolling_thunder.config import ApplicationConfig


def base_payload(tmp_path: Path) -> dict[str, object]:
    return {
        "operator": {"callsign": "KI5VNB", "home_grid": "EM79xm"},
        "hardware": {"mock": True},
        "forge": {
            "enabled": True,
            "api_url": "http://192.168.9.170:8766",
        },
        "map": {
            "enabled": True,
            "zoom": 7,
            "cache_directory": str(tmp_path / "map-cache"),
            "installed_packages": [],
        },
        "radar": {"enabled": True},
    }


def test_radar_requires_map_and_forge() -> None:
    with pytest.raises(ValidationError, match="map.enabled"):
        ApplicationConfig.model_validate(
            {
                "operator": {"callsign": "KI5VNB", "home_grid": "EM79xm"},
                "forge": {
                    "enabled": True,
                    "api_url": "http://192.168.9.170:8766",
                },
                "map": {"enabled": False},
                "radar": {"enabled": True},
            }
        )

    with pytest.raises(ValidationError, match="forge.enabled"):
        ApplicationConfig.model_validate(
            {
                "operator": {"callsign": "KI5VNB", "home_grid": "EM79xm"},
                "forge": {"enabled": False},
                "map": {"enabled": True},
                "radar": {"enabled": True},
            }
        )


def test_radar_defaults_off_for_existing_configuration() -> None:
    config = ApplicationConfig.model_validate(
        {
            "operator": {"callsign": "KI5VNB", "home_grid": "EM79xm"},
            "hardware": {"mock": True},
        }
    )

    assert config.radar.enabled is False
    assert config.radar.opacity == 0.55
    assert config.radar.stale_after_s == 900.0
    assert config.radar.hide_after_s == 1_800.0


def test_runtime_composes_separate_map_and_radar_services(tmp_path: Path) -> None:
    config = ApplicationConfig.model_validate(base_payload(tmp_path))

    runtime = ApplicationRuntime.from_config(config)

    assert runtime.live_map is not None
    assert runtime.live_radar is not None
    assert runtime.live_map is not runtime.live_radar
    assert runtime.latest_live_radar_state is runtime.live_radar.latest_state
    assert runtime.latest_live_radar_state.detail == "RADAR WAITING FOR MAP"
