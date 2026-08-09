"""Focused tests for retained Forge weather configuration."""

import pytest
from pydantic import ValidationError

from rolling_thunder.forge_config import ForgeApplicationConfig


def test_weather_defaults_are_bounded_and_disabled() -> None:
    weather = ForgeApplicationConfig().weather

    assert weather.enabled is False
    assert str(weather.endpoint) == "https://api.open-meteo.com/v1/forecast"
    assert weather.request_timeout_s == 5.0
    assert weather.check_interval_s == 60.0
    assert weather.max_forecast_age_s == 1_800.0
    assert weather.movement_refresh_km == 10.0
    assert weather.refresh_on_start is True


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("request_timeout_s", 0),
        ("check_interval_s", 0),
        ("max_forecast_age_s", 0),
        ("movement_refresh_km", 0),
    ],
)
def test_weather_numeric_bounds_are_enforced(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        ForgeApplicationConfig.model_validate({"weather": {field: value}})


def test_weather_endpoint_must_be_http_url() -> None:
    with pytest.raises(ValidationError):
        ForgeApplicationConfig.model_validate(
            {"weather": {"endpoint": "not-a-url"}}
        )
