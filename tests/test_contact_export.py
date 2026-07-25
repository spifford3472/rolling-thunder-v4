"""Tests for deterministic atomic contact JSON export."""

import json
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from pathlib import Path
from uuid import UUID

import pytest

from rolling_thunder.contact_export import (
    CONTACT_EXPORT_FORMAT_VERSION,
    ContactExportError,
    export_contacts_to_json,
)
from rolling_thunder.contact_repository import ContactRepository
from rolling_thunder.domain import Contact, SynchronizationState


def make_export_contact(
    *,
    contact_id: UUID,
    callsign: str,
    started_at: datetime,
    synchronization_state: SynchronizationState,
    grid: str | None = None,
    notes: str | None = None,
) -> Contact:
    """Create a representative export contact."""
    return Contact(
        contact_id=contact_id,
        callsign=callsign,
        frequency_hz=14_250_000,
        mode="USB",
        started_at=started_at,
        rst_sent="59",
        rst_received="57",
        grid=grid,
        notes=notes,
        synchronization_state=synchronization_state,
    )


def test_export_writes_versioned_deterministic_json(tmp_path: Path) -> None:
    """Export should preserve complete contacts in newest-first order."""
    repository = ContactRepository(tmp_path / "contacts.db")
    destination = tmp_path / "exports" / "contacts.json"
    exported_at = datetime(2026, 7, 25, 2, 30, tzinfo=UTC)

    older = make_export_contact(
        contact_id=UUID("00000000-0000-0000-0000-000000000001"),
        callsign="W8O",
        started_at=datetime(2026, 7, 25, 1, 0, tzinfo=UTC),
        synchronization_state=SynchronizationState.PENDING,
    )
    newer = make_export_contact(
        contact_id=UUID("00000000-0000-0000-0000-000000000002"),
        callsign="KI5VNB/P",
        started_at=datetime(2026, 7, 25, 2, 0, tzinfo=UTC),
        synchronization_state=SynchronizationState.FAILED,
        grid="EM79xm",
        notes="Mobile contact",
    )

    repository.add(older)
    repository.add(newer)

    count = export_contacts_to_json(
        repository,
        destination,
        exported_at=exported_at,
    )

    document = json.loads(destination.read_text(encoding="utf-8"))

    assert count == 2
    assert document["format_version"] == CONTACT_EXPORT_FORMAT_VERSION
    assert document["exported_at"] == "2026-07-25T02:30:00Z"
    assert [
        contact["contact_id"]
        for contact in document["contacts"]
    ] == [
        str(newer.contact_id),
        str(older.contact_id),
    ]

    exported_newer = document["contacts"][0]
    assert exported_newer["callsign"] == "KI5VNB/P"
    assert exported_newer["mode"] == "USB"
    assert exported_newer["started_at"] == "2026-07-25T02:00:00Z"
    assert exported_newer["grid"] == "EM79xm"
    assert exported_newer["notes"] == "Mobile contact"
    assert exported_newer["synchronization_state"] == "failed"

    exported_older = document["contacts"][1]
    assert exported_older["grid"] is None
    assert exported_older["notes"] is None


def test_export_is_byte_deterministic_for_fixed_timestamp(
    tmp_path: Path,
) -> None:
    """Identical repository state and timestamp should produce identical bytes."""
    repository = ContactRepository(tmp_path / "contacts.db")
    first_destination = tmp_path / "first.json"
    second_destination = tmp_path / "second.json"
    exported_at = datetime(2026, 7, 25, 3, 0, tzinfo=UTC)

    repository.add(
        make_export_contact(
            contact_id=UUID("00000000-0000-0000-0000-000000000003"),
            callsign="W8O",
            started_at=datetime(2026, 7, 25, 2, 45, tzinfo=UTC),
            synchronization_state=SynchronizationState.SYNCHRONIZED,
        )
    )

    export_contacts_to_json(
        repository,
        first_destination,
        exported_at=exported_at,
    )
    export_contacts_to_json(
        repository,
        second_destination,
        exported_at=exported_at,
    )

    assert first_destination.read_bytes() == second_destination.read_bytes()


def test_export_normalizes_timestamp_to_utc(tmp_path: Path) -> None:
    """An aware non-UTC timestamp should be represented canonically in UTC."""
    repository = ContactRepository(tmp_path / "contacts.db")
    destination = tmp_path / "contacts.json"

    export_contacts_to_json(
        repository,
        destination,
        exported_at=datetime(
            2026,
            7,
            24,
            22,
            0,
            tzinfo=timezone_offset(-4),
        ),
    )

    document = json.loads(destination.read_text(encoding="utf-8"))

    assert document["exported_at"] == "2026-07-25T02:00:00Z"


def timezone_offset(hours: int) -> tzinfo:
    """Return a fixed timezone for timestamp-normalization tests."""
    return timezone(timedelta(hours=hours))


def test_export_rejects_naive_timestamp(tmp_path: Path) -> None:
    """Export metadata must never contain a timezone-ambiguous timestamp."""
    repository = ContactRepository(tmp_path / "contacts.db")

    with pytest.raises(
        ValueError,
        match=r"must include a timezone",
    ):
        export_contacts_to_json(
            repository,
            tmp_path / "contacts.json",
            exported_at=datetime(2026, 7, 25, 2, 30),  # noqa: DTZ001
        )


def test_export_rejects_directory_destination(tmp_path: Path) -> None:
    """A directory must not be mistaken for an export file."""
    repository = ContactRepository(tmp_path / "contacts.db")
    destination = tmp_path / "export-directory"
    destination.mkdir()

    with pytest.raises(
        ContactExportError,
        match=r"is a directory",
    ):
        export_contacts_to_json(repository, destination)


def test_export_atomically_replaces_existing_file(tmp_path: Path) -> None:
    """A completed export should replace the previous destination contents."""
    repository = ContactRepository(tmp_path / "contacts.db")
    destination = tmp_path / "contacts.json"
    destination.write_text("old contents", encoding="utf-8")

    export_contacts_to_json(
        repository,
        destination,
        exported_at=datetime(2026, 7, 25, 3, 0, tzinfo=UTC),
    )

    document = json.loads(destination.read_text(encoding="utf-8"))

    assert document["contacts"] == []
    assert list(tmp_path.glob(".contacts.json.*.tmp")) == []
