"""Tests for typed POTA spot YAML configuration."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from rolling_thunder.config import (
    ApplicationConfig,
    ConfigurationValidationError,
    PotaSpotsConfig,
    load_config,
)


def minimal_config() -> dict[str, object]:
    return {
        "operator": {"callsign": "KI5VNB", "home_grid": "EM79xm"},
        "hardware": {"mock": True},
    }


def write_config(path: Path, pota_yaml: str = "") -> None:
    path.write_text(
        "operator:\n"
        "  callsign: KI5VNB\n"
        "  home_grid: EM79xm\n"
        "hardware:\n"
        "  mock: true\n"
        f"{pota_yaml}",
        encoding="utf-8",
    )


def test_pota_spots_are_disabled_by_default() -> None:
    config = ApplicationConfig.model_validate(minimal_config())

    assert config.pota_spots.enabled is False
    assert str(config.pota_spots.base_url) == "https://api.pota.app/"
    assert config.pota_spots.request_timeout_s == 5.0
    assert config.pota_spots.refresh_interval_s == 60.0
    assert config.pota_spots.refresh_on_start is True


def test_load_config_parses_pota_spot_settings(tmp_path: Path) -> None:
    config_path = tmp_path / "rolling-thunder.yaml"
    write_config(
        config_path,
        "pota_spots:\n"
        "  enabled: true\n"
        "  base_url: https://spots.example.test/api\n"
        "  request_timeout_s: 7.5\n"
        "  refresh_interval_s: 90.0\n"
        "  refresh_on_start: false\n",
    )

    config = load_config(config_path)

    assert config.pota_spots.enabled is True
    assert str(config.pota_spots.base_url) == "https://spots.example.test/api"
    assert config.pota_spots.request_timeout_s == 7.5
    assert config.pota_spots.refresh_interval_s == 90.0
    assert config.pota_spots.refresh_on_start is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("request_timeout_s", 0.0),
        ("request_timeout_s", 61.0),
        ("refresh_interval_s", 0.0),
        ("refresh_interval_s", 3_601.0),
    ],
)
def test_pota_spot_numeric_bounds_are_validated(field: str, value: float) -> None:
    with pytest.raises(ValidationError):
        PotaSpotsConfig.model_validate({field: value})


def test_pota_spot_settings_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        PotaSpotsConfig.model_validate({"enabled": True, "token": "secret"})


def test_yaml_validation_reports_pota_field_path(tmp_path: Path) -> None:
    config_path = tmp_path / "rolling-thunder.yaml"
    write_config(
        config_path,
        "pota_spots:\n"
        "  enabled: true\n"
        "  refresh_interval_s: 0\n",
    )

    with pytest.raises(
        ConfigurationValidationError,
        match=r"pota_spots\.refresh_interval_s",
    ):
        load_config(config_path)
