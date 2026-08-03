"""Tests for verified rotating local contact backups."""

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from rolling_thunder import contact_backup
from rolling_thunder.contact_backup import (
    ContactBackupError,
    ContactBackupResult,
    create_contact_backup,
)
from rolling_thunder.contact_import import ContactImportError
from rolling_thunder.contact_repository import ContactRepository
from rolling_thunder.domain import Contact, SynchronizationState


def make_backup_contact() -> Contact:
    """Create a representative contact for backup tests."""
    return Contact(
        contact_id=UUID("00000000-0000-0000-0000-000000000701"),
        callsign="W8O",
        frequency_hz=7_200_000,
        mode="LSB",
        started_at=datetime(2026, 7, 25, 1, 0, tzinfo=UTC),
        rst_sent="59",
        rst_received="59",
        grid="EN80ma",
        my_grid="EM79wm",
        pota_reference="US-1234",
        grid_source="pota_park",
        notes="POTA US-1234",
        synchronization_state=SynchronizationState.PENDING,
    )


def test_backup_creates_and_verifies_timestamped_export(
    tmp_path: Path,
) -> None:
    """A completed backup should be readable and report its contact count."""
    repository = ContactRepository(tmp_path / "contacts.db")
    backup_directory = tmp_path / "backups"
    created_at = datetime(
        2026,
        7,
        25,
        3,
        4,
        5,
        123456,
        tzinfo=UTC,
    )
    repository.add(make_backup_contact())

    result = create_contact_backup(
        repository,
        backup_directory,
        retention_count=5,
        created_at=created_at,
    )

    expected_path = backup_directory / "rolling-thunder-contacts-20260725T030405.123456Z.json"

    assert result == ContactBackupResult(
        path=expected_path,
        contact_count=1,
    )
    assert expected_path.is_file()

    document = json.loads(expected_path.read_text(encoding="utf-8"))

    assert document["exported_at"] == "2026-07-25T03:04:05.123456Z"
    exported = document["contacts"][0]
    assert exported["callsign"] == "W8O"
    assert exported["grid"] == "EN80ma"
    assert exported["my_grid"] == "EM79wm"
    assert exported["pota_reference"] == "US-1234"
    assert exported["grid_source"] == "pota_park"
    assert exported["enrichment_state"] == "ready"
    assert exported["notes"] == "POTA US-1234"


def test_backup_retains_only_configured_newest_backups(
    tmp_path: Path,
) -> None:
    """Rotation should retain the newest managed backup files."""
    repository = ContactRepository(tmp_path / "contacts.db")
    backup_directory = tmp_path / "backups"

    timestamps = [datetime(2026, 7, 25, hour, tzinfo=UTC) for hour in (1, 2, 3, 4)]

    for timestamp in timestamps:
        create_contact_backup(
            repository,
            backup_directory,
            retention_count=3,
            created_at=timestamp,
        )

    names = sorted(path.name for path in backup_directory.iterdir())

    assert names == [
        "rolling-thunder-contacts-20260725T020000.000000Z.json",
        "rolling-thunder-contacts-20260725T030000.000000Z.json",
        "rolling-thunder-contacts-20260725T040000.000000Z.json",
    ]


def test_backup_never_deletes_unrelated_files(tmp_path: Path) -> None:
    """Retention must not remove files not owned by the backup service."""
    repository = ContactRepository(tmp_path / "contacts.db")
    backup_directory = tmp_path / "backups"
    backup_directory.mkdir()
    unrelated = backup_directory / "notes.txt"
    unrelated.write_text("keep me", encoding="utf-8")

    for hour in (1, 2):
        create_contact_backup(
            repository,
            backup_directory,
            retention_count=1,
            created_at=datetime(2026, 7, 25, hour, tzinfo=UTC),
        )

    assert unrelated.read_text(encoding="utf-8") == "keep me"
    assert len(list(backup_directory.glob("rolling-thunder-contacts-*.json"))) == 1


def test_backup_removes_new_file_when_verification_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A backup that cannot be validated must not remain on disk."""
    repository = ContactRepository(tmp_path / "contacts.db")
    backup_directory = tmp_path / "backups"

    def fail_validation(_source: Path) -> int:
        raise ContactImportError("simulated verification failure")

    monkeypatch.setattr(
        contact_backup,
        "validate_contact_export_json",
        fail_validation,
    )

    with pytest.raises(
        ContactBackupError,
        match=r"simulated verification failure",
    ):
        create_contact_backup(
            repository,
            backup_directory,
            retention_count=3,
            created_at=datetime(2026, 7, 25, 3, 0, tzinfo=UTC),
        )

    assert list(backup_directory.iterdir()) == []


def test_backup_rejects_file_as_backup_directory(tmp_path: Path) -> None:
    """The configured backup location must be a directory."""
    repository = ContactRepository(tmp_path / "contacts.db")
    backup_directory = tmp_path / "not-a-directory"
    backup_directory.write_text("occupied", encoding="utf-8")

    with pytest.raises(
        ContactBackupError,
        match=r"is not a directory",
    ):
        create_contact_backup(
            repository,
            backup_directory,
            retention_count=3,
        )


@pytest.mark.parametrize("retention_count", [True, 1.5, "3"])
def test_backup_rejects_non_integer_retention(
    tmp_path: Path,
    retention_count: object,
) -> None:
    """Retention configuration should require a real integer."""
    repository = ContactRepository(tmp_path / "contacts.db")

    with pytest.raises(
        TypeError,
        match=r"must be an integer",
    ):
        create_contact_backup(
            repository,
            tmp_path / "backups",
            retention_count=retention_count,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("retention_count", [0, -1])
def test_backup_rejects_non_positive_retention(
    tmp_path: Path,
    retention_count: int,
) -> None:
    """At least one completed backup must be retained."""
    repository = ContactRepository(tmp_path / "contacts.db")

    with pytest.raises(
        ValueError,
        match=r"must be at least 1",
    ):
        create_contact_backup(
            repository,
            tmp_path / "backups",
            retention_count=retention_count,
        )
