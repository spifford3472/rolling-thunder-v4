"""Tests for SQLite-backed contact persistence."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from rolling_thunder.contact_repository import (
    ContactAlreadyExistsError,
    ContactNotFoundError,
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


@pytest.mark.parametrize(
    "state",
    [
        SynchronizationState.SYNCHRONIZED,
        SynchronizationState.FAILED,
    ],
)
def test_repository_updates_synchronization_state(
    tmp_path: Path,
    state: SynchronizationState,
) -> None:
    """A synchronization transition should return the updated contact."""
    database_path = tmp_path / "contacts.db"
    repository = ContactRepository(database_path)
    contact = make_contact(
        synchronization_state=SynchronizationState.PENDING
    )
    repository.add(contact)

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            UPDATE contacts
            SET updated_at = '2000-01-01 00:00:00'
            WHERE contact_id = ?
            """,
            (str(contact.contact_id),),
        )
        connection.commit()

    updated = repository.update_synchronization_state(
        contact.contact_id,
        state,
    )

    assert updated.synchronization_state is state
    assert updated.contact_id == contact.contact_id
    assert updated.callsign == contact.callsign
    assert updated.frequency_hz == contact.frequency_hz
    assert updated.mode == contact.mode
    assert updated.started_at == contact.started_at
    assert updated.rst_sent == contact.rst_sent
    assert updated.rst_received == contact.rst_received
    assert updated.grid == contact.grid
    assert updated.notes == contact.notes

    with sqlite3.connect(database_path) as connection:
        stored = connection.execute(
            """
            SELECT synchronization_state, updated_at
            FROM contacts
            WHERE contact_id = ?
            """,
            (str(contact.contact_id),),
        ).fetchone()

    assert stored is not None
    assert stored[0] == state.value
    assert stored[1] != "2000-01-01 00:00:00"


def test_repository_state_update_changes_filter_results(
    tmp_path: Path,
) -> None:
    """A transitioned contact should move between synchronization queries."""
    repository = ContactRepository(tmp_path / "contacts.db")
    contact = make_contact(
        synchronization_state=SynchronizationState.PENDING
    )
    repository.add(contact)

    repository.update_synchronization_state(
        contact.contact_id,
        SynchronizationState.SYNCHRONIZED,
    )

    pending = repository.list_by_synchronization_state(
        SynchronizationState.PENDING
    )
    synchronized = repository.list_by_synchronization_state(
        SynchronizationState.SYNCHRONIZED
    )

    assert pending == []
    assert synchronized == [
        contact.model_copy(
            update={
                "synchronization_state": SynchronizationState.SYNCHRONIZED
            }
        )
    ]


def test_repository_state_update_reports_missing_contact(
    tmp_path: Path,
) -> None:
    """Updating an unknown contact should raise a specific storage error."""
    repository = ContactRepository(tmp_path / "contacts.db")
    contact_id = UUID("00000000-0000-0000-0000-000000000999")

    with pytest.raises(
        ContactNotFoundError,
        match=str(contact_id),
    ):
        repository.update_synchronization_state(
            contact_id,
            SynchronizationState.FAILED,
        )


@pytest.mark.parametrize("state", ["pending", None, 1])
def test_repository_state_update_rejects_invalid_state_type(
    tmp_path: Path,
    state: object,
) -> None:
    """Synchronization updates should require the domain enum type."""
    repository = ContactRepository(tmp_path / "contacts.db")

    with pytest.raises(
        TypeError,
        match=r"must be a SynchronizationState",
    ):
        repository.update_synchronization_state(
            _DEFAULT_CONTACT_ID,
            state,  # type: ignore[arg-type]
        )


