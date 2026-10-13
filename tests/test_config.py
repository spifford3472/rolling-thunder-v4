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
    HardwareAdapterMode,
    HardwareConfig,
    OperatorConfig,
    RepeaterConfig,
    StorageConfig,
    load_config,
    resolve_contact_backup_directory,
    resolve_database_path,
    resolve_repeater_source_path,
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
    assert config.hardware.effective_radio_mode is HardwareAdapterMode.MOCK
    assert config.hardware.effective_gps_mode is HardwareAdapterMode.MOCK
    assert config.forge.api_url is not None
    assert config.storage.database_path == (tmp_path / "data/test.db").resolve()


def test_models_can_be_constructed_directly() -> None:
    """Tests and application code should not require filesystem loading."""
    config = ApplicationConfig(
        operator=OperatorConfig(callsign="KI5VNB", home_grid="EM79xm")
    )

    assert config.hardware.mock is True
    assert config.hardware.effective_radio_mode is HardwareAdapterMode.MOCK
    assert config.hardware.effective_gps_mode is HardwareAdapterMode.MOCK
    assert config.hardware.gps_baud_rate == 9_600
    assert config.hardware.gps_timeout_s == 2.0
    assert config.forge.enabled is False
    assert config.forge.api_url is None
    assert config.forge.request_timeout_s == 5.0
    assert config.forge.refresh_interval_s == 60.0
    assert config.forge.refresh_on_start is True
    assert config.forge.max_response_bytes == 1_048_576
    assert config.storage.database_path == Path("data/rolling-thunder.db")
    assert config.antenna_reference.enabled is False
    assert config.antenna_reference.data_file is None


def test_antenna_reference_screen_requires_and_resolves_data_file(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        """
operator:
  callsign: KI5VNB
  home_grid: EM79xm
antenna_reference:
  enabled: true
  data_file: antenna-reference.yaml
""",
    )

    config = load_config(path)

    assert config.antenna_reference.enabled is True
    assert config.antenna_reference.data_file == tmp_path / "antenna-reference.yaml"


def test_antenna_reference_enabled_requires_data_file(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        """
operator:
  callsign: KI5VNB
  home_grid: EM79xm
antenna_reference:
  enabled: true
""",
    )

    with pytest.raises(ConfigurationValidationError, match="antenna_reference"):
        load_config(path)


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


def test_enabled_forge_requires_api_url(tmp_path: Path) -> None:
    """Enabled Pi-side Forge polling should require its service URL."""
    path = write_config(
        tmp_path,
        """
operator:
  callsign: KI5VNB
  home_grid: EM79xm
forge:
  enabled: true
""",
    )

    with pytest.raises(ConfigurationValidationError) as error_info:
        load_config(path)

    message = str(error_info.value)
    assert "forge" in message
    assert "api_url" in message


@pytest.mark.parametrize(
    ("setting", "value"),
    [
        ("request_timeout_s", 0),
        ("request_timeout_s", 61),
        ("refresh_interval_s", 0),
        ("refresh_interval_s", 3601),
        ("max_response_bytes", 1023),
        ("max_response_bytes", 16_777_217),
    ],
)
def test_invalid_forge_polling_bounds_are_actionable(
    tmp_path: Path,
    setting: str,
    value: object,
) -> None:
    """Unsafe Forge client bounds should identify the affected setting."""
    path = write_config(
        tmp_path,
        f"""
operator:
  callsign: KI5VNB
  home_grid: EM79xm
forge:
  {setting}: {value}
""",
    )

    with pytest.raises(
        ConfigurationValidationError,
        match=rf"forge\.{setting}",
    ):
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


def test_legacy_real_hardware_mode_requires_device_paths(tmp_path: Path) -> None:
    """Legacy global real mode should still require both configured devices."""
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
    assert "selected hardware mode is real" in message


def test_legacy_real_hardware_mode_accepts_device_paths(tmp_path: Path) -> None:
    """Configured device paths should permit legacy global real mode."""
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
    assert config.hardware.effective_radio_mode is HardwareAdapterMode.REAL
    assert config.hardware.effective_gps_mode is HardwareAdapterMode.REAL
    assert config.hardware.radio_device == Path("/dev/ttyUSB0")
    assert config.hardware.gps_device == Path("/dev/ttyACM0")


