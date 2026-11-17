"""Regression tests for the removed MeshCore runtime/configuration boundary."""

from importlib.util import find_spec
from pathlib import Path

import pytest
from pydantic import ValidationError

from rolling_thunder.application_runtime import ApplicationRuntime
from rolling_thunder.config import ApplicationConfig


def _config(tmp_path: Path, *, legacy_meshcore: dict[str, object] | None = None) -> ApplicationConfig:
    payload: dict[str, object] = {
        "operator": {"callsign": "KI5VNB", "home_grid": "EM79xm"},
        "hardware": {"mock": True},
        "storage": {"database_path": str(tmp_path / "rolling.db")},
    }
    if legacy_meshcore is not None:
        payload["meshcore_passive"] = legacy_meshcore
    return ApplicationConfig.model_validate(payload)


def test_runtime_has_no_meshcore_gps_or_serial_integration(tmp_path: Path) -> None:
    runtime = ApplicationRuntime.from_config(_config(tmp_path))

    assert not hasattr(runtime, "meshcore_gps_publisher")
    assert not (tmp_path / "meshcore-observations.db").exists()
    assert find_spec("rolling_thunder.meshcore_serial_service") is None
    assert find_spec("rolling_thunder.meshcore_collector_main") is None
    assert find_spec("rolling_thunder.meshcore_message_broker") is None


def test_legacy_meshcore_configuration_is_warned_and_ignored(tmp_path: Path) -> None:
    with pytest.warns(UserWarning, match="meshcore_passive is retired"):
        config = _config(
            tmp_path,
            legacy_meshcore={
                "enabled": True,
                "device": "/dev/serial/by-path/old-meshcore-device",
            },
        )

    runtime = ApplicationRuntime.from_config(config)
    assert not hasattr(runtime, "meshcore_gps_publisher")
    assert not (tmp_path / "meshcore-observations.db").exists()


def test_runtime_starts_and_stops_without_meshcore_services(tmp_path: Path) -> None:
    runtime = ApplicationRuntime.from_config(_config(tmp_path))

    runtime.start()
    runtime.stop()

    assert not hasattr(runtime, "meshcore_gps_publisher")


def test_retired_section_shape_is_checked_without_weakening_other_validation(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValidationError, match="unsupported shape"):
        _config(tmp_path, legacy_meshcore={"enabled": False, "unexpected": True})

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ApplicationConfig.model_validate(
            {
                "operator": {"callsign": "KI5VNB", "home_grid": "EM79xm"},
                "unrelated_legacy_key": True,
            }
        )
