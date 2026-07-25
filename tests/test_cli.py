"""Tests for Rolling Thunder command-line operations."""

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from pytest import CaptureFixture

from rolling_thunder.cli import (
    EXIT_BACKUP_DISABLED,
    EXIT_BACKUP_ERROR,
    EXIT_CONFIGURATION_ERROR,
    EXIT_IMPORT_CONFLICT,
    EXIT_IMPORT_VALIDATION_ERROR,
    EXIT_SUCCESS,
    cli,
)
from rolling_thunder.contact_export import export_contacts_to_json
from rolling_thunder.contact_repository import ContactRepository
from rolling_thunder.domain import Contact, RadioMode


def make_contact() -> Contact:
    """Build one deterministic contact for CLI restore tests."""
    return Contact(
        contact_id=UUID("11111111-2222-3333-4444-555555555555"),
        callsign="K8ABC",
        frequency_hz=14_250_000,
        mode=RadioMode.USB,
        started_at=datetime(2026, 7, 25, 2, 0, tzinfo=UTC),
        rst_sent="59",
        rst_received="59",
        grid="EM79",
        notes="Restore test",
    )


def write_contact_export(
    path: Path,
    contacts: list[Contact],
) -> None:
    """Write a valid contact export for CLI restore tests."""
    class ExportRepository:
        def list_all(self) -> list[Contact]:
            return contacts

    export_contacts_to_json(
        ExportRepository(),
        path,
        exported_at=datetime(2026, 7, 25, 2, 5, tzinfo=UTC),
    )


def write_config(tmp_path: Path, content: str) -> Path:
    """Write a temporary command configuration."""
    path = tmp_path / "rolling-thunder.yaml"
    path.write_text(content, encoding="utf-8")
    return path


