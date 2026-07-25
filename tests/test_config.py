"""Tests for typed Rolling Thunder YAML configuration."""

from pathlib import Path

import pytest

from rolling_thunder.config import (
    ApplicationConfig,
    ConfigurationFileError,
    ConfigurationParseError,
    ConfigurationValidationError,
    ContactBackupConfig,
    ForgeConfig,
    HardwareConfig,
    OperatorConfig,
    StorageConfig,
    load_config,
    resolve_contact_backup_directory,
)


def write_config(tmp_path: Path, content: str) -> Path:
    """Write a temporary YAML configuration file."""
    path = tmp_path / "rolling-thunder.yaml"
    path.write_text(content, encoding="utf-8")
    return path


def test_valid_mock_configuration_loads_typed_models(tmp_path: Path) -> None:
    """A valid mock-mode YAML file should produce typed nested models."""
    path = write_config(
        tmp_path,
        """
operator:
  callsign: ki5vnb
  home_grid: em79XM
hardware:
  mock: true
forge:
  api_url: https://forge.example.invalid/api
storage:
  database_path: data/test.db
""",
    )

    config = load_config(path)

    assert isinstance(config, ApplicationConfig)
    assert isinstance(config.operator, OperatorConfig)
    assert isinstance(config.hardware, HardwareConfig)
    assert isinstance(config.forge, ForgeConfig)
    assert isinstance(config.storage, StorageConfig)
    assert config.operator.callsign == "KI5VNB"
    assert config.operator.home_grid == "EM79xm"
    assert config.hardware.mock is True
    assert config.forge.api_url is not None
    assert str(config.storage.database_path) == "data/test.db"


def test_models_can_be_constructed_directly() -> None:
    """Tests and application code should not require filesystem loading."""
    config = ApplicationConfig(
        operator=OperatorConfig(callsign="KI5VNB", home_grid="EM79xm")
    )

    assert config.hardware.mock is True
    assert config.forge.api_url is None
    assert config.storage.database_path == Path("data/rolling-thunder.db")


@pytest.mark.parametrize(
    ("callsign", "expected_message"),
    [
        ("", "operator.callsign"),
        ("NOT-A-CALL", "operator.callsign"),
        ("123456789", "operator.callsign"),
    ],
)
def test_invalid_callsign_is_actionable(
    tmp_path: Path,
    callsign: str,
    expected_message: str,
) -> None:
    """Invalid callsigns should identify the exact configuration path."""
    path = write_config(
        tmp_path,
        f"""
operator:
  callsign: {callsign!r}
  home_grid: EM79xm
""",
    )

    with pytest.raises(ConfigurationValidationError, match=expected_message):
        load_config(path)


@pytest.mark.parametrize("grid", ["EM7", "ZZ99", "EM79xyz", "EM79xm123"])
def test_invalid_home_grid_is_actionable(tmp_path: Path, grid: str) -> None:
    """Invalid grids should identify operator.home_grid."""
    path = write_config(
        tmp_path,
        f"""
operator:
  callsign: KI5VNB
  home_grid: {grid}
""",
    )

    with pytest.raises(ConfigurationValidationError, match=r"operator\.home_grid"):
        load_config(path)


def test_invalid_forge_url_is_actionable(tmp_path: Path) -> None:
    """Invalid Forge URLs should identify forge.api_url."""
    path = write_config(
        tmp_path,
        """
operator:
  callsign: KI5VNB
  home_grid: EM79xm
forge:
  api_url: not-a-url
""",
    )

    with pytest.raises(ConfigurationValidationError, match=r"forge\.api_url"):
        load_config(path)


def test_missing_configuration_file_has_recovery_guidance(tmp_path: Path) -> None:
    """Missing files should explain how to create a local configuration."""
    path = tmp_path / "missing.yaml"

    with pytest.raises(ConfigurationFileError) as error_info:
        load_config(path)

    message = str(error_info.value)
    assert str(path) in message
    assert "rolling-thunder.example.yaml" in message
    assert "rolling-thunder.yaml" in message


def test_malformed_yaml_reports_line_and_column(tmp_path: Path) -> None:
    """Malformed YAML should include a useful source location."""
    path = write_config(
        tmp_path,
        """
operator:
  callsign: KI5VNB
    home_grid: EM79xm
""",
    )

    with pytest.raises(ConfigurationParseError) as error_info:
        load_config(path)

    message = str(error_info.value)
    assert "line" in message
    assert "column" in message


@pytest.mark.parametrize("content", ["", "[]", "- operator"])
def test_yaml_root_must_be_a_mapping(tmp_path: Path, content: str) -> None:
    """Empty or non-mapping YAML documents should be rejected."""
    path = write_config(tmp_path, content)

    with pytest.raises(
        ConfigurationParseError,
        match="mapping at the document root",
    ):
        load_config(path)


