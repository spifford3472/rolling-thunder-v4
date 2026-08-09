"""Configuration safety tests for location-aware Pi weather alerts."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from rolling_thunder.config import (
    ApplicationConfig,
    ForgeConfig,
)


def test_alert_defaults_are_disabled_and_location_bounded() -> None:
    alerts = ForgeConfig().weather_alerts

    assert alerts.enabled is False
    assert alerts.refresh_interval_s == 30.0
    assert alerts.refresh_on_start is False
    assert alerts.location_publish_interval_s == 15.0


def test_alert_client_requires_parent_forge_enablement() -> None:
    with pytest.raises(
        ValidationError,
        match="forge.enabled",
    ):
        ForgeConfig.model_validate(
            {
                "weather_alerts": {
                    "enabled": True,
                }
            }
        )


def test_alert_location_publish_cannot_be_slower_than_alert_refresh() -> None:
    with pytest.raises(
        ValidationError,
        match="location_publish_interval_s",
    ):
        ForgeConfig.model_validate(
            {
                "enabled": True,
                "api_url": "http://forge.example.invalid",
                "weather_alerts": {
                    "enabled": True,
                    "refresh_interval_s": 10.0,
                    "location_publish_interval_s": 15.0,
                },
            }
        )


def application_payload(
    tmp_path: Path,
    *,
    gps_mode: str,
) -> dict[str, object]:
    return {
        "operator": {
            "callsign": "KI5VNB",
            "home_grid": "EM79xm",
        },
        "hardware": {
            "mock": False,
            "radio_mode": "mock",
            "gps_mode": gps_mode,
            "gps_device": (
                "/dev/fake-gps"
                if gps_mode == "real"
                else None
            ),
        },
        "forge": {
            "enabled": True,
            "api_url": "http://forge.example.invalid",
            "weather_alerts": {
                "enabled": True,
            },
        },
        "storage": {
            "database_path": str(
                tmp_path / "rolling-thunder.db"
            )
        },
    }


def test_alerts_reject_mock_gps(tmp_path: Path) -> None:
    with pytest.raises(
        ValidationError,
        match="hardware.gps_mode must be real",
    ):
        ApplicationConfig.model_validate(
            application_payload(
                tmp_path,
                gps_mode="mock",
            )
        )


def test_alerts_accept_explicit_real_gps(tmp_path: Path) -> None:
    config = ApplicationConfig.model_validate(
        application_payload(
            tmp_path,
            gps_mode="real",
        )
    )

    assert config.forge.weather_alerts.enabled is True
    assert config.hardware.effective_gps_mode.value == "real"


def test_enabled_alerts_reject_refresh_on_start() -> None:
    with pytest.raises(
        ValidationError,
        match="refresh_on_start",
    ):
        ForgeConfig.model_validate(
            {
                "enabled": True,
                "api_url": "http://forge.example.invalid",
                "weather_alerts": {
                    "enabled": True,
                    "refresh_on_start": True,
                },
            }
        )
