"""Versioned JSON export for locally stored Rolling Thunder contacts."""

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from rolling_thunder.contact_repository import ContactRepository
from rolling_thunder.storage import StorageError

CONTACT_EXPORT_FORMAT_VERSION: Final = 4
SUPPORTED_CONTACT_EXPORT_FORMAT_VERSIONS: Final[frozenset[int]] = frozenset(
    {1, 2, 3, CONTACT_EXPORT_FORMAT_VERSION}
)


class ContactExportError(Exception):
    """Raised when contacts cannot be exported safely."""


def export_contacts_to_json(
    repository: ContactRepository,
    destination: Path,
    *,
    exported_at: datetime | None = None,
) -> int:
    """Atomically export all contacts and return the exported record count."""
    if destination.exists() and destination.is_dir():
        raise ContactExportError(f"Contact export destination is a directory: {destination}")

    timestamp = exported_at or datetime.now(UTC)

    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("Contact export timestamp must include a timezone.")

    timestamp = timestamp.astimezone(UTC)
    contacts = repository.list_all()

    document = {
        "format_version": CONTACT_EXPORT_FORMAT_VERSION,
        "exported_at": _format_utc_datetime(timestamp),
        "contacts": [contact.model_dump(mode="json") for contact in contacts],
    }

    temporary_path: Path | None = None

    try:
        destination.parent.mkdir(parents=True, exist_ok=True)

        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            json.dump(
                document,
                temporary_file,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            temporary_file.write("\n")
            temporary_file.flush()
            os.fsync(temporary_file.fileno())

        os.replace(temporary_path, destination)
    except StorageError:
        raise
    except (OSError, TypeError, ValueError) as error:
        raise ContactExportError(
            f"Contacts could not be exported to {destination}: {error}"
        ) from error
    finally:
        if temporary_path is not None and temporary_path.exists():
            try:
                temporary_path.unlink()
            except OSError:
                pass

    return len(contacts)


def _format_utc_datetime(value: datetime) -> str:
    """Format an aware datetime as canonical UTC JSON text."""
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
