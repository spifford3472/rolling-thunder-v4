"""Static safety checks for the production Forge deployment assets."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
UNIT_PATH = ROOT / "deploy/systemd/rolling-thunder-forge-spots.service"
CONFIG_PATH = ROOT / "config/forge-spots.production.example.yaml"


def test_systemd_service_uses_dedicated_unprivileged_account() -> None:
    unit = UNIT_PATH.read_text(encoding="utf-8")

    assert "User=rollingthunder" in unit
    assert "Group=rollingthunder" in unit
    assert "User=root" not in unit
    assert "User=geoff" not in unit
    assert "NoNewPrivileges=true" in unit
    assert "CapabilityBoundingSet=" in unit


def test_systemd_service_uses_production_paths_and_persistent_state() -> None:
    unit = UNIT_PATH.read_text(encoding="utf-8")

    assert "WorkingDirectory=/opt/rolling-thunder-forge" in unit
    assert (
        "ExecStart=/opt/rolling-thunder-forge/.venv/bin/"
        "rolling-thunder-forge-spots "
        "--config /etc/rolling-thunder/forge-spots.yaml"
    ) in unit
    assert "StateDirectory=rolling-thunder" in unit
    assert "StateDirectoryMode=0750" in unit


def test_systemd_service_loads_secrets_only_from_external_environment_file() -> None:
    unit = UNIT_PATH.read_text(encoding="utf-8")

    assert "EnvironmentFile=-/etc/rolling-thunder/forge-spots.env" in unit
    assert "ROLLING_THUNDER_QRZ_USERNAME=" not in unit
    assert "ROLLING_THUNDER_QRZ_PASSWORD=" not in unit


def test_production_example_uses_radio_lan_only_and_checkpoint_8_port() -> None:
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))

    assert config["server"] == {
        "bind_host": "192.168.9.170",
        "bind_port": 8766,
    }
    assert config["storage"]["database_path"] == (
        "/var/lib/rolling-thunder/forge-spots.db"
    )
    assert config["server"]["bind_host"] != "0.0.0.0"


def test_production_example_contains_no_qrz_credentials() -> None:
    text = CONFIG_PATH.read_text(encoding="utf-8")
    config = yaml.safe_load(text)

    assert config["qrz"]["enabled"] is False
    assert "username:" not in text.lower()
    assert "password:" not in text.lower()
    assert "ROLLING_THUNDER_QRZ_USERNAME=..." in text
    assert "ROLLING_THUNDER_QRZ_PASSWORD=..." in text



CALLSIGN_UNIT_PATH = ROOT / "deploy/systemd/rolling-thunder-forge-callsign-info.service"
CALLSIGN_CONFIG_PATH = ROOT / "config/forge-callsign-info.example.yaml"


def test_callsign_info_service_uses_private_unprivileged_deployment() -> None:
    unit = CALLSIGN_UNIT_PATH.read_text(encoding="utf-8")
    config = yaml.safe_load(CALLSIGN_CONFIG_PATH.read_text(encoding="utf-8"))

    assert "User=rollingthunder" in unit
    assert "Group=rollingthunder" in unit
    assert "NoNewPrivileges=true" in unit
    assert "CapabilityBoundingSet=" in unit
    assert config["server"] == {
        "bind_host": "192.168.9.170",
        "bind_port": 8788,
    }


def test_callsign_info_service_keeps_credentials_out_of_yaml_and_unit() -> None:
    unit = CALLSIGN_UNIT_PATH.read_text(encoding="utf-8")
    text = CALLSIGN_CONFIG_PATH.read_text(encoding="utf-8")

    assert "EnvironmentFile=/etc/rolling-thunder/forge-callsign-info.env" in unit
    assert "ROLLING_THUNDER_QRZ_USERNAME=" not in unit
    assert "ROLLING_THUNDER_QRZ_PASSWORD=" not in unit
    assert "ROLLING_THUNDER_WAVELOG_V2_TOKEN=" not in unit
    assert "username:" not in text.lower()
    assert "password:" not in text.lower()
    assert "token:" not in text.lower()
