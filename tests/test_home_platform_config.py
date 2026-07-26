"""Tests for Home Station Platform configuration."""

from pathlib import Path

import pytest

from rolling_thunder.config import (
    ApplicationConfig,
    ConfigurationValidationError,
    HomePlatformConfig,
    OperatorConfig,
    load_config,
)


def write_config(tmp_path: Path, home_platform: str) -> Path:
    """Write a minimal configuration with one Home Platform section."""
    path = tmp_path / "rolling-thunder.yaml"
    path.write_text(
        f"""operator:
  callsign: KI5VNB
  home_grid: EM79xm
home_platform:
{home_platform}
""",
        encoding="utf-8",
    )
    return path


def test_home_platform_is_disabled_by_default() -> None:
    """Directly constructed application config should remain offline-safe."""
    config = ApplicationConfig(
        operator=OperatorConfig(callsign="KI5VNB", home_grid="EM79xm")
    )

    assert isinstance(config.home_platform, HomePlatformConfig)
    assert config.home_platform.enabled is False
    assert config.home_platform.base_url is None
    assert config.home_platform.request_timeout_s == 5.0
    assert config.home_platform.health_poll_interval_s == 30.0
    assert config.home_platform.contact_sync_interval_s == 30.0
    assert config.home_platform.contact_sync_batch_size == 25


def test_enabled_home_platform_loads_typed_settings(tmp_path: Path) -> None:
    """Enabled settings should load as one immutable typed section."""
    path = write_config(
        tmp_path,
        """  enabled: true
  base_url: https://forge.example.invalid/platform
  request_timeout_s: 4.5
  health_poll_interval_s: 15
  contact_sync_interval_s: 20
  contact_sync_batch_size: 50""",
    )

    config = load_config(path)

    assert config.home_platform.enabled is True
    assert str(config.home_platform.base_url) == "https://forge.example.invalid/platform"
    assert config.home_platform.request_timeout_s == 4.5
    assert config.home_platform.health_poll_interval_s == 15
    assert config.home_platform.contact_sync_interval_s == 20
    assert config.home_platform.contact_sync_batch_size == 50


def test_disabled_home_platform_does_not_require_base_url(tmp_path: Path) -> None:
    """Offline operation must remain valid without a remote endpoint."""
    path = write_config(tmp_path, "  enabled: false")

    config = load_config(path)

    assert config.home_platform.enabled is False
    assert config.home_platform.base_url is None


def test_enabled_home_platform_requires_base_url(tmp_path: Path) -> None:
    """An enabled service without an endpoint should be actionable."""
    path = write_config(tmp_path, "  enabled: true")

    with pytest.raises(ConfigurationValidationError) as error_info:
        load_config(path)

    message = str(error_info.value)
    assert "home_platform" in message
    assert "home_platform.base_url" in message
    assert "home_platform.enabled is true" in message


@pytest.mark.parametrize("base_url", ["forge.local", "ftp://forge.local", "/platform"])
def test_home_platform_base_url_must_be_http(tmp_path: Path, base_url: str) -> None:
    """Invalid endpoint schemes should identify the exact YAML path."""
    path = write_config(
        tmp_path,
        f"""  enabled: true
  base_url: {base_url}""",
    )

    with pytest.raises(
        ConfigurationValidationError,
        match=r"home_platform\.base_url",
    ):
        load_config(path)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("request_timeout_s", 0),
        ("request_timeout_s", 61),
        ("health_poll_interval_s", 0),
        ("health_poll_interval_s", 3601),
        ("contact_sync_interval_s", -1),
        ("contact_sync_interval_s", 3601),
        ("contact_sync_batch_size", 0),
        ("contact_sync_batch_size", 1001),
    ],
)
def test_home_platform_limits_are_actionable(
    tmp_path: Path,
    field: str,
    value: int,
) -> None:
    """Unsafe timeout, polling, and batch values should be rejected."""
    path = write_config(
        tmp_path,
        f"""  enabled: false
  {field}: {value}""",
    )

    with pytest.raises(
        ConfigurationValidationError,
        match=rf"home_platform\.{field}",
    ):
        load_config(path)


def test_unknown_home_platform_key_is_rejected(tmp_path: Path) -> None:
    """Misspelled platform keys must not be ignored silently."""
    path = write_config(
        tmp_path,
        "  enabled: false\n  request_timout_s: 5",
    )

    with pytest.raises(
        ConfigurationValidationError,
        match=r"home_platform\.request_timout_s",
    ):
        load_config(path)
