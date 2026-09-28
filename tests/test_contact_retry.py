"""Tests for persistent contact synchronization retry backoff."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from rolling_thunder.contact_repository import ContactRepository
from rolling_thunder.contact_retry import ContactRetryRepository
from rolling_thunder.domain import Contact, RadioMode, SynchronizationState


def contact(contact_id: UUID) -> Contact:
    return Contact(
        contact_id=contact_id,
        callsign="W8O",
        frequency_hz=14_250_000,
        mode=RadioMode.USB,
        started_at=datetime(2026, 7, 26, 20, 0, tzinfo=UTC),
        rst_sent="59",
        rst_received="59",
    )


def repositories(tmp_path: Path) -> tuple[ContactRepository, ContactRetryRepository]:
    database_path = tmp_path / "rolling-thunder.db"
    return ContactRepository(database_path), ContactRetryRepository(database_path)


def test_failure_backoff_doubles_and_caps(tmp_path: Path) -> None:
    contacts, retries = repositories(tmp_path)
    contact_id = uuid4()
    contacts.add(contact(contact_id))
    now = datetime(2026, 7, 26, 20, 0, tzinfo=UTC)

    first = retries.record_failure(
        contact_id,
        failed_at=now,
        error_message="offline",
        initial_delay_s=5,
        max_delay_s=12,
    )
    second = retries.record_failure(
        contact_id,
        failed_at=now,
        error_message="still offline",
        initial_delay_s=5,
        max_delay_s=12,
    )
    third = retries.record_failure(
        contact_id,
        failed_at=now,
        error_message="still offline",
        initial_delay_s=5,
        max_delay_s=12,
    )

    assert first.attempt_count == 1
    assert first.next_attempt_at == now + timedelta(seconds=5)
    assert second.attempt_count == 2
    assert second.next_attempt_at == now + timedelta(seconds=10)
    assert third.attempt_count == 3
    assert third.next_attempt_at == now + timedelta(seconds=12)


def test_due_retry_survives_repository_restart(tmp_path: Path) -> None:
    database_path = tmp_path / "rolling-thunder.db"
    contacts = ContactRepository(database_path)
    retries = ContactRetryRepository(database_path)
    contact_id = uuid4()
    contacts.add(contact(contact_id))
    contacts.update_synchronization_state(contact_id, SynchronizationState.FAILED)
    now = datetime(2026, 7, 26, 20, 0, tzinfo=UTC)
    retries.record_failure(
        contact_id,
        failed_at=now,
        error_message="offline",
        initial_delay_s=5,
        max_delay_s=60,
    )

    restarted = ContactRetryRepository(database_path)

    assert restarted.list_due_contact_ids(now + timedelta(seconds=4), limit=10) == []
    assert restarted.list_due_contact_ids(now + timedelta(seconds=5), limit=10) == [
        contact_id
    ]


def test_only_failed_contacts_are_retry_candidates(tmp_path: Path) -> None:
    contacts, retries = repositories(tmp_path)
    contact_id = uuid4()
    contacts.add(contact(contact_id))
    now = datetime(2026, 7, 26, 20, 0, tzinfo=UTC)
    retries.record_failure(
        contact_id,
        failed_at=now,
        error_message="offline",
        initial_delay_s=1,
        max_delay_s=60,
    )

    assert retries.list_due_contact_ids(now + timedelta(seconds=1), limit=10) == []

    contacts.update_synchronization_state(contact_id, SynchronizationState.FAILED)

    assert retries.list_due_contact_ids(now + timedelta(seconds=1), limit=10) == [
        contact_id
    ]


def test_clear_removes_retry_eligibility(tmp_path: Path) -> None:
    contacts, retries = repositories(tmp_path)
    contact_id = uuid4()
    contacts.add(contact(contact_id))
    contacts.update_synchronization_state(contact_id, SynchronizationState.FAILED)
    now = datetime(2026, 7, 26, 20, 0, tzinfo=UTC)
    retries.record_failure(
        contact_id,
        failed_at=now,
        error_message="offline",
        initial_delay_s=1,
        max_delay_s=60,
    )

    retries.clear(contact_id)

    assert retries.list_due_contact_ids(now + timedelta(seconds=10), limit=10) == []
