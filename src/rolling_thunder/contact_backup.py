"""Verified rotating backups for locally stored contacts."""

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from rolling_thunder.contact_export import (
    ContactExportError,
    export_contacts_to_json,
)
from rolling_thunder.contact_import import (
    ContactImportError,
    validate_contact_export_json,
)
from rolling_thunder.contact_repository import ContactRepository
from rolling_thunder.storage import StorageError

_BACKUP_PREFIX: Final = "rolling-thunder-contacts-"
_BACKUP_SUFFIX: Final = ".json"


class ContactBackupError(Exception):
    """Raised when a verified contact backup cannot be completed."""


@dataclass(frozen=True, slots=True)
class ContactBackupResult:
    """Details about one completed contact backup."""

    path: Path
    contact_count: int


def create_contact_backup(
    repository: ContactRepository,
    backup_directory: Path,
    *,
    retention_count: int,
    created_at: datetime | None = None,
) -> ContactBackupResult:
    """Create, verify, and rotate one timestamped contact backup."""
    _validate_retention_count(retention_count)

    timestamp = created_at or datetime.now(UTC)

    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("Contact backup timestamp must include a timezone.")

    timestamp = timestamp.astimezone(UTC)

    if backup_directory.exists() and not backup_directory.is_dir():
        raise ContactBackupError(
            f"Contact backup path is not a directory: {backup_directory}"
        )

    filename = (
        f"{_BACKUP_PREFIX}"
        f"{timestamp.strftime('%Y%m%dT%H%M%S.%fZ')}"
        f"{_BACKUP_SUFFIX}"
    )
    destination = backup_directory / filename

    try:
        contact_count = export_contacts_to_json(
            repository,
            destination,
            exported_at=timestamp,
        )
        verified_count = validate_contact_export_json(destination)

        if verified_count != contact_count:
            raise ContactBackupError(
                "Contact backup verification count mismatch: "
                f"exported={contact_count}, verified={verified_count}."
            )

        _prune_backups(
            backup_directory,
            retention_count=retention_count,
        )
    except ContactBackupError:
        destination.unlink(missing_ok=True)
        raise
    except (ContactExportError, ContactImportError, StorageError) as error:
        destination.unlink(missing_ok=True)
        raise ContactBackupError(
            f"Contact backup could not be completed: {destination}: {error}"
        ) from error
    except OSError as error:
        destination.unlink(missing_ok=True)
        raise ContactBackupError(
            f"Contact backup files could not be managed in "
            f"{backup_directory}: {error}"
        ) from error

    return ContactBackupResult(
        path=destination,
        contact_count=contact_count,
    )


def _validate_retention_count(retention_count: int) -> None:
    """Require at least one retained backup."""
    if isinstance(retention_count, bool) or not isinstance(
        retention_count,
        int,
    ):
        raise TypeError("Contact backup retention count must be an integer.")

    if retention_count < 1:
        raise ValueError(
            "Contact backup retention count must be at least 1."
        )


def _prune_backups(
    backup_directory: Path,
    *,
    retention_count: int,
) -> None:
    """Delete only older files managed by this backup service."""
    managed_backups = sorted(
        (
            path
            for path in backup_directory.iterdir()
            if path.is_file()
            and path.name.startswith(_BACKUP_PREFIX)
            and path.name.endswith(_BACKUP_SUFFIX)
        ),
        key=lambda path: path.name,
        reverse=True,
    )

    for obsolete_backup in managed_backups[retention_count:]:
        obsolete_backup.unlink()