def test_repository_lists_all_contacts_without_limit(tmp_path: Path) -> None:
    """Complete listing should not apply the bounded UI query limit."""
    repository = ContactRepository(tmp_path / "contacts.db")
    shared_time = datetime(2026, 7, 25, 2, 0, tzinfo=UTC)

    for index in range(1, 1_002):
        repository.add(
            make_contact(
                contact_id=UUID(
                    f"00000000-0000-0000-0000-{index:012d}"
                ),
                started_at=shared_time,
            )
        )

    contacts = repository.list_all()

    assert len(contacts) == 1_001
    assert contacts[0].contact_id == UUID(
        "00000000-0000-0000-0000-000000000001"
    )
    assert contacts[-1].contact_id == UUID(
        "00000000-0000-0000-0000-000000001001"
    )


def test_repository_atomically_updates_complete_contact(
    tmp_path: Path,
) -> None:
    """A complete replacement should persist every updated field."""
    repository = ContactRepository(tmp_path / "contacts.db")
    original = make_contact()
    repository.add(original)

    replacement = Contact(
        contact_id=original.contact_id,
        callsign="K8ABC",
        frequency_hz=7_255_000,
        mode=RadioMode.LSB,
        started_at=datetime(2026, 7, 25, 2, 30, tzinfo=UTC),
        rst_sent="59",
        rst_received="55",
        grid="EN80aa",
        notes="Corrected contact",
        synchronization_state=SynchronizationState.PENDING,
    )

    returned = repository.update(replacement)
    stored = repository.get(original.contact_id)

    assert returned == replacement
    assert stored == replacement
    assert returned is not replacement


def test_repository_update_preserves_contact_uuid(
    tmp_path: Path,
) -> None:
    """Updating a contact should retain its existing UUID."""
    repository = ContactRepository(tmp_path / "contacts.db")
    original = make_contact()
    repository.add(original)

    replacement = original.model_copy(
        update={
            "callsign": "K8ABC",
            "synchronization_state": SynchronizationState.PENDING,
        }
    )

    updated = repository.update(replacement)

    assert updated.contact_id == original.contact_id
    assert repository.get(original.contact_id) == updated


def test_repository_update_rejects_missing_contact(
    tmp_path: Path,
) -> None:
    """Updating an absent UUID should raise contact-not-found."""
    repository = ContactRepository(tmp_path / "contacts.db")
    contact = make_contact()

    with pytest.raises(
        ContactNotFoundError,
        match=f"Contact does not exist: {contact.contact_id}",
    ):
        repository.update(contact)


def test_repository_atomically_deletes_and_returns_contact(
    tmp_path: Path,
) -> None:
    """Deleting a stored UUID should return and remove its contact."""
    repository = ContactRepository(tmp_path / "contacts.db")
    contact = make_contact()
    repository.add(contact)

    deleted = repository.delete(contact.contact_id)

    assert deleted == contact
    assert deleted is not contact
    assert repository.get(contact.contact_id) is None


def test_repository_delete_does_not_affect_other_contacts(
    tmp_path: Path,
) -> None:
    """Deleting one contact should preserve all other records."""
    repository = ContactRepository(tmp_path / "contacts.db")
    deleted_contact = make_contact()
    retained_contact = make_contact(
        contact_id=UUID(
            "00000000-0000-0000-0000-000000000002"
        ),
        started_at=datetime(2026, 7, 25, 1, 30, tzinfo=UTC),
    )
    repository.add(deleted_contact)
    repository.add(retained_contact)

    repository.delete(deleted_contact.contact_id)

    assert repository.get(deleted_contact.contact_id) is None
    assert repository.get(retained_contact.contact_id) == retained_contact


def test_repository_delete_rejects_missing_contact(
    tmp_path: Path,
) -> None:
    """Deleting an absent UUID should raise contact-not-found."""
    repository = ContactRepository(tmp_path / "contacts.db")
    missing_id = UUID(
        "00000000-0000-0000-0000-000000000003"
    )

    with pytest.raises(
        ContactNotFoundError,
        match=f"Contact does not exist: {missing_id}",
    ):
        repository.delete(missing_id)
