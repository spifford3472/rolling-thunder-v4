"""Tests for validated transactional contact JSON recovery."""

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from rolling_thunder.contact_export import export_contacts_to_json
from rolling_thunder.contact_import import (
    ContactImportError,
    ContactImportResult,
    import_contacts_from_json,
    preview_contact_import,
)
from rolling_thunder.contact_repository import (
    ContactConflictError,
    ContactRepository,
)
from rolling_thunder.domain import Contact, SynchronizationState


def make_import_contact(
    *,
    contact_id: UUID,
    callsign: str,
    started_at: datetime,
    notes: str | None = None,
) -> Contact:
    """Create a representative contact for import tests."""
    return Contact(
        contact_id=contact_id,
        callsign=callsign,
        frequency_hz=14_250_000,
        mode="USB",
        started_at=started_at,
        rst_sent="59",
        rst_received="57",
        grid="EM79xm",
        notes=notes,
        synchronization_state=SynchronizationState.PENDING,
    )


def write_document(
    path: Path,
    contacts: list[dict[str, object]],
    *,
    format_version: int = 1,
) -> None:
    """Write a minimally valid import document."""
    path.write_text(
        json.dumps(
            {
                "format_version": format_version,
                "exported_at": "2026-07-25T03:00:00Z",
                "contacts": contacts,
            }
        ),
        encoding="utf-8",
    )


def contact_json(contact: Contact) -> dict[str, object]:
    """Convert a domain contact into export-compatible JSON values."""
    return contact.model_dump(mode="json")


def test_import_recovers_all_contacts_transactionally(tmp_path: Path) -> None:
    """A valid export should recover all contacts."""
    source_repository = ContactRepository(tmp_path / "source.db")
    target_repository = ContactRepository(tmp_path / "target.db")
    export_path = tmp_path / "contacts.json"

    older = make_import_contact(
        contact_id=UUID("00000000-0000-0000-0000-000000000001"),
        callsign="W8O",
        started_at=datetime(2026, 7, 25, 1, 0, tzinfo=UTC),
    )
    newer = make_import_contact(
        contact_id=UUID("00000000-0000-0000-0000-000000000002"),
        callsign="KI5VNB/P",
        started_at=datetime(2026, 7, 25, 2, 0, tzinfo=UTC),
        notes="Recovered contact",
    )

    source_repository.add(older)
    source_repository.add(newer)
    export_contacts_to_json(
        source_repository,
        export_path,
        exported_at=datetime(2026, 7, 25, 3, 0, tzinfo=UTC),
    )

    result = import_contacts_from_json(
        target_repository,
        export_path,
    )

    assert result == ContactImportResult(imported=2, skipped=0)
    assert target_repository.list_all() == [newer, older]


def test_import_skips_exact_existing_contact(tmp_path: Path) -> None:
    """An identical UUID and payload should be safely skipped."""
    repository = ContactRepository(tmp_path / "contacts.db")
    source = tmp_path / "contacts.json"
    contact = make_import_contact(
        contact_id=UUID("00000000-0000-0000-0000-000000000003"),
        callsign="W8O",
        started_at=datetime(2026, 7, 25, 2, 0, tzinfo=UTC),
    )
    repository.add(contact)
    write_document(source, [contact_json(contact)])

    result = import_contacts_from_json(repository, source)

    assert result == ContactImportResult(imported=0, skipped=1)
    assert repository.list_all() == [contact]


def test_import_rejects_conflicting_existing_uuid(tmp_path: Path) -> None:
    """A matching UUID with different data should fail and roll back."""
    repository = ContactRepository(tmp_path / "contacts.db")
    source = tmp_path / "contacts.json"
    existing = make_import_contact(
        contact_id=UUID("00000000-0000-0000-0000-000000000004"),
        callsign="W8O",
        started_at=datetime(2026, 7, 25, 1, 0, tzinfo=UTC),
    )
    new_contact = make_import_contact(
        contact_id=UUID("00000000-0000-0000-0000-000000000005"),
        callsign="K8ABC",
        started_at=datetime(2026, 7, 25, 2, 0, tzinfo=UTC),
    )
    conflict = existing.model_copy(update={"callsign": "N8XYZ"})

    repository.add(existing)
    write_document(
        source,
        [
            contact_json(new_contact),
            contact_json(conflict),
        ],
    )

    with pytest.raises(
        ContactConflictError,
        match=str(existing.contact_id),
    ):
        import_contacts_from_json(repository, source)

    assert repository.list_all() == [existing]


def test_import_validates_every_record_before_writing(tmp_path: Path) -> None:
    """A later invalid record must prevent earlier valid records being written."""
    repository = ContactRepository(tmp_path / "contacts.db")
    source = tmp_path / "contacts.json"
    valid = make_import_contact(
        contact_id=UUID("00000000-0000-0000-0000-000000000006"),
        callsign="W8O",
        started_at=datetime(2026, 7, 25, 2, 0, tzinfo=UTC),
    )
    invalid = contact_json(valid)
    invalid["contact_id"] = "not-a-uuid"

    write_document(
        source,
        [
            contact_json(valid),
            invalid,
        ],
    )

    with pytest.raises(
        ContactImportError,
        match=r"record 1 is invalid",
    ):
        import_contacts_from_json(repository, source)

    assert repository.list_all() == []


