"""Tests for typed MeshCore USB configuration."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from rolling_thunder.config import ApplicationConfig


def base_config(meshcore: dict[str, object]) -> ApplicationConfig:
    return ApplicationConfig.model_validate(
        {
            "operator": {"callsign": "KI5VNB", "home_grid": "EM79xm"},
            "hardware": {"mock": True},
            "meshcore": meshcore,
        }
    )


def test_meshcore_defaults_are_receive_overlay_defaults() -> None:
    config = base_config({})

    assert config.meshcore.enabled is False
    assert config.meshcore.device is None
    assert config.meshcore.baud_rate == 115_200
    assert config.meshcore.command_timeout_s == 2.0
    assert config.meshcore.channels == ("#hamradio", "#skywarn", "#traffic")
    assert config.meshcore.message_overlay_seconds == 20.0


def test_enabled_meshcore_accepts_stable_usb_by_id_path() -> None:
    config = base_config(
        {
            "enabled": True,
            "device": "/dev/serial/by-id/usb-MeshCore_companion",
            "channels": [" #HAMRADIO ", "#skywarn"],
        }
    )

    assert config.meshcore.device == Path(
        "/dev/serial/by-id/usb-MeshCore_companion"
    )
    assert config.meshcore.channels == ("#hamradio", "#skywarn")


def test_enabled_meshcore_requires_absolute_device() -> None:
    with pytest.raises(ValidationError, match="absolute serial-device path"):
        base_config({"enabled": True, "device": "ttyACM0"})


def test_meshcore_rejects_duplicate_or_non_hashtag_channels() -> None:
    with pytest.raises(ValidationError, match="duplicate MeshCore channel"):
        base_config({"channels": ["#traffic", "#TRAFFIC"]})

    with pytest.raises(ValidationError, match="must be nonblank hashtags"):
        base_config({"channels": ["traffic"]})
