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
from rolling_thunder.domain import (
    Contact,
    ContactEnrichmentState,
    ContactGridSource,
    ContactSource,
    ContactWeatherObservation,
    RadioMode,
    SynchronizationState,
)
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
        grid="en80AA",
        contact_latitude=41.25,
        contact_longitude=-82.75,
        my_grid="em79XM",
        pota_reference="us-1234",
        grid_source="pota_park",
        enrichment_state="ready",
        source="pota",
        tx_power_watts=55,
        contact_weather=ContactWeatherObservation(summary="Clear, 61 F"),
        local_weather=ContactWeatherObservation(summary="Cloudy, 58 F"),
        weather_notes_enabled=True,
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
    assert retrieved.grid == "EN80aa"
    assert (retrieved.contact_latitude, retrieved.contact_longitude) == (41.25, -82.75)
    assert retrieved.my_grid == "EM79xm"
    assert retrieved.pota_reference == "US-1234"
    assert retrieved.grid_source is ContactGridSource.POTA_PARK
    assert retrieved.enrichment_state is ContactEnrichmentState.READY
    assert retrieved.source is ContactSource.POTA
    assert retrieved.tx_power_watts == 55
    assert retrieved.contact_weather == ContactWeatherObservation(summary="Clear, 61 F")
    assert retrieved.local_weather == ContactWeatherObservation(summary="Cloudy, 58 F")
    assert retrieved.weather_notes_enabled
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

    result = repository.get(UUID("00000000-0000-0000-0000-000000000999"))

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
    assert retrieved.my_grid is None
    assert retrieved.pota_reference is None
    assert retrieved.grid_source is None
    assert retrieved.enrichment_state is ContactEnrichmentState.READY
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


def test_repository_list_since_filters_by_utc_start_and_mode(
    tmp_path: Path,
) -> None:
    repository = ContactRepository(tmp_path / "contacts.db")
    before = make_contact(
        contact_id=UUID("00000000-0000-0000-0000-000000000021"),
        started_at=datetime(2026, 10, 1, 23, 59, tzinfo=UTC),
    )
    ft8_today = Contact(
        contact_id=UUID("00000000-0000-0000-0000-000000000022"),
        callsign="K1ABC",
        frequency_hz=14_074_000,
        mode=RadioMode.FT8,
        started_at=datetime(2026, 10, 2, 0, 1, tzinfo=UTC),
        rst_sent="-10",
        rst_received="-08",
        my_grid="EM79xm",
        grid="FN31",
    )
    usb_today = make_contact(
        contact_id=UUID("00000000-0000-0000-0000-000000000023"),
        started_at=datetime(2026, 10, 2, 0, 2, tzinfo=UTC),
    )
    repository.add(before)
    repository.add(ft8_today)
    repository.add(usb_today)

    contacts = repository.list_since(
        datetime(2026, 10, 2, 0, 0, tzinfo=UTC),
        mode=RadioMode.FT8,
    )

    assert contacts == [ft8_today]


def test_repository_list_since_requires_timezone_aware_start(
    tmp_path: Path,
) -> None:
    repository = ContactRepository(tmp_path / "contacts.db")

    with pytest.raises(ValueError, match="timezone-aware"):
        repository.list_since(
            datetime(2026, 10, 2, 0, 0, tzinfo=UTC).replace(tzinfo=None)
        )


