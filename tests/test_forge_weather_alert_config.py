"""Focused configuration tests for optional Forge NWS weather alerts."""

import pytest
from pydantic import ValidationError

from rolling_thunder.forge_config import ForgeApplicationConfig


def test_weather_alert_defaults_are_bounded_and_disabled() -> None:
    alerts = ForgeApplicationConfig().weather_alerts

    assert alerts.enabled is False
    assert str(alerts.endpoint) == "https://api.weather.gov/alerts/active"
    assert alerts.user_agent.startswith("RollingThunder-v4/")
    assert alerts.request_timeout_s == 5.0
    assert alerts.check_interval_s == 30.0
    assert alerts.location_max_age_s == 120.0
    assert alerts.refresh_on_start is True


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("request_timeout_s", 0),
        ("check_interval_s", 29.9),
        ("location_max_age_s", 0),
    ],
)
def test_weather_alert_numeric_bounds_are_enforced(
    field: str,
    value: object,
) -> None:
    with pytest.raises(ValidationError):
        ForgeApplicationConfig.model_validate(
            {"weather_alerts": {field: value}}
        )


def test_weather_alert_user_agent_is_required_and_trimmed() -> None:
    with pytest.raises(ValidationError):
        ForgeApplicationConfig.model_validate(
            {"weather_alerts": {"user_agent": "   "}}
        )

    config = ForgeApplicationConfig.model_validate(
        {
            "weather_alerts": {
                "user_agent": "  RollingThunder-Test/1.0  "
            }
        }
    )

    assert config.weather_alerts.user_agent == "RollingThunder-Test/1.0"


def test_weather_alert_endpoint_must_be_http_url() -> None:
    with pytest.raises(ValidationError):
        ForgeApplicationConfig.model_validate(
            {"weather_alerts": {"endpoint": "not-a-url"}}
        )
