"""Tests for the Rolling Thunder application entry point."""

import json
from pathlib import Path

from pytest import CaptureFixture

from rolling_thunder.main import main
from rolling_thunder.storage import CURRENT_SCHEMA_VERSION


def write_config(tmp_path: Path, content: str) -> Path:
    """Write a temporary startup configuration."""
    path = tmp_path / "rolling-thunder.yaml"
    path.write_text(content, encoding="utf-8")
    return path


def test_main_starts_with_valid_configuration(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    """Valid configuration should allow normal startup and logging."""
    config_path = write_config(
        tmp_path,
        """
operator:
  callsign: KI5VNB
  home_grid: EM79xm
hardware:
  mock: true
""",
    )
    log_path = tmp_path / "logs" / "rolling-thunder.log"

    assert main(config_path, log_path) == 0

    captured = capsys.readouterr()
    assert "Rolling Thunder v4 starting" in captured.out
    assert "KI5VNB" in captured.out
    assert "mock hardware=True" in captured.out
    assert captured.err == ""

    log_text = log_path.read_text(encoding="utf-8")
    assert "Application startup requested" in log_text
    assert "Configuration loaded for operator=KI5VNB" in log_text
    assert "mock_hardware=True" in log_text
    assert f"schema_version={CURRENT_SCHEMA_VERSION}" in log_text


def test_main_reports_missing_configuration_without_traceback(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    """Missing configuration should be reported and logged without traceback."""
    config_path = tmp_path / "missing.yaml"
    log_path = tmp_path / "logs" / "rolling-thunder.log"

    assert main(config_path, log_path) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Rolling Thunder configuration error" in captured.err
    assert str(config_path) in captured.err
    assert "Traceback" not in captured.err

    log_text = log_path.read_text(encoding="utf-8")
    assert "ERROR" in log_text
    assert "Configuration error" in log_text
    assert str(config_path) in log_text
    assert "Traceback" not in log_text


def test_main_reports_invalid_configuration_without_traceback(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    """Invalid configuration should be reported and logged without traceback."""
    config_path = write_config(
        tmp_path,
        """
operator:
  callsign: NOT-A-CALL
  home_grid: EM79xm
""",
    )
    log_path = tmp_path / "logs" / "rolling-thunder.log"

    assert main(config_path, log_path) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "operator.callsign" in captured.err
    assert "Traceback" not in captured.err

    log_text = log_path.read_text(encoding="utf-8")
    assert "ERROR" in log_text
    assert "operator.callsign" in log_text
    assert "Traceback" not in log_text


def test_logging_creates_parent_directory(tmp_path: Path) -> None:
    """Startup logging should create its parent directory automatically."""
    config_path = write_config(
        tmp_path,
        """
operator:
  callsign: KI5VNB
  home_grid: EM79xm
""",
    )
    log_path = tmp_path / "nested" / "log" / "rolling-thunder.log"

    assert not log_path.parent.exists()

    assert main(config_path, log_path) == 0

    assert log_path.is_file()


def test_main_reports_storage_failure_without_traceback(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    """Storage initialization failures should be concise and logged."""
    database_path = tmp_path / "database-directory"
    database_path.mkdir()

    config_path = write_config(
        tmp_path,
        f"""
operator:
  callsign: KI5VNB
  home_grid: EM79xm
storage:
  database_path: {database_path}
""",
    )
    log_path = tmp_path / "logs" / "rolling-thunder.log"

    assert main(config_path, log_path) == 3

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Rolling Thunder storage error" in captured.err
    assert str(database_path) in captured.err
    assert "Traceback" not in captured.err

    log_text = log_path.read_text(encoding="utf-8")
    assert "Storage error" in log_text
    assert str(database_path) in log_text
    assert "Traceback" not in log_text


def test_main_logs_resolved_contact_backup_configuration(
    tmp_path: Path,
) -> None:
    """Startup should resolve and report configured backup settings."""
    config_directory = tmp_path / "config"
    config_directory.mkdir()
    config_path = write_config(
        config_directory,
        """
operator:
  callsign: KI5VNB
  home_grid: EM79xm
storage:
  database_path: data/contacts.db
  contact_backups:
    enabled: true
    directory: ../backups/contacts
    retention_count: 7
""",
    )
    log_path = tmp_path / "logs" / "rolling-thunder.log"

    assert main(config_path, log_path) == 0

    log_text = log_path.read_text(encoding="utf-8")
    expected_directory = (
        tmp_path / "backups" / "contacts"
    ).resolve()

    assert "Contact backups configured enabled=True" in log_text
    assert f"directory={expected_directory}" in log_text
    assert "retention=7" in log_text
    assert expected_directory.is_dir()
    assert len(
        list(
            expected_directory.glob(
                "rolling-thunder-contacts-*.json"
            )
        )
    ) == 1
    assert "Startup contact backup completed" in log_text


def test_main_creates_enabled_startup_contact_backup(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    """Enabled startup backups should create one verified JSON export."""
    database_path = tmp_path / "data" / "contacts.db"
    config_directory = tmp_path / "config"
    config_directory.mkdir()
    config_path = write_config(
        config_directory,
        f"""
operator:
  callsign: KI5VNB
  home_grid: EM79xm
storage:
  database_path: {database_path}
  contact_backups:
    enabled: true
    directory: ../backups/contacts
    retention_count: 3
""",
    )
    log_path = tmp_path / "logs" / "rolling-thunder.log"

    assert main(config_path, log_path) == 0

    captured = capsys.readouterr()
    assert "Rolling Thunder v4 starting" in captured.out
    assert captured.err == ""

    backup_directory = tmp_path / "backups" / "contacts"
    backup_paths = list(
        backup_directory.glob("rolling-thunder-contacts-*.json")
    )

    assert len(backup_paths) == 1

    document = json.loads(
        backup_paths[0].read_text(encoding="utf-8")
    )
    assert document["contacts"] == []

    log_text = log_path.read_text(encoding="utf-8")
    assert "Startup contact backup completed" in log_text
    assert f"path={backup_paths[0]}" in log_text
    assert "contacts=0" in log_text


def test_main_skips_backup_work_when_disabled(
    tmp_path: Path,
) -> None:
    """Disabled backups must not inspect or modify the backup path."""
    database_path = tmp_path / "data" / "contacts.db"
    invalid_backup_path = tmp_path / "occupied"
    invalid_backup_path.write_text("not a directory", encoding="utf-8")

    config_path = write_config(
        tmp_path,
        f"""
operator:
  callsign: KI5VNB
  home_grid: EM79xm
storage:
  database_path: {database_path}
  contact_backups:
    enabled: false
    directory: {invalid_backup_path}
    retention_count: 3
""",
    )
    log_path = tmp_path / "logs" / "rolling-thunder.log"

    assert main(config_path, log_path) == 0
    assert invalid_backup_path.read_text(encoding="utf-8") == (
        "not a directory"
    )

    log_text = log_path.read_text(encoding="utf-8")
    assert "Startup contact backup skipped because disabled" in log_text
    assert "Startup contact backup completed" not in log_text


def test_main_reports_enabled_backup_failure_without_traceback(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    """Enabled backup failures should stop startup with exit code four."""
    database_path = tmp_path / "data" / "contacts.db"
    invalid_backup_path = tmp_path / "occupied"
    invalid_backup_path.write_text("not a directory", encoding="utf-8")

    config_path = write_config(
        tmp_path,
        f"""
operator:
  callsign: KI5VNB
  home_grid: EM79xm
storage:
  database_path: {database_path}
  contact_backups:
    enabled: true
    directory: {invalid_backup_path}
    retention_count: 3
""",
    )
    log_path = tmp_path / "logs" / "rolling-thunder.log"

    assert main(config_path, log_path) == 4

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Rolling Thunder contact backup error" in captured.err
    assert str(invalid_backup_path) in captured.err
    assert "Traceback" not in captured.err

    log_text = log_path.read_text(encoding="utf-8")
    assert "Contact backup error" in log_text
    assert str(invalid_backup_path) in log_text
    assert "Traceback" not in log_text
    assert "Rolling Thunder v4 starting" not in captured.out
