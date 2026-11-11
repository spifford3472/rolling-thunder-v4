"""Opt-in MeshCore configuration and runtime composition regression tests."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from rolling_thunder.application_runtime import ApplicationRuntime
from rolling_thunder.config import ApplicationConfig


def _config(tmp_path: Path, meshcore: dict[str, object]) -> ApplicationConfig:
    return ApplicationConfig.model_validate(
        {
            "operator": {"callsign": "KI5VNB", "home_grid": "EM79xm"},
            "hardware": {"mock": True},
            "storage": {"database_path": str(tmp_path / "rolling.db")},
            "meshcore_passive": meshcore,
        }
    )


def test_default_disabled_never_builds_collector(tmp_path: Path) -> None:
    config = _config(tmp_path, {"enabled": False})
    runtime = ApplicationRuntime.from_config(config)
    assert runtime.meshcore_passive is None
    assert not (tmp_path / "meshcore-observations.db").exists()


def test_enabling_requires_physical_usb_path(tmp_path: Path) -> None:
    for invalid in (None, "/dev/ttyUSB0", "/dev/serial/by-id/CP2102_0001"):
        with pytest.raises(ValidationError, match="meshcore_passive"):
            _config(tmp_path, {"enabled": True, "device": invalid})


def test_opt_in_creates_isolated_storage_without_opening_device(tmp_path: Path) -> None:
    path = "/dev/serial/by-path/meshcore-on-anvilmobile"
    config = _config(tmp_path, {"enabled": True, "device": path})
    runtime = ApplicationRuntime.from_config(config)
    assert runtime.meshcore_passive is not None
    assert not runtime.meshcore_passive.status().running
    assert not runtime.meshcore_passive.status().device_connected
    assert (tmp_path / "meshcore-observations.db").exists()
