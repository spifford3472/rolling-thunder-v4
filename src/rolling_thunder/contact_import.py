"""Validated transactional recovery from Rolling Thunder contact JSON."""

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from rolling_thunder.contact_export import (
    SUPPORTED_CONTACT_EXPORT_FORMAT_VERSIONS,
)
from rolling_thunder.contact_repository import (
    ContactConflictError,
    ContactRepository,
)
from rolling_thunder.domain import Contact
from rolling_thunder.storage import StorageError

_REQUIRED_DOCUMENT_KEYS = {
    "format_version",
    "exported_at",
    "contacts",
}


class ContactImportError(Exception):
    """Raised when a contact export cannot be validated or recovered."""


@dataclass(frozen=True, slots=True)
class ContactImportResult:
    """Counts produced by a completed contact recovery."""

    imported: int
    skipped: int


@dataclass(frozen=True, slots=True)
class ContactImportPreview:
    """Counts produced without changing the contact repository."""

    imported: int
    skipped: int
    conflicted: int


def validate_contact_export_json(source: Path) -> int:
    """Validate an export without writing and return its contact count."""
    document = _read_document(source)
    contacts = _validate_document(document)
    return len(contacts)


def preview_contact_import(
    repository: ContactRepository,
    source: Path,
) -> ContactImportPreview:
    """Validate and compare an export without writing to the repository."""
    document = _read_document(source)
    contacts = _validate_document(document)

    imported = 0
    skipped = 0
    conflicted = 0

    for contact in contacts:
        existing = repository.get(contact.contact_id)

        if existing is None:
            imported += 1
        elif existing == contact:
            skipped += 1
        else:
            conflicted += 1

    return ContactImportPreview(
        imported=imported,
        skipped=skipped,
        conflicted=conflicted,
    )


def import_contacts_from_json(
    repository: ContactRepository,
    source: Path,
) -> ContactImportResult:
    """Validate a complete export and transactionally recover its contacts."""
    document = _read_document(source)
    contacts = _validate_document(document)

    try:
        imported, skipped = repository.recover_contacts(contacts)
    except ContactConflictError:
        raise
    except StorageError as error:
        raise ContactImportError(
            f"Contacts could not be imported from {source}: {error}"
        ) from error

    return ContactImportResult(
        imported=imported,
        skipped=skipped,
    )


def _read_document(source: Path) -> object:
    """Read and decode one JSON export."""
    try:
        return json.loads(source.read_text(encoding="utf-8"))
    except OSError as error:
        raise ContactImportError(
            f"Contact import file could not be read: {source}: {error}"
        ) from error
    except json.JSONDecodeError as error:
        raise ContactImportError(
            f"Contact import file is not valid JSON: "
            f"{source}: line {error.lineno}, column {error.colno}."
        ) from error


def _validate_document(document: object) -> list[Contact]:
    """Validate export metadata and every contact before any database write."""
    if not isinstance(document, dict):
        raise ContactImportError("Contact import document must be a JSON object.")

    document_keys = set(document)

    if document_keys != _REQUIRED_DOCUMENT_KEYS:
        missing = sorted(_REQUIRED_DOCUMENT_KEYS - document_keys)
        unexpected = sorted(document_keys - _REQUIRED_DOCUMENT_KEYS)
        raise ContactImportError(
            f"Contact import document has invalid keys: missing={missing}, unexpected={unexpected}."
        )

    version = document["format_version"]

    if isinstance(version, bool) or not isinstance(version, int):
        raise ContactImportError("Contact import format_version must be an integer.")

    if version not in SUPPORTED_CONTACT_EXPORT_FORMAT_VERSIONS:
        raise ContactImportError(
            f"Unsupported contact import format version: {version}; "
            "supported versions are "
            f"{sorted(SUPPORTED_CONTACT_EXPORT_FORMAT_VERSIONS)}."
        )

    _validate_export_timestamp(document["exported_at"])

    raw_contacts = document["contacts"]

    if not isinstance(raw_contacts, list):
        raise ContactImportError("Contact import contacts value must be a JSON array.")

    contacts: list[Contact] = []

    for index, raw_contact in enumerate(raw_contacts):
        if not isinstance(raw_contact, dict):
            raise ContactImportError(f"Contact import record {index} must be a JSON object.")

        try:
            contacts.append(Contact.model_validate(raw_contact))
        except ValidationError as error:
            raise ContactImportError(
                f"Contact import record {index} is invalid: {error}"
            ) from error

    return contacts


def _validate_export_timestamp(value: object) -> None:
    """Require an ISO-8601 timestamp containing timezone information."""
    if not isinstance(value, str):
        raise ContactImportError("Contact import exported_at must be a string.")

    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ContactImportError(f"Contact import exported_at is invalid: {value}.") from error

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ContactImportError("Contact import exported_at must include a timezone.")