def test_import_accepts_legacy_version_one_without_new_fields(
    tmp_path: Path,
) -> None:
    repository = ContactRepository(tmp_path / "contacts.db")
    source = tmp_path / "legacy.json"
    contact = make_import_contact(
        contact_id=UUID("00000000-0000-0000-0000-000000000099"),
        callsign="W8O",
        started_at=datetime(2026, 7, 25, 2, 0, tzinfo=UTC),
    )
    legacy = contact_json(contact)
    for field in (
        "my_grid",
        "pota_reference",
        "grid_source",
        "enrichment_state",
    ):
        legacy.pop(field)

    write_document(source, [legacy], format_version=1)

    result = import_contacts_from_json(repository, source)
    restored = repository.get(contact.contact_id)

    assert result == ContactImportResult(imported=1, skipped=0)
    assert restored is not None
    assert restored.my_grid is None
    assert restored.pota_reference is None
    assert restored.grid_source is None
    assert restored.enrichment_state.value == "ready"


def test_import_rejects_unsupported_format_version(tmp_path: Path) -> None:
    """Unknown export formats must not be interpreted speculatively."""
    repository = ContactRepository(tmp_path / "contacts.db")
    source = tmp_path / "contacts.json"
    write_document(source, [], format_version=99)

    with pytest.raises(
        ContactImportError,
        match=r"Unsupported contact import format version: 99",
    ):
        import_contacts_from_json(repository, source)

    assert repository.list_all() == []


def test_import_rejects_invalid_json(tmp_path: Path) -> None:
    """Malformed JSON should produce an actionable import error."""
    repository = ContactRepository(tmp_path / "contacts.db")
    source = tmp_path / "contacts.json"
    source.write_text('{"contacts": [', encoding="utf-8")

    with pytest.raises(
        ContactImportError,
        match=r"not valid JSON",
    ):
        import_contacts_from_json(repository, source)


@pytest.mark.parametrize(
    "exported_at",
    [
        "not-a-date",
        "2026-07-25T03:00:00",
        123,
    ],
)
def test_import_rejects_invalid_export_timestamp(
    tmp_path: Path,
    exported_at: object,
) -> None:
    """Recovery metadata must contain a timezone-aware timestamp."""
    repository = ContactRepository(tmp_path / "contacts.db")
    source = tmp_path / "contacts.json"
    source.write_text(
        json.dumps(
            {
                "format_version": 1,
                "exported_at": exported_at,
                "contacts": [],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ContactImportError):
        import_contacts_from_json(repository, source)


def test_preview_contact_import_reports_new_contacts_without_writing(
    tmp_path: Path,
) -> None:
    """Preview should report importable contacts without storing them."""
    repository = ContactRepository(tmp_path / "contacts.db")
    source = tmp_path / "backup.json"
    contact = make_import_contact(
        contact_id=UUID("00000000-0000-0000-0000-000000000010"),
        callsign="K8ABC",
        started_at=datetime(2026, 7, 25, 2, 0, tzinfo=UTC),
    )
    write_document(source, [contact_json(contact)])

    result = preview_contact_import(repository, source)

    assert result.imported == 1
    assert result.skipped == 0
    assert result.conflicted == 0
    assert repository.get(contact.contact_id) is None


def test_preview_contact_import_reports_exact_duplicate(
    tmp_path: Path,
) -> None:
    """Preview should report an existing identical contact as skipped."""
    repository = ContactRepository(tmp_path / "contacts.db")
    contact = make_import_contact(
        contact_id=UUID("00000000-0000-0000-0000-000000000011"),
        callsign="W8O",
        started_at=datetime(2026, 7, 25, 2, 0, tzinfo=UTC),
    )
    repository.add(contact)
    source = tmp_path / "backup.json"
    write_document(source, [contact_json(contact)])

    result = preview_contact_import(repository, source)

    assert result.imported == 0
    assert result.skipped == 1
    assert result.conflicted == 0


def test_preview_contact_import_reports_uuid_conflict(
    tmp_path: Path,
) -> None:
    """Preview should report differing data with an existing UUID."""
    repository = ContactRepository(tmp_path / "contacts.db")
    existing = make_import_contact(
        contact_id=UUID("00000000-0000-0000-0000-000000000012"),
        callsign="K8ABC",
        started_at=datetime(2026, 7, 25, 2, 0, tzinfo=UTC),
    )
    repository.add(existing)
    source = tmp_path / "backup.json"
    conflicting = existing.model_copy(update={"callsign": "W8O"})
    write_document(source, [contact_json(conflicting)])

    result = preview_contact_import(repository, source)

    assert result.imported == 0
    assert result.skipped == 0
    assert result.conflicted == 1
    assert repository.get(existing.contact_id) == existing
