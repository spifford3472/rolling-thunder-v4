"""Tests for Rolling Thunder command-line operations."""

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from pytest import CaptureFixture

from rolling_thunder.cli import (
    EXIT_BACKUP_DISABLED,
    EXIT_BACKUP_ERROR,
    EXIT_CONFIGURATION_ERROR,
    EXIT_CONTACT_CONFLICT,
    EXIT_CONTACT_NOT_FOUND,
    EXIT_CONTACT_VALIDATION_ERROR,
    EXIT_IMPORT_CONFLICT,
    EXIT_IMPORT_VALIDATION_ERROR,
    EXIT_SUCCESS,
    cli,
)
from rolling_thunder.contact_export import export_contacts_to_json
from rolling_thunder.contact_repository import (
    ContactAlreadyExistsError,
    ContactRepository,
)
from rolling_thunder.domain import (
    Contact,
    RadioMode,
    SynchronizationState,
)


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


def test_add_contact_stores_valid_manual_entry(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    """A valid manual entry should be normalized and stored."""
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

    result = cli(
        [
            "add-contact",
            "k8abc",
            "--frequency-hz",
            "14250000",
            "--mode",
            "usb",
            "--started-at",
            "2026-07-25T02:30:00-04:00",
            "--rst-sent",
            "59",
            "--rst-received",
            "57",
            "--grid",
            "em79xm",
            "--notes",
            "  Manual entry test  ",
            "--config",
            str(config_path),
            "--log",
            str(tmp_path / "logs" / "entry.log"),
        ]
    )

    assert result == EXIT_SUCCESS

    captured = capsys.readouterr()
    assert captured.err == ""
    assert "Contact created:" in captured.out
    assert "callsign=K8ABC" in captured.out
    assert "frequency_hz=14250000" in captured.out
    assert "mode=USB" in captured.out
    assert "started_at=2026-07-25T06:30:00Z" in captured.out

    contacts = ContactRepository(database_path).list_all()
    assert len(contacts) == 1

    contact = contacts[0]
    assert str(contact.callsign) == "K8ABC"
    assert contact.frequency_hz == 14_250_000
    assert contact.mode is RadioMode.USB
    assert contact.rst_sent == "59"
    assert contact.rst_received == "57"
    assert str(contact.grid) == "EM79xm"
    assert contact.notes == "Manual entry test"


def test_add_contact_defaults_time_and_signal_reports(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    """Omitted time and reports should use safe operator defaults."""
    database_path = tmp_path / "contacts.db"
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
    before = datetime.now(UTC)

    result = cli(
        [
            "add-contact",
            "W8O",
            "--frequency-hz",
            "7255000",
            "--mode",
            "LSB",
            "--config",
            str(config_path),
            "--log",
            str(tmp_path / "entry.log"),
        ]
    )

    after = datetime.now(UTC)

    assert result == EXIT_SUCCESS
    assert capsys.readouterr().err == ""

    contacts = ContactRepository(database_path).list_all()
    assert len(contacts) == 1
    assert before <= contacts[0].started_at <= after
    assert contacts[0].rst_sent == "59"
    assert contacts[0].rst_received == "59"


def test_add_contact_rejects_invalid_domain_values(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    """Invalid entry data should fail before a contact is stored."""
    database_path = tmp_path / "contacts.db"
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

    result = cli(
        [
            "add-contact",
            "not a callsign",
            "--frequency-hz",
            "-1",
            "--mode",
            "INVALID",
            "--started-at",
            "not-a-time",
            "--rst-sent",
            "99",
            "--config",
            str(config_path),
            "--log",
            str(tmp_path / "entry.log"),
        ]
    )

    assert result == EXIT_CONTACT_VALIDATION_ERROR

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Rolling Thunder contact validation error" in captured.err
    assert "Traceback" not in captured.err
    assert not database_path.exists()


def test_add_contact_reports_duplicate_uuid_conflict(
    tmp_path: Path,
    capsys: CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Repository UUID collisions should use the contact conflict code."""
    config_path = write_config(
        tmp_path,
        f"""
operator:
  callsign: KI5VNB
  home_grid: EM79xm
storage:
  database_path: {tmp_path / "contacts.db"}
""",
    )

    def reject_contact(
        self: ContactRepository,
        contact: Contact,
    ) -> None:
        raise ContactAlreadyExistsError(
            f"Contact already exists: {contact.contact_id}"
        )

    monkeypatch.setattr(ContactRepository, "add", reject_contact)

    result = cli(
        [
            "add-contact",
            "K8ABC",
            "--frequency-hz",
            "14250000",
            "--mode",
            "USB",
            "--config",
            str(config_path),
            "--log",
            str(tmp_path / "entry.log"),
        ]
    )

    assert result == EXIT_CONTACT_CONFLICT

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Rolling Thunder contact conflict" in captured.err
    assert "Traceback" not in captured.err


def test_list_contacts_outputs_newest_first(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    """Stored contacts should be printed newest first with core details."""
    database_path = tmp_path / "contacts.db"
    repository = ContactRepository(database_path)

    older = make_contact().model_copy(
        update={
            "contact_id": UUID(
                "11111111-2222-3333-4444-555555555551"
            ),
            "callsign": "K8ABC",
            "started_at": datetime(
                2026,
                7,
                25,
                1,
                0,
                tzinfo=UTC,
            ),
            "notes": 'Older "contact"',
        }
    )
    newer = make_contact().model_copy(
        update={
            "contact_id": UUID(
                "11111111-2222-3333-4444-555555555552"
            ),
            "callsign": "W8O",
            "started_at": datetime(
                2026,
                7,
                25,
                2,
                0,
                tzinfo=UTC,
            ),
            "grid": None,
            "notes": "Newer contact",
        }
    )
    repository.add(older)
    repository.add(newer)

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

    result = cli(
        [
            "list-contacts",
            "--config",
            str(config_path),
            "--log",
            str(tmp_path / "list.log"),
        ]
    )

    assert result == EXIT_SUCCESS

    captured = capsys.readouterr()
    assert captured.err == ""

    lines = captured.out.strip().splitlines()
    assert len(lines) == 2
    assert "callsign=W8O" in lines[0]
    assert "callsign=K8ABC" in lines[1]
    assert "frequency_hz=14250000" in lines[0]
    assert "mode=USB" in lines[0]
    assert "started_at=2026-07-25T02:00:00Z" in lines[0]
    assert "rst=59/59" in lines[0]
    assert "grid=-" in lines[0]
    assert "sync=pending" in lines[0]
    assert 'notes="Newer contact"' in lines[0]
    assert 'notes="Older \\"contact\\""' in lines[1]


def test_list_contacts_honors_limit(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    """The requested limit should bound the newest-first result."""
    database_path = tmp_path / "contacts.db"
    repository = ContactRepository(database_path)

    for index in range(3):
        repository.add(
            make_contact().model_copy(
                update={
                    "contact_id": UUID(
                        f"11111111-2222-3333-4444-{index + 1:012d}"
                    ),
                    "callsign": f"K8A{index}",
                    "started_at": datetime(
                        2026,
                        7,
                        25,
                        index,
                        0,
                        tzinfo=UTC,
                    ),
                }
            )
        )

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

    result = cli(
        [
            "list-contacts",
            "--limit",
            "2",
            "--config",
            str(config_path),
            "--log",
            str(tmp_path / "list.log"),
        ]
    )

    assert result == EXIT_SUCCESS

    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 2
    assert "callsign=K8A2" in lines[0]
    assert "callsign=K8A1" in lines[1]


def test_list_contacts_reports_empty_repository(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    """An empty repository should produce a clear successful result."""
    database_path = tmp_path / "contacts.db"
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

    result = cli(
        [
            "list-contacts",
            "--config",
            str(config_path),
            "--log",
            str(tmp_path / "list.log"),
        ]
    )

    assert result == EXIT_SUCCESS

    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out == "No contacts found.\n"


def test_list_contacts_rejects_invalid_limit(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    """An out-of-range limit should fail with contact validation."""
    config_path = write_config(
        tmp_path,
        f"""
operator:
  callsign: KI5VNB
  home_grid: EM79xm
storage:
  database_path: {tmp_path / "contacts.db"}
""",
    )

    result = cli(
        [
            "list-contacts",
            "--limit",
            "0",
            "--config",
            str(config_path),
            "--log",
            str(tmp_path / "list.log"),
        ]
    )

    assert result == EXIT_CONTACT_VALIDATION_ERROR

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Rolling Thunder contact validation error" in captured.err
    assert "between 1 and 1000" in captured.err
    assert "Traceback" not in captured.err


def test_show_contact_outputs_complete_details(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    """A stored contact should be displayed with all operator details."""
    database_path = tmp_path / "contacts.db"
    repository = ContactRepository(database_path)

    contact = Contact(
        contact_id=UUID(
            "11111111-2222-3333-4444-555555555555"
        ),
        callsign="K8ABC",
        frequency_hz=14_250_000,
        mode=RadioMode.USB,
        started_at=datetime(
            2026,
            7,
            25,
            6,
            30,
            tzinfo=UTC,
        ),
        rst_sent="59",
        rst_received="57",
        grid="EM79xm",
        notes="Detailed contact",
    )
    repository.add(contact)

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

    result = cli(
        [
            "show-contact",
            str(contact.contact_id),
            "--config",
            str(config_path),
            "--log",
            str(tmp_path / "show.log"),
        ]
    )

    assert result == EXIT_SUCCESS

    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out == (
        "Contact ID: 11111111-2222-3333-4444-555555555555\n"
        "Callsign: K8ABC\n"
        "Frequency: 14250000 Hz\n"
        "Mode: USB\n"
        "Started: 2026-07-25T06:30:00Z\n"
        "RST sent: 59\n"
        "RST received: 57\n"
        "Grid: EM79xm\n"
        "Synchronization: pending\n"
        "Notes: Detailed contact\n"
    )


def test_show_contact_displays_missing_optional_values(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    """Absent grid and notes should be represented clearly."""
    database_path = tmp_path / "contacts.db"
    repository = ContactRepository(database_path)

    contact = make_contact().model_copy(
        update={
            "contact_id": UUID(
                "11111111-2222-3333-4444-555555555556"
            ),
            "grid": None,
            "notes": None,
        }
    )
    repository.add(contact)

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

    result = cli(
        [
            "show-contact",
            str(contact.contact_id),
            "--config",
            str(config_path),
            "--log",
            str(tmp_path / "show.log"),
        ]
    )

    assert result == EXIT_SUCCESS

    output = capsys.readouterr().out
    assert "Grid: -\n" in output
    assert "Notes: -\n" in output


def test_show_contact_rejects_invalid_uuid(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    """Malformed UUID input should fail before opening the database."""
    database_path = tmp_path / "contacts.db"
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

    result = cli(
        [
            "show-contact",
            "not-a-uuid",
            "--config",
            str(config_path),
            "--log",
            str(tmp_path / "show.log"),
        ]
    )

    assert result == EXIT_CONTACT_VALIDATION_ERROR

    captured = capsys.readouterr()
    assert captured.out == ""
    assert (
        "Rolling Thunder contact validation error: "
        "invalid contact UUID: not-a-uuid"
        in captured.err
    )
    assert "Traceback" not in captured.err
    assert not database_path.exists()


def test_show_contact_reports_missing_contact(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    """A valid UUID absent from storage should return not-found."""
    database_path = tmp_path / "contacts.db"
    missing_id = UUID(
        "11111111-2222-3333-4444-555555555557"
    )
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

    result = cli(
        [
            "show-contact",
            str(missing_id),
            "--config",
            str(config_path),
            "--log",
            str(tmp_path / "show.log"),
        ]
    )

    assert result == EXIT_CONTACT_NOT_FOUND

    captured = capsys.readouterr()
    assert captured.out == ""
    assert (
        "Rolling Thunder contact not found: "
        "11111111-2222-3333-4444-555555555557"
        in captured.err
    )
    assert "Traceback" not in captured.err


def test_update_contact_replaces_selected_fields(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    """Selected replacements should change while other fields remain."""
    database_path = tmp_path / "contacts.db"
    repository = ContactRepository(database_path)
    original = Contact(
        contact_id=UUID(
            "11111111-2222-3333-4444-555555555561"
        ),
        callsign="K8ABC",
        frequency_hz=14_250_000,
        mode=RadioMode.USB,
        started_at=datetime(2026, 7, 25, 6, 30, tzinfo=UTC),
        rst_sent="59",
        rst_received="57",
        grid="EM79xm",
        notes="Original notes",
        synchronization_state=SynchronizationState.SYNCHRONIZED,
    )
    repository.add(original)

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

    result = cli(
        [
            "update-contact",
            str(original.contact_id),
            "--frequency-hz",
            "7255000",
            "--mode",
            "lsb",
            "--rst-received",
            "55",
            "--notes",
            "Corrected notes",
            "--config",
            str(config_path),
            "--log",
            str(tmp_path / "update.log"),
        ]
    )

    assert result == EXIT_SUCCESS

    captured = capsys.readouterr()
    assert captured.err == ""
    assert "changed=true" in captured.out
    assert "frequency_hz=7255000" in captured.out
    assert "mode=LSB" in captured.out
    assert "sync=pending" in captured.out

    updated = repository.get(original.contact_id)
    assert updated is not None
    assert updated.callsign == original.callsign
    assert updated.frequency_hz == 7_255_000
    assert updated.mode is RadioMode.LSB
    assert updated.started_at == original.started_at
    assert updated.rst_sent == original.rst_sent
    assert updated.rst_received == "55"
    assert updated.grid == original.grid
    assert updated.notes == "Corrected notes"
    assert updated.synchronization_state is SynchronizationState.PENDING


def test_update_contact_can_clear_optional_fields(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    """Explicit clear options should remove grid and notes."""
    database_path = tmp_path / "contacts.db"
    repository = ContactRepository(database_path)
    original = make_contact().model_copy(
        update={
            "contact_id": UUID(
                "11111111-2222-3333-4444-555555555562"
            ),
            "synchronization_state": SynchronizationState.SYNCHRONIZED,
        }
    )
    repository.add(original)

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

    result = cli(
        [
            "update-contact",
            str(original.contact_id),
            "--clear-grid",
            "--clear-notes",
            "--config",
            str(config_path),
            "--log",
            str(tmp_path / "update.log"),
        ]
    )

    assert result == EXIT_SUCCESS
    assert capsys.readouterr().err == ""

    updated = repository.get(original.contact_id)
    assert updated is not None
    assert updated.grid is None
    assert updated.notes is None
    assert updated.synchronization_state is SynchronizationState.PENDING


def test_update_contact_preserves_sync_state_for_identical_value(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    """An identical replacement should not reset synchronization state."""
    database_path = tmp_path / "contacts.db"
    repository = ContactRepository(database_path)
    original = make_contact().model_copy(
        update={
            "contact_id": UUID(
                "11111111-2222-3333-4444-555555555563"
            ),
            "synchronization_state": SynchronizationState.SYNCHRONIZED,
        }
    )
    repository.add(original)

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

    result = cli(
        [
            "update-contact",
            str(original.contact_id),
            "--callsign",
            str(original.callsign),
            "--config",
            str(config_path),
            "--log",
            str(tmp_path / "update.log"),
        ]
    )

    assert result == EXIT_SUCCESS

    captured = capsys.readouterr()
    assert captured.err == ""
    assert "changed=false" in captured.out
    assert "sync=synchronized" in captured.out

    updated = repository.get(original.contact_id)
    assert updated is not None
    assert (
        updated.synchronization_state
        is SynchronizationState.SYNCHRONIZED
    )


def test_update_contact_rejects_missing_replacements(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    """An update command must contain at least one replacement."""
    config_path = write_config(
        tmp_path,
        f"""
operator:
  callsign: KI5VNB
  home_grid: EM79xm
storage:
  database_path: {tmp_path / "contacts.db"}
""",
    )

    result = cli(
        [
            "update-contact",
            "11111111-2222-3333-4444-555555555564",
            "--config",
            str(config_path),
            "--log",
            str(tmp_path / "update.log"),
        ]
    )

    assert result == EXIT_CONTACT_VALIDATION_ERROR

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "at least one replacement field is required" in captured.err
    assert "Traceback" not in captured.err


def test_update_contact_rejects_invalid_replacement(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    """Invalid replacement data should leave storage unchanged."""
    database_path = tmp_path / "contacts.db"
    repository = ContactRepository(database_path)
    original = make_contact().model_copy(
        update={
            "contact_id": UUID(
                "11111111-2222-3333-4444-555555555565"
            )
        }
    )
    repository.add(original)

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

    result = cli(
        [
            "update-contact",
            str(original.contact_id),
            "--frequency-hz",
            "-1",
            "--mode",
            "INVALID",
            "--rst-sent",
            "99",
            "--config",
            str(config_path),
            "--log",
            str(tmp_path / "update.log"),
        ]
    )

    assert result == EXIT_CONTACT_VALIDATION_ERROR

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Rolling Thunder contact validation error" in captured.err
    assert "Traceback" not in captured.err
    assert repository.get(original.contact_id) == original


def test_update_contact_reports_missing_contact(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    """A valid absent UUID should return contact-not-found."""
    missing_id = UUID(
        "11111111-2222-3333-4444-555555555566"
    )
    config_path = write_config(
        tmp_path,
        f"""
operator:
  callsign: KI5VNB
  home_grid: EM79xm
storage:
  database_path: {tmp_path / "contacts.db"}
""",
    )

    result = cli(
        [
            "update-contact",
            str(missing_id),
            "--notes",
            "Replacement",
            "--config",
            str(config_path),
            "--log",
            str(tmp_path / "update.log"),
        ]
    )

    assert result == EXIT_CONTACT_NOT_FOUND

    captured = capsys.readouterr()
    assert captured.out == ""
    assert f"Rolling Thunder contact not found: {missing_id}" in captured.err
    assert "Traceback" not in captured.err


def test_delete_contact_requires_matching_confirmation(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    """A different confirmation UUID must prevent deletion."""
    database_path = tmp_path / "contacts.db"
    repository = ContactRepository(database_path)
    contact = make_contact().model_copy(
        update={
            "contact_id": UUID(
                "11111111-2222-3333-4444-555555555571"
            )
        }
    )
    repository.add(contact)

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

    result = cli(
        [
            "delete-contact",
            str(contact.contact_id),
            "--confirm",
            "11111111-2222-3333-4444-555555555572",
            "--config",
            str(config_path),
            "--log",
            str(tmp_path / "delete.log"),
        ]
    )

    assert result == EXIT_CONTACT_VALIDATION_ERROR

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "confirmation UUID does not match contact UUID" in captured.err
    assert "Traceback" not in captured.err
    assert repository.get(contact.contact_id) == contact


def test_delete_contact_rejects_invalid_target_uuid(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    """A malformed target UUID should fail before database access."""
    database_path = tmp_path / "contacts.db"
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

    result = cli(
        [
            "delete-contact",
            "not-a-uuid",
            "--confirm",
            "11111111-2222-3333-4444-555555555573",
            "--config",
            str(config_path),
            "--log",
            str(tmp_path / "delete.log"),
        ]
    )

    assert result == EXIT_CONTACT_VALIDATION_ERROR

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "invalid contact UUID: not-a-uuid" in captured.err
    assert "Traceback" not in captured.err
    assert not database_path.exists()


def test_delete_contact_rejects_invalid_confirmation_uuid(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    """A malformed confirmation UUID should fail before database access."""
    database_path = tmp_path / "contacts.db"
    target_id = UUID(
        "11111111-2222-3333-4444-555555555574"
    )
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

    result = cli(
        [
            "delete-contact",
            str(target_id),
            "--confirm",
            "not-a-uuid",
            "--config",
            str(config_path),
            "--log",
            str(tmp_path / "delete.log"),
        ]
    )

    assert result == EXIT_CONTACT_VALIDATION_ERROR

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "invalid confirmation UUID: not-a-uuid" in captured.err
    assert "Traceback" not in captured.err
    assert not database_path.exists()


def test_delete_contact_removes_confirmed_contact(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    """A matching confirmation should permanently remove the contact."""
    database_path = tmp_path / "contacts.db"
    repository = ContactRepository(database_path)
    contact = Contact(
        contact_id=UUID(
            "11111111-2222-3333-4444-555555555575"
        ),
        callsign="K8ABC",
        frequency_hz=14_250_000,
        mode=RadioMode.USB,
        started_at=datetime(2026, 7, 25, 6, 30, tzinfo=UTC),
        rst_sent="59",
        rst_received="57",
        grid="EM79xm",
        notes="Delete this contact",
    )
    repository.add(contact)

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

    result = cli(
        [
            "delete-contact",
            str(contact.contact_id),
            "--confirm",
            str(contact.contact_id),
            "--config",
            str(config_path),
            "--log",
            str(tmp_path / "delete.log"),
        ]
    )

    assert result == EXIT_SUCCESS

    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out == (
        "Contact deleted: "
        "id=11111111-2222-3333-4444-555555555575 "
        "callsign=K8ABC "
        "frequency_hz=14250000 "
        "mode=USB\n"
    )
    assert repository.get(contact.contact_id) is None


def test_delete_contact_reports_missing_contact(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    """A confirmed absent UUID should return contact-not-found."""
    missing_id = UUID(
        "11111111-2222-3333-4444-555555555576"
    )
    config_path = write_config(
        tmp_path,
        f"""
operator:
  callsign: KI5VNB
  home_grid: EM79xm
storage:
  database_path: {tmp_path / "contacts.db"}
""",
    )

    result = cli(
        [
            "delete-contact",
            str(missing_id),
            "--confirm",
            str(missing_id),
            "--config",
            str(config_path),
            "--log",
            str(tmp_path / "delete.log"),
        ]
    )

    assert result == EXIT_CONTACT_NOT_FOUND

    captured = capsys.readouterr()
    assert captured.out == ""
    assert f"Rolling Thunder contact not found: {missing_id}" in captured.err
    assert "Traceback" not in captured.err
