"""Tests for SQLite-backed contact persistence."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from rolling_thunder.contact_repository import (
    ContactAlreadyExistsError,
    ContactRepository,
)
from rolling_thunder.domain import Contact, RadioMode, SynchronizationState
from rolling_thunder.storage import StorageError

_DEFAULT_CONTACT_ID = UUID("00000000-0000-0000-0000-000000000001")
_DEFAULT_STARTED_AT = datetime(2026, 7, 25, 0, 30, tzinfo=UTC)


def make_contact(
    *,
    contact_id: UUID = _DEFAULT_CONTACT_ID,
    started_at: datetime = _DEFAULT_STARTED_AT,
    synchronization_state: SynchronizationState = SynchronizationState.FAILED,
) -> Contact:
    """Create a representative contact for repository tests."""
    return Contact(
        contact_id=contact_id,
        callsign="ki5vnb/p",
        frequency_hz=14_250_000,
        mode="usb",
        started_at=started_at,
        rst_sent="59",
        rst_received="57",
        grid="em79XM",
        notes="Mobile contact",
        synchronization_state=synchronization_state,
    )


def test_repository_initializes_database(tmp_path: Path) -> None:
    """Constructing a repository should prepare its database."""
    database_path = tmp_path / "nested" / "contacts.db"

    ContactRepository(database_path)

    assert database_path.is_file()


def test_repository_adds_and_retrieves_complete_contact(
    tmp_path: Path,
) -> None:
    """A stored contact should round-trip through the domain model."""
    repository = ContactRepository(tmp_path / "contacts.db")
    contact = make_contact()

    repository.add(contact)

    retrieved = repository.get(contact.contact_id)

    assert retrieved == contact
    assert retrieved is not contact
    assert retrieved is not None
    assert retrieved.callsign == "KI5VNB/P"
    assert retrieved.mode is RadioMode.USB
    assert retrieved.started_at == datetime(2026, 7, 25, 0, 30, tzinfo=UTC)
    assert retrieved.grid == "EM79xm"
    assert retrieved.synchronization_state is SynchronizationState.FAILED


def test_repository_write_is_durable_before_returning(tmp_path: Path) -> None:
    """A successful add should be visible through a new connection."""
    database_path = tmp_path / "contacts.db"
    repository = ContactRepository(database_path)
    contact = make_contact()

    repository.add(contact)

    with sqlite3.connect(database_path) as connection:
        result = connection.execute(
            """
            SELECT callsign
            FROM contacts
            WHERE contact_id = ?
            """,
            (str(contact.contact_id),),
        ).fetchone()

    assert result == ("KI5VNB/P",)


def test_repository_returns_none_for_missing_contact(tmp_path: Path) -> None:
    """Retrieving an unknown UUID should not be treated as an error."""
    repository = ContactRepository(tmp_path / "contacts.db")

    result = repository.get(
        UUID("00000000-0000-0000-0000-000000000999")
    )

    assert result is None


def test_repository_rejects_duplicate_contact_id(tmp_path: Path) -> None:
    """One UUID should identify exactly one stored contact."""
    repository = ContactRepository(tmp_path / "contacts.db")
    contact = make_contact()

    repository.add(contact)

    with pytest.raises(
        ContactAlreadyExistsError,
        match=str(contact.contact_id),
    ):
        repository.add(contact)


def test_repository_preserves_optional_null_values(tmp_path: Path) -> None:
    """Optional grid and notes values should round-trip as None."""
    repository = ContactRepository(tmp_path / "contacts.db")
    contact = Contact(
        contact_id=UUID("00000000-0000-0000-0000-000000000002"),
        callsign="W8O",
        frequency_hz=7_200_000,
        mode="LSB",
        started_at=datetime(2026, 7, 25, 1, 0, tzinfo=UTC),
        rst_sent="59",
        rst_received="59",
        grid=None,
        notes=None,
    )

    repository.add(contact)

    retrieved = repository.get(contact.contact_id)

    assert retrieved == contact
    assert retrieved is not None
    assert retrieved.grid is None
    assert retrieved.notes is None


def test_repository_reports_invalid_stored_contact(tmp_path: Path) -> None:
    """Corrupt stored values should not escape as an invalid domain model."""
    database_path = tmp_path / "contacts.db"
    repository = ContactRepository(database_path)
    contact = make_contact()
    repository.add(contact)

    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA ignore_check_constraints = ON")
        connection.execute(
            """
            UPDATE contacts
            SET mode = 'INVALID'
            WHERE contact_id = ?
            """,
            (str(contact.contact_id),),
        )
        connection.commit()

    with pytest.raises(
        StorageError,
        match=r"Stored contact is invalid",
    ):
        repository.get(contact.contact_id)


def test_repository_reports_unusable_database_path(tmp_path: Path) -> None:
    """Repository initialization should retain actionable storage errors."""
    database_path = tmp_path / "database-directory"
    database_path.mkdir()

    with pytest.raises(
        StorageError,
        match=r"Database could not be initialized",
    ):
        ContactRepository(database_path)


def test_repository_lists_empty_database(tmp_path: Path) -> None:
    """Listing an empty repository should return an empty list."""
    repository = ContactRepository(tmp_path / "contacts.db")

    assert repository.list_recent() == []


def test_repository_lists_newest_first_with_deterministic_ties(
    tmp_path: Path,
) -> None:
    """Contact ordering should be newest first and stable for equal times."""
    repository = ContactRepository(tmp_path / "contacts.db")

    oldest = make_contact(
        contact_id=UUID("00000000-0000-0000-0000-000000000003"),
        started_at=datetime(2026, 7, 25, 0, 10, tzinfo=UTC),
    )
    tied_second = make_contact(
        contact_id=UUID("00000000-0000-0000-0000-000000000002"),
        started_at=datetime(2026, 7, 25, 0, 40, tzinfo=UTC),
    )
    tied_first = make_contact(
        contact_id=UUID("00000000-0000-0000-0000-000000000001"),
        started_at=datetime(2026, 7, 25, 0, 40, tzinfo=UTC),
    )

    repository.add(oldest)
    repository.add(tied_second)
    repository.add(tied_first)

    contacts = repository.list_recent()

    assert [contact.contact_id for contact in contacts] == [
        tied_first.contact_id,
        tied_second.contact_id,
        oldest.contact_id,
    ]


def test_repository_applies_list_limit(tmp_path: Path) -> None:
    """Recent contact listing should honor the requested limit."""
    repository = ContactRepository(tmp_path / "contacts.db")

    for index in range(1, 4):
        repository.add(
            make_contact(
                contact_id=UUID(
                    f"00000000-0000-0000-0000-{index:012d}"
                ),
                started_at=datetime(
                    2026,
                    7,
                    25,
                    0,
                    index,
                    tzinfo=UTC,
                ),
            )
        )

    contacts = repository.list_recent(limit=2)

    assert len(contacts) == 2
    assert [contact.started_at.minute for contact in contacts] == [3, 2]


def test_repository_lists_by_synchronization_state(
    tmp_path: Path,
) -> None:
    """Synchronization listing should return only matching contacts."""
    repository = ContactRepository(tmp_path / "contacts.db")

    pending = make_contact(
        contact_id=UUID("00000000-0000-0000-0000-000000000010"),
        synchronization_state=SynchronizationState.PENDING,
    )
    synchronized = make_contact(
        contact_id=UUID("00000000-0000-0000-0000-000000000011"),
        synchronization_state=SynchronizationState.SYNCHRONIZED,
    )
    failed = make_contact(
        contact_id=UUID("00000000-0000-0000-0000-000000000012"),
        synchronization_state=SynchronizationState.FAILED,
    )

    repository.add(pending)
    repository.add(synchronized)
    repository.add(failed)

    contacts = repository.list_by_synchronization_state(
        SynchronizationState.PENDING
    )

    assert contacts == [pending]


@pytest.mark.parametrize("limit", [0, -1, 1_001])
def test_repository_rejects_invalid_list_limit(
    tmp_path: Path,
    limit: int,
) -> None:
    """Contact listing should reject unsafe or meaningless limits."""
    repository = ContactRepository(tmp_path / "contacts.db")

    with pytest.raises(
        ValueError,
        match=r"between 1 and 1000",
    ):
        repository.list_recent(limit=limit)


def test_repository_list_reports_invalid_stored_contact(
    tmp_path: Path,
) -> None:
    """Every listed database row should be validated as a domain contact."""
    database_path = tmp_path / "contacts.db"
    repository = ContactRepository(database_path)
    contact = make_contact()
    repository.add(contact)

    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA ignore_check_constraints = ON")
        connection.execute(
            """
            UPDATE contacts
            SET mode = 'INVALID'
            WHERE contact_id = ?
            """,
            (str(contact.contact_id),),
        )
        connection.commit()

    with pytest.raises(
        StorageError,
        match=r"Stored contact is invalid",
    ):
        repository.list_recent()


@pytest.mark.parametrize("limit", [True, 1.5, "10"])
def test_repository_rejects_non_integer_list_limit(
    tmp_path: Path,
    limit: object,
) -> None:
    """Contact listing should reject non-integer limit values."""
    repository = ContactRepository(tmp_path / "contacts.db")

    with pytest.raises(
        TypeError,
        match=r"must be an integer",
    ):
        repository.list_recent(limit=limit)  # type: ignore[arg-type]
