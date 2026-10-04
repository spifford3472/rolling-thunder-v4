"""Tests for the independent Forge spot-service configuration."""

from pathlib import Path

import pytest

from rolling_thunder.forge_config import (
    ForgeApplicationConfig,
    ForgeConfigurationFileError,
    ForgeConfigurationParseError,
    ForgeConfigurationValidationError,
    ForgeLogLevel,
    load_forge_config,
)


def write_config(tmp_path: Path, content: str) -> Path:
    """Write one temporary Forge YAML configuration file."""
    path = tmp_path / "forge-spots.yaml"
    path.write_text(content, encoding="utf-8")
    return path


def test_direct_configuration_uses_loopback_safe_defaults() -> None:
    config = ForgeApplicationConfig()

    assert config.server.bind_host == "127.0.0.1"
    assert config.server.bind_port == 8765
    assert config.storage.database_path == Path("data/forge-spots.db")
    assert config.aggregation.refresh_interval_s == 60.0
    assert config.aggregation.refresh_on_start is True
    assert config.pota.enabled is True
    assert str(config.pota.base_url).rstrip("/") == "https://api.pota.app"
    assert config.pota.request_timeout_s == 5.0

    assert config.dxspider.enabled is False
    assert config.dxspider.host == "cluster.example.invalid"
    assert config.dxspider.port == 7300
    assert config.dxspider.login_callsign == "N0CALL"
    assert config.dxspider.connect_timeout_s == 5.0
    assert config.dxspider.read_timeout_s == 5.0
    assert config.dxspider.max_response_bytes == 262_144
    assert config.dxspider.max_spots == 250
    assert config.dxspider.max_spot_age_s == 3_600.0

    assert config.dxsummit.enabled is False
    assert config.dxsummit.host == "irc.radiochat.org"
    assert config.dxsummit.port == 6667
    assert config.dxsummit.channel == "#CQDX"
    assert config.dxsummit.nickname == "N0CALL"
    assert config.dxsummit.connect_timeout_s == 15.0
    assert config.dxsummit.read_timeout_s == 5.0
    assert config.dxsummit.inactivity_timeout_s == 600.0
    assert config.dxsummit.reconnect_initial_s == 5.0
    assert config.dxsummit.reconnect_max_s == 300.0
    assert config.dxsummit.stable_connection_s == 300.0
    assert config.dxsummit.max_spots == 500
    assert config.dxsummit.max_spot_age_s == 3_600.0

    assert config.qrz.enabled is False
    assert config.qrz.request_timeout_s == 5.0
    assert config.qrz.minimum_request_interval_s == 1.0
    assert config.qrz.max_lookups_per_refresh == 25
    assert config.qrz.positive_ttl_s == 86_400.0
    assert config.qrz.negative_ttl_s == 3_600.0
    assert config.qrz.max_cache_entries == 2_000
    assert config.logging_level is ForgeLogLevel.INFO


def test_valid_yaml_loads_and_resolves_database_path(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        """
server:
  bind_host: 127.0.0.1
  bind_port: 9010
storage:
  database_path: state/forge.db
aggregation:
  refresh_interval_s: 45
  refresh_on_start: false
pota:
  enabled: true
  base_url: https://pota.example.invalid/root
  request_timeout_s: 4.5
dxspider:
  enabled: true
  host: " cluster.example.invalid "
  port: 7301
  login_callsign: " ki5vnb "
  connect_timeout_s: 3
  read_timeout_s: 7
  max_response_bytes: 131072
  max_spots: 125
  max_spot_age_s: 1800
dxsummit:
  enabled: true
  host: " irc.radiochat.org "
  port: 6667
  channel: " #CQDX "
  nickname: " ki5vnb "
  connect_timeout_s: 12
  read_timeout_s: 4
  inactivity_timeout_s: 720
  reconnect_initial_s: 7
  reconnect_max_s: 240
  stable_connection_s: 180
  max_spots: 600
  max_spot_age_s: 2700
qrz:
  enabled: true
  request_timeout_s: 6
  minimum_request_interval_s: 1.5
  max_lookups_per_refresh: 12
  positive_ttl_s: 43200
  negative_ttl_s: 900
  max_cache_entries: 500
logging_level: warning
""",
    )

    config = load_forge_config(path)

    assert config.server.bind_host == "127.0.0.1"
    assert config.server.bind_port == 9010
    assert config.storage.database_path == (tmp_path / "state/forge.db").resolve()
    assert config.aggregation.refresh_interval_s == 45
    assert config.aggregation.refresh_on_start is False
    assert str(config.pota.base_url).rstrip("/") == (
        "https://pota.example.invalid/root"
    )
    assert config.pota.request_timeout_s == 4.5

    assert config.dxspider.enabled is True
    assert config.dxspider.host == "cluster.example.invalid"
    assert config.dxspider.port == 7301
    assert config.dxspider.login_callsign == "KI5VNB"
    assert config.dxspider.connect_timeout_s == 3
    assert config.dxspider.read_timeout_s == 7
    assert config.dxspider.max_response_bytes == 131_072
    assert config.dxspider.max_spots == 125
    assert config.dxspider.max_spot_age_s == 1_800

    assert config.dxsummit.enabled is True
    assert config.dxsummit.host == "irc.radiochat.org"
    assert config.dxsummit.port == 6667
    assert config.dxsummit.channel == "#CQDX"
    assert config.dxsummit.nickname == "KI5VNB"
    assert config.dxsummit.connect_timeout_s == 12
    assert config.dxsummit.read_timeout_s == 4
    assert config.dxsummit.inactivity_timeout_s == 720
    assert config.dxsummit.reconnect_initial_s == 7
    assert config.dxsummit.reconnect_max_s == 240
    assert config.dxsummit.stable_connection_s == 180
    assert config.dxsummit.max_spots == 600
    assert config.dxsummit.max_spot_age_s == 2_700

    assert config.qrz.enabled is True
    assert config.qrz.request_timeout_s == 6
    assert config.qrz.minimum_request_interval_s == 1.5
    assert config.qrz.max_lookups_per_refresh == 12
    assert config.qrz.positive_ttl_s == 43_200
    assert config.qrz.negative_ttl_s == 900
    assert config.qrz.max_cache_entries == 500
    assert config.logging_level is ForgeLogLevel.WARNING