def test_real_gps_with_mock_radio_requires_only_gps_device(tmp_path: Path) -> None:
    """Per-device modes should support safe real-GPS and mock-radio testing."""
    path = write_config(
        tmp_path,
        """
operator:
  callsign: KI5VNB
  home_grid: EM79xm
hardware:
  mock: true
  radio_mode: mock
  gps_mode: real
  gps_device: /dev/serial/by-id/gps
  gps_baud_rate: 9600
  gps_timeout_s: 0.75
""",
    )

    config = load_config(path)

    assert config.hardware.effective_radio_mode is HardwareAdapterMode.MOCK
    assert config.hardware.effective_gps_mode is HardwareAdapterMode.REAL
    assert config.hardware.radio_device is None
    assert config.hardware.gps_device == Path("/dev/serial/by-id/gps")
    assert config.hardware.gps_baud_rate == 9_600
    assert config.hardware.gps_timeout_s == 0.75


def test_explicit_real_gps_mode_requires_gps_device(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        """
operator:
  callsign: KI5VNB
  home_grid: EM79xm
hardware:
  mock: true
  radio_mode: mock
  gps_mode: real
""",
    )

    with pytest.raises(ConfigurationValidationError) as error_info:
        load_config(path)

    message = str(error_info.value)
    assert "hardware.gps_device" in message
    assert "hardware.radio_device" not in message


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("radio_device", "''"),
        ("gps_device", "'.'"),
        ("radio_device", "ttyUSB0"),
        ("gps_device", "devices/gps"),
    ],
)
def test_hardware_device_paths_are_actionable(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    """Configured hardware paths should be non-empty absolute device paths."""
    path = write_config(
        tmp_path,
        f"""
operator:
  callsign: KI5VNB
  home_grid: EM79xm
hardware:
  mock: true
  {field}: {value}
""",
    )

    with pytest.raises(
        ConfigurationValidationError,
        match=rf"hardware\.{field}",
    ):
        load_config(path)


@pytest.mark.parametrize(
    ("field", "value"),
    [("gps_baud_rate", 0), ("gps_timeout_s", 0), ("gps_timeout_s", 61)],
)
def test_gps_serial_settings_are_bounded(
    tmp_path: Path,
    field: str,
    value: int,
) -> None:
    path = write_config(
        tmp_path,
        f"""
operator:
  callsign: KI5VNB
  home_grid: EM79xm
hardware:
  {field}: {value}
""",
    )

    with pytest.raises(
        ConfigurationValidationError,
        match=rf"hardware\.{field}",
    ):
        load_config(path)


@pytest.mark.parametrize("database_path", ["''", '""', "'.'"])
def test_database_path_rejects_empty_or_current_directory(
    tmp_path: Path,
    database_path: str,
) -> None:
    """The database setting must identify a database file."""
    path = write_config(
        tmp_path,
        f"""
operator:
  callsign: KI5VNB
  home_grid: EM79xm
storage:
  database_path: {database_path}
""",
    )

    with pytest.raises(
        ConfigurationValidationError,
        match=r"storage\.database_path",
    ):
        load_config(path)


def test_relative_database_path_resolves_relative_to_config(tmp_path: Path) -> None:
    """YAML-relative database paths should not depend on the launch directory."""
    config_directory = tmp_path / "machine-config"
    config_directory.mkdir()
    config_path = write_config(
        config_directory,
        """
operator:
  callsign: KI5VNB
  home_grid: EM79xm
storage:
  database_path: ../persistent/rolling-thunder.db
""",
    )

    config = load_config(config_path)

    assert config.storage.database_path == (
        tmp_path / "persistent/rolling-thunder.db"
    ).resolve()


def test_absolute_database_path_is_preserved(tmp_path: Path) -> None:
    """Absolute database paths should not be rebased."""
    absolute_database = tmp_path / "persistent/rolling-thunder.db"
    config_path = write_config(
        tmp_path,
        f"""
operator:
  callsign: KI5VNB
  home_grid: EM79xm
storage:
  database_path: {absolute_database}
""",
    )
    config = load_config(config_path)

    assert resolve_database_path(config, config_path) == absolute_database
    assert config.storage.database_path == absolute_database


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
    assert config.storage.contact_backups.directory == Path("backups/contacts")
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
    assert config.storage.contact_backups.directory == Path("local/contact-backups")
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

    assert resolved == (tmp_path / "persistent" / "contact-backups").resolve()


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


def test_completed_qso_delivery_defaults_disabled_and_resolves_outbox(
    tmp_path: Path,
) -> None:
    config_path = write_config(
        tmp_path,
        """
operator:
  callsign: KI5VNB
  home_grid: EM79xm
""",
    )
    config = load_config(config_path)

    assert config.ft8.completed_qso_delivery.enabled is False
    assert config.ft8.completed_qso_delivery.voacap.enabled is False
    assert config.ft8.completed_qso_delivery.psk_reporter.enabled is False
    assert config.ft8.completed_qso_delivery.database_path == (
        tmp_path / "data/completed-qso-outbox.db"
    ).resolve()


def test_completed_qso_delivery_requires_ft8_receiver_and_endpoint(
    tmp_path: Path,
) -> None:
    for ft8 in (
        """
  completed_qso_delivery:
    enabled: true
    voacap:
      enabled: true
      base_url: http://forge.test:8790
""",
        """
  enabled: true
  receive:
    decoder_executable: /unused/decode_ft8
  completed_qso_delivery:
    enabled: true
""",
        """
  enabled: true
  receive:
    decoder_executable: /unused/decode_ft8
  completed_qso_delivery:
    enabled: true
    voacap:
      enabled: true
""",
    ):
        path = write_config(
            tmp_path,
            f"""
operator:
  callsign: KI5VNB
  home_grid: EM79xm
ft8:
{ft8}
""",
        )
        with pytest.raises(ConfigurationValidationError):
            load_config(path)


def test_repeater_source_defaults_to_worktree_independent_user_data_path(
    tmp_path: Path,
) -> None:
    path = write_config(
        tmp_path,
        """
operator:
  callsign: KI5VNB
  home_grid: EM79xm
""",
    )

    config = load_config(path)

    assert isinstance(config.repeaters, RepeaterConfig)
    assert config.repeaters.source_path == Path(
        "~/.local/share/rolling-thunder/repeaters/6m_repeaters.csv"
    ).expanduser()


def test_relative_repeater_source_is_resolved_against_active_yaml(
    tmp_path: Path,
) -> None:
    path = write_config(
        tmp_path,
        """
operator:
  callsign: KI5VNB
  home_grid: EM79xm
repeaters:
  source_path: ../shared/repeaters/6m_repeaters.csv
""",
    )

    config = load_config(path)

    assert config.repeaters.source_path == (
        tmp_path / "../shared/repeaters/6m_repeaters.csv"
    ).resolve()
    assert resolve_repeater_source_path(config, path) == config.repeaters.source_path


def test_repeater_source_rejects_non_csv_path(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        """
operator:
  callsign: KI5VNB
  home_grid: EM79xm
repeaters:
  source_path: data/repeaters.txt
""",
    )

    with pytest.raises(
        ConfigurationValidationError,
        match=r"repeaters\.source_path",
    ):
        load_config(path)


def test_ft8_transmit_is_disabled_by_default() -> None:
    config = ApplicationConfig.model_validate(
        {
            "operator": {"callsign": "KI5VNB", "home_grid": "EM79xm"},
        }
    )

    assert config.ft8.enabled is False
    assert config.ft8.transmit.enabled is False
    assert config.ft8.transmit.encoder_executable is None


def test_ft8_transmit_requires_parent_ft8_enable() -> None:
    with pytest.raises(ValueError, match="ft8.transmit.enabled requires ft8.enabled"):
        ApplicationConfig.model_validate(
            {
                "operator": {"callsign": "KI5VNB", "home_grid": "EM79xm"},
                "ft8": {
                    "enabled": False,
                    "transmit": {
                        "enabled": True,
                        "encoder_executable": "/opt/ft8_lib/gen_ft8",
                    },
                },
            }
        )


def test_ft8_transmit_requires_absolute_encoder_when_enabled() -> None:
    with pytest.raises(ValueError, match="encoder_executable"):
        ApplicationConfig.model_validate(
            {
                "operator": {"callsign": "KI5VNB", "home_grid": "EM79xm"},
                "ft8": {
                    "enabled": True,
                    "receive": {
                        "decoder_executable": "/opt/ft8_lib/decode_ft8",
                    },
                    "transmit": {
                        "enabled": True,
                    },
                },
            }
        )

    with pytest.raises(ValueError, match="absolute path"):
        ApplicationConfig.model_validate(
            {
                "operator": {"callsign": "KI5VNB", "home_grid": "EM79xm"},
                "ft8": {
                    "enabled": True,
                    "receive": {
                        "decoder_executable": "/opt/ft8_lib/decode_ft8",
                    },
                    "transmit": {
                        "enabled": True,
                        "encoder_executable": "gen_ft8",
                    },
                },
            }
        )