def test_unknown_configuration_key_is_rejected(tmp_path: Path) -> None:
    """Misspelled and undocumented keys must not be silently ignored."""
    path = write_config(
        tmp_path,
        """
operator:
  callsign: KI5VNB
  home_grid: EM79xm
hardware:
  mock: true
  radio_devise: /dev/ttyUSB0
""",
    )

    with pytest.raises(
        ConfigurationValidationError,
        match=r"hardware\.radio_devise",
    ):
        load_config(path)


def test_real_hardware_mode_requires_device_paths(tmp_path: Path) -> None:
    """Real hardware mode should require both configured devices."""
    path = write_config(
        tmp_path,
        """
operator:
  callsign: KI5VNB
  home_grid: EM79xm
hardware:
  mock: false
""",
    )

    with pytest.raises(ConfigurationValidationError) as error_info:
        load_config(path)

    message = str(error_info.value)
    assert "hardware.radio_device" in message
    assert "hardware.gps_device" in message
    assert "hardware.mock is false" in message


def test_real_hardware_mode_accepts_device_paths(tmp_path: Path) -> None:
    """Configured device paths should permit real hardware mode."""
    path = write_config(
        tmp_path,
        """
operator:
  callsign: KI5VNB
  home_grid: EM79xm
hardware:
  mock: false
  radio_device: /dev/ttyUSB0
  gps_device: /dev/ttyACM0
""",
    )

    config = load_config(path)

    assert config.hardware.mock is False
    assert config.hardware.radio_device == Path("/dev/ttyUSB0")
    assert config.hardware.gps_device == Path("/dev/ttyACM0")


def test_contact_backup_defaults_are_typed() -> None:
    """Backup settings should have safe disabled defaults."""
    config = ApplicationConfig(
        operator=OperatorConfig(callsign="KI5VNB", home_grid="EM79xm")
    )

    assert isinstance(
        config.storage.contact_backups,
        ContactBackupConfig,
    )
    assert config.storage.contact_backups.enabled is False
    assert config.storage.contact_backups.directory == Path(
        "backups/contacts"
    )
    assert config.storage.contact_backups.retention_count == 10


def test_contact_backup_yaml_overrides_load(tmp_path: Path) -> None:
    """Explicit backup settings should load as typed values."""
    path = write_config(
        tmp_path,
        """
operator:
  callsign: KI5VNB
  home_grid: EM79xm
storage:
  contact_backups:
    enabled: true
    directory: local/contact-backups
    retention_count: 25
""",
    )

    config = load_config(path)

    assert config.storage.contact_backups.enabled is True
    assert config.storage.contact_backups.directory == Path(
        "local/contact-backups"
    )
    assert config.storage.contact_backups.retention_count == 25


@pytest.mark.parametrize("retention_count", [0, -1])
def test_contact_backup_rejects_non_positive_retention(
    tmp_path: Path,
    retention_count: int,
) -> None:
    """Retention must identify the exact invalid configuration path."""
    path = write_config(
        tmp_path,
        f"""
operator:
  callsign: KI5VNB
  home_grid: EM79xm
storage:
  contact_backups:
    retention_count: {retention_count}
""",
    )

    with pytest.raises(
        ConfigurationValidationError,
        match=r"storage\.contact_backups\.retention_count",
    ):
        load_config(path)


@pytest.mark.parametrize("directory", ["''", '""', "'.'"])
def test_contact_backup_rejects_invalid_directory(
    tmp_path: Path,
    directory: str,
) -> None:
    """Empty and current-directory backup paths should be rejected."""
    path = write_config(
        tmp_path,
        f"""
operator:
  callsign: KI5VNB
  home_grid: EM79xm
storage:
  contact_backups:
    directory: {directory}
""",
    )

    with pytest.raises(
        ConfigurationValidationError,
        match=r"storage\.contact_backups\.directory",
    ):
        load_config(path)


def test_contact_backup_directory_resolves_relative_to_config(
    tmp_path: Path,
) -> None:
    """Relative machine paths should be anchored beside the YAML file."""
    config_directory = tmp_path / "machine-config"
    config_directory.mkdir()
    config_path = write_config(
        config_directory,
        """
operator:
  callsign: KI5VNB
  home_grid: EM79xm
storage:
  contact_backups:
    directory: ../persistent/contact-backups
""",
    )
    config = load_config(config_path)

    resolved = resolve_contact_backup_directory(
        config,
        config_path,
    )

    assert resolved == (
        tmp_path / "persistent" / "contact-backups"
    ).resolve()


def test_absolute_contact_backup_directory_is_preserved(
    tmp_path: Path,
) -> None:
    """Absolute backup paths should not be rebased."""
    absolute_directory = tmp_path / "absolute-backups"
    config_path = write_config(
        tmp_path,
        f"""
operator:
  callsign: KI5VNB
  home_grid: EM79xm
storage:
  contact_backups:
    directory: {absolute_directory}
""",
    )
    config = load_config(config_path)

    assert resolve_contact_backup_directory(
        config,
        config_path,
    ) == absolute_directory