def test_manual_backup_command_creates_verified_export(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    """The command should create and report one verified backup."""
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
    log_path = tmp_path / "logs" / "manual-backup.log"

    result = cli(
        [
            "backup-contacts",
            "--config",
            str(config_path),
            "--log",
            str(log_path),
        ]
    )

    assert result == EXIT_SUCCESS

    captured = capsys.readouterr()
    assert captured.err == ""
    assert "Contact backup created:" in captured.out
    assert "contacts: 0" in captured.out
    assert "Rolling Thunder v4 starting" not in captured.out

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
    assert "Manual contact backup requested" in log_text
    assert "Manual contact backup completed" in log_text
    assert f"path={backup_paths[0]}" in log_text
    assert "contacts=0" in log_text


def test_manual_backup_command_requires_enabled_configuration(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    """A disabled backup configuration should reject the command."""
    backup_directory = tmp_path / "backups"
    config_path = write_config(
        tmp_path,
        f"""
operator:
  callsign: KI5VNB
  home_grid: EM79xm
storage:
  database_path: {tmp_path / "data" / "contacts.db"}
  contact_backups:
    enabled: false
    directory: {backup_directory}
""",
    )
    log_path = tmp_path / "logs" / "manual-backup.log"

    result = cli(
        [
            "backup-contacts",
            "--config",
            str(config_path),
            "--log",
            str(log_path),
        ]
    )

    assert result == EXIT_BACKUP_DISABLED

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Contact backups are disabled" in captured.err
    assert "storage.contact_backups.enabled" in captured.err
    assert not backup_directory.exists()


def test_manual_backup_command_reports_missing_configuration(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    """Missing configuration should return the configuration exit code."""
    config_path = tmp_path / "missing.yaml"
    log_path = tmp_path / "logs" / "manual-backup.log"

    result = cli(
        [
            "backup-contacts",
            "--config",
            str(config_path),
            "--log",
            str(log_path),
        ]
    )

    assert result == EXIT_CONFIGURATION_ERROR

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Rolling Thunder configuration error" in captured.err
    assert str(config_path) in captured.err
    assert "Traceback" not in captured.err


def test_manual_backup_command_reports_backup_failure(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    """Backup filesystem failures should use the backup exit code."""
    invalid_backup_path = tmp_path / "occupied"
    invalid_backup_path.write_text(
        "not a directory",
        encoding="utf-8",
    )
    config_path = write_config(
        tmp_path,
        f"""
operator:
  callsign: KI5VNB
  home_grid: EM79xm
storage:
  database_path: {tmp_path / "data" / "contacts.db"}
  contact_backups:
    enabled: true
    directory: {invalid_backup_path}
    retention_count: 3
""",
    )
    log_path = tmp_path / "logs" / "manual-backup.log"

    result = cli(
        [
            "backup-contacts",
            "--config",
            str(config_path),
            "--log",
            str(log_path),
        ]
    )

    assert result == EXIT_BACKUP_ERROR

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Rolling Thunder contact backup error" in captured.err
    assert str(invalid_backup_path) in captured.err
    assert "Traceback" not in captured.err


def test_restore_contacts_dry_run_does_not_modify_database(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    """Dry-run restore should report changes without storing contacts."""
    database_path = tmp_path / "data" / "contacts.db"
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
    backup_path = tmp_path / "backup.json"
    contact = make_contact()
    write_contact_export(backup_path, [contact])
    log_path = tmp_path / "logs" / "restore.log"

    result = cli(
        [
            "restore-contacts",
            str(backup_path),
            "--config",
            str(config_path),
            "--log",
            str(log_path),
            "--dry-run",
        ]
    )

    assert result == EXIT_SUCCESS

    captured = capsys.readouterr()
    assert captured.err == ""
    assert "Contact restore dry run" in captured.out
    assert "imported=1" in captured.out
    assert "skipped=0" in captured.out
    assert "conflicted=0" in captured.out

    repository = ContactRepository(database_path)
    assert repository.get(contact.contact_id) is None


def test_restore_contacts_imports_valid_backup(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    """A non-dry-run restore should transactionally import contacts."""
    database_path = tmp_path / "data" / "contacts.db"
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
    backup_path = tmp_path / "backup.json"
    contact = make_contact()
    write_contact_export(backup_path, [contact])

    result = cli(
        [
            "restore-contacts",
            str(backup_path),
            "--config",
            str(config_path),
            "--log",
            str(tmp_path / "logs" / "restore.log"),
        ]
    )

    assert result == EXIT_SUCCESS

    captured = capsys.readouterr()
    assert captured.err == ""
    assert "Contact restore completed" in captured.out
    assert "imported=1" in captured.out
    assert "skipped=0" in captured.out
    assert "conflicted=0" in captured.out

    repository = ContactRepository(database_path)
    assert repository.get(contact.contact_id) == contact


def test_restore_contacts_rejects_invalid_backup(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    """Invalid JSON should fail before changing the database."""
    config_path = write_config(
        tmp_path,
        f"""
operator:
  callsign: KI5VNB
  home_grid: EM79xm
storage:
  database_path: {tmp_path / "data" / "contacts.db"}
""",
    )
    backup_path = tmp_path / "backup.json"
    backup_path.write_text("{invalid", encoding="utf-8")

    result = cli(
        [
            "restore-contacts",
            str(backup_path),
            "--config",
            str(config_path),
            "--log",
            str(tmp_path / "logs" / "restore.log"),
        ]
    )

    assert result == EXIT_IMPORT_VALIDATION_ERROR

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "contact restore validation error" in captured.err
    assert "Traceback" not in captured.err


def test_restore_contacts_reports_conflict_without_writing(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    """Conflicting UUID data should stop the complete restore."""
    database_path = tmp_path / "data" / "contacts.db"
    repository = ContactRepository(database_path)
    existing = make_contact()
    repository.add(existing)

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
    backup_path = tmp_path / "backup.json"
    conflicting = existing.model_copy(
        update={"callsign": "W8O"}
    )
    write_contact_export(backup_path, [conflicting])

    result = cli(
        [
            "restore-contacts",
            str(backup_path),
            "--config",
            str(config_path),
            "--log",
            str(tmp_path / "logs" / "restore.log"),
        ]
    )

    assert result == EXIT_IMPORT_CONFLICT

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "contact restore conflict" in captured.err
    assert repository.get(existing.contact_id) == existing