@pytest.mark.parametrize(
    ("content", "expected_path"),
    [
        ("server:\n  bind_host: '   '\n", "server.bind_host"),
        ("server:\n  bind_port: 0\n", "server.bind_port"),
        ("server:\n  bind_port: 70000\n", "server.bind_port"),
        ("storage:\n  database_path: ''\n", "storage.database_path"),
        ("storage:\n  database_path: .\n", "storage.database_path"),
        (
            "aggregation:\n  refresh_interval_s: 0\n",
            "aggregation.refresh_interval_s",
        ),
        ("pota:\n  base_url: not-a-url\n", "pota.base_url"),
        ("pota:\n  request_timeout_s: 0\n", "pota.request_timeout_s"),
        ("dxspider:\n  host: '   '\n", "dxspider.host"),
        ("dxspider:\n  port: 0\n", "dxspider.port"),
        ("dxspider:\n  port: 70000\n", "dxspider.port"),
        (
            "dxspider:\n  login_callsign: invalid\n",
            "dxspider.login_callsign",
        ),
        (
            "dxspider:\n  connect_timeout_s: 0\n",
            "dxspider.connect_timeout_s",
        ),
        (
            "dxspider:\n  read_timeout_s: 61\n",
            "dxspider.read_timeout_s",
        ),
        (
            "dxspider:\n  max_response_bytes: 1024\n",
            "dxspider.max_response_bytes",
        ),
        ("dxspider:\n  max_spots: 0\n", "dxspider.max_spots"),
        (
            "dxspider:\n  max_spot_age_s: 0\n",
            "dxspider.max_spot_age_s",
        ),
        ("dxsummit:\n  host: '   '\n", "dxsummit.host"),
        ("dxsummit:\n  port: 0\n", "dxsummit.port"),
        ("dxsummit:\n  channel: '   '\n", "dxsummit.channel"),
        ("dxsummit:\n  nickname: invalid\n", "dxsummit.nickname"),
        ("dxsummit:\n  inactivity_timeout_s: 30\n", "dxsummit.inactivity_timeout_s"),
        ("dxsummit:\n  reconnect_initial_s: 0\n", "dxsummit.reconnect_initial_s"),
        (
            "dxsummit:\n  reconnect_initial_s: 30\n  reconnect_max_s: 10\n",
            "dxsummit",
        ),
        ("dxsummit:\n  max_spots: 0\n", "dxsummit.max_spots"),
        ("dxsummit:\n  max_spot_age_s: 0\n", "dxsummit.max_spot_age_s"),
        ("qrz:\n  request_timeout_s: 0\n", "qrz.request_timeout_s"),
        (
            "qrz:\n  minimum_request_interval_s: -1\n",
            "qrz.minimum_request_interval_s",
        ),
        (
            "qrz:\n  max_lookups_per_refresh: 0\n",
            "qrz.max_lookups_per_refresh",
        ),
        ("qrz:\n  positive_ttl_s: 0\n", "qrz.positive_ttl_s"),
        ("qrz:\n  negative_ttl_s: 0\n", "qrz.negative_ttl_s"),
        ("qrz:\n  max_cache_entries: 0\n", "qrz.max_cache_entries"),
        ("logging_level: verbose\n", "logging_level"),
        ("unknown_key: true\n", "unknown_key"),
    ],
)
def test_invalid_configuration_is_actionable(
    tmp_path: Path,
    content: str,
    expected_path: str,
) -> None:
    path = write_config(tmp_path, content)

    with pytest.raises(
        ForgeConfigurationValidationError,
        match=expected_path.replace(".", r"\."),
    ):
        load_forge_config(path)


def test_absolute_database_path_is_preserved(tmp_path: Path) -> None:
    absolute = tmp_path / "forge.db"
    path = write_config(
        tmp_path,
        f"storage:\n  database_path: {absolute}\n",
    )

    config = load_forge_config(path)

    assert config.storage.database_path == absolute


def test_missing_file_has_recovery_guidance(tmp_path: Path) -> None:
    path = tmp_path / "missing.yaml"

    with pytest.raises(ForgeConfigurationFileError) as error_info:
        load_forge_config(path)

    message = str(error_info.value)
    assert str(path) in message
    assert "forge-spots.example.yaml" in message


def test_malformed_yaml_reports_source_location(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        "server:\n  bind_port: 8765\n    bind_host: 127.0.0.1\n",
    )

    with pytest.raises(ForgeConfigurationParseError) as error_info:
        load_forge_config(path)

    message = str(error_info.value)
    assert "line" in message
    assert "column" in message


@pytest.mark.parametrize("content", ["", "[]", "- server"])
def test_yaml_root_must_be_mapping(tmp_path: Path, content: str) -> None:
    path = write_config(tmp_path, content)

    with pytest.raises(
        ForgeConfigurationParseError,
        match="mapping at the document root",
    ):
        load_forge_config(path)
