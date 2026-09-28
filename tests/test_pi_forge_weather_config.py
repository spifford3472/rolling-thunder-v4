"""Tests for opt-in Pi retained Forge weather configuration."""

import pytest
from pydantic import ValidationError

from rolling_thunder.config import ApplicationConfig


def base_payload() -> dict[str, object]:
    return {"operator": {"callsign": "KI5VNB", "home_grid": "EM79xm"}}


def test_retained_weather_defaults_disabled_with_15_minute_polling_defaults() -> None:
    config = ApplicationConfig.model_validate(base_payload())
    assert config.forge.weather.enabled is False
    assert config.forge.weather.refresh_interval_s == 900.0
    assert config.forge.weather.refresh_on_start is True
    assert config.forge.weather.stale_after_s == 1_800.0


def test_retained_weather_requires_parent_forge_enablement() -> None:
    payload = base_payload()
    payload["forge"] = {
        "enabled": False,
        "weather": {"enabled": True},
    }
    with pytest.raises(ValidationError, match="forge.enabled"):
        ApplicationConfig.model_validate(payload)


def test_retained_weather_accepts_explicit_enabled_settings() -> None:
    payload = base_payload()
    payload["forge"] = {
        "enabled": True,
        "api_url": "http://forge.example.invalid:8766",
        "weather": {
            "enabled": True,
            "refresh_interval_s": 600.0,
            "refresh_on_start": False,
            "stale_after_s": 2_400.0,
        },
    }
    config = ApplicationConfig.model_validate(payload)
    assert config.forge.weather.enabled is True
    assert config.forge.weather.refresh_interval_s == 600.0
    assert config.forge.weather.refresh_on_start is False
    assert config.forge.weather.stale_after_s == 2_400.0