def test_repository_applies_list_limit(tmp_path: Path) -> None:
    """Recent contact listing should honor the requested limit."""
    repository = ContactRepository(tmp_path / "contacts.db")

    for index in range(1, 4):
        repository.add(
            make_contact(
                contact_id=UUID(f"00000000-0000-0000-0000-{index:012d}"),
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

    contacts = repository.list_by_synchronization_state(SynchronizationState.PENDING)

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
    contact = make_contact(synchronization_state=SynchronizationState.PENDING)
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
    assert updated.my_grid == contact.my_grid
    assert updated.pota_reference == contact.pota_reference
    assert updated.grid_source == contact.grid_source
    assert updated.enrichment_state == contact.enrichment_state
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
    contact = make_contact(synchronization_state=SynchronizationState.PENDING)
    repository.add(contact)

    repository.update_synchronization_state(
        contact.contact_id,
        SynchronizationState.SYNCHRONIZED,
    )

    pending = repository.list_by_synchronization_state(SynchronizationState.PENDING)
    synchronized = repository.list_by_synchronization_state(SynchronizationState.SYNCHRONIZED)

    assert pending == []
    assert synchronized == [
        contact.model_copy(update={"synchronization_state": SynchronizationState.SYNCHRONIZED})
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
                contact_id=UUID(f"00000000-0000-0000-0000-{index:012d}"),
                started_at=shared_time,
            )
        )

    contacts = repository.list_all()

    assert len(contacts) == 1_001
    assert contacts[0].contact_id == UUID("00000000-0000-0000-0000-000000000001")
    assert contacts[-1].contact_id == UUID("00000000-0000-0000-0000-000000001001")


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
        contact_id=UUID("00000000-0000-0000-0000-000000000002"),
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
    missing_id = UUID("00000000-0000-0000-0000-000000000003")

    with pytest.raises(
        ContactNotFoundError,
        match=f"Contact does not exist: {missing_id}",
    ):
        repository.delete(missing_id)


def test_repository_lists_only_synchronization_ready_contacts(
    tmp_path: Path,
) -> None:
    repository = ContactRepository(tmp_path / "contacts.db")
    ready = make_contact(
        contact_id=UUID("00000000-0000-0000-0000-000000000101"),
        synchronization_state=SynchronizationState.PENDING,
    )
    pending_qrz = Contact.model_validate(
        {
            **make_contact(
                contact_id=UUID("00000000-0000-0000-0000-000000000102"),
                synchronization_state=SynchronizationState.PENDING,
            ).model_dump(mode="python"),
                "grid": None,
                "contact_latitude": None,
                "contact_longitude": None,
                "grid_source": None,
            "enrichment_state": ContactEnrichmentState.PENDING_QRZ,
        }
    )
    repository.add(ready)
    repository.add(pending_qrz)

    eligible = repository.list_synchronization_eligible(SynchronizationState.PENDING)

    assert eligible == [ready]


def test_repository_lists_contacts_by_enrichment_state(
    tmp_path: Path,
) -> None:
    repository = ContactRepository(tmp_path / "contacts.db")
    pending = Contact.model_validate(
        {
            **make_contact(contact_id=UUID("00000000-0000-0000-0000-000000000103")).model_dump(
                mode="python"
            ),
            "grid": None,
            "contact_latitude": None,
            "contact_longitude": None,
            "grid_source": None,
            "enrichment_state": ContactEnrichmentState.PENDING_QRZ,
        }
    )
    repository.add(pending)

    contacts = repository.list_by_enrichment_state(ContactEnrichmentState.PENDING_QRZ)

    assert contacts == [pending]


def test_repository_completes_qrz_enrichment_atomically(
    tmp_path: Path,
) -> None:
    repository = ContactRepository(tmp_path / "contacts.db")
    pending = Contact.model_validate(
        {
            **make_contact(contact_id=UUID("00000000-0000-0000-0000-000000000104")).model_dump(
                mode="python"
            ),
            "grid": None,
            "contact_latitude": None,
            "contact_longitude": None,
            "grid_source": None,
            "enrichment_state": ContactEnrichmentState.PENDING_QRZ,
        }
    )
    repository.add(pending)

    completed = repository.complete_enrichment(
        pending.contact_id,
        grid="EN80aa",
        grid_source=ContactGridSource.QRZ,
    )

    assert completed.grid == "EN80aa"
    assert completed.grid_source is ContactGridSource.QRZ
    assert completed.enrichment_state is ContactEnrichmentState.READY
    assert completed.my_grid == pending.my_grid
    assert completed.pota_reference == pending.pota_reference
    assert completed.notes == pending.notes
    assert completed.synchronization_state == pending.synchronization_state


def test_repository_completes_unsuccessful_enrichment_without_grid(
    tmp_path: Path,
) -> None:
    repository = ContactRepository(tmp_path / "contacts.db")
    pending = Contact(
        contact_id=UUID("00000000-0000-0000-0000-000000000105"),
        callsign="W8O",
        frequency_hz=14_250_000,
        mode=RadioMode.USB,
        started_at=_DEFAULT_STARTED_AT,
        rst_sent="59",
        rst_received="59",
        enrichment_state=ContactEnrichmentState.PENDING_QRZ,
    )
    repository.add(pending)

    completed = repository.complete_enrichment(
        pending.contact_id,
        grid=None,
        grid_source=None,
    )

    assert completed.grid is None
    assert completed.grid_source is None
    assert completed.enrichment_state is ContactEnrichmentState.READY


def test_repository_recovery_preserves_contact_enrichment_fields(
    tmp_path: Path,
) -> None:
    """Recovery must retain station, contacted-grid, and POTA metadata."""
    repository = ContactRepository(tmp_path / "contacts.db")
    recovered_contact = make_contact(
        contact_id=UUID("00000000-0000-0000-0000-000000000106"),
        synchronization_state=SynchronizationState.PENDING,
    )

    result = repository.recover_contacts([recovered_contact])

    assert result == (1, 0)
    assert repository.get(recovered_contact.contact_id) == recovered_contact
