"""Tests for the dashboard-facing contact logging application service."""

from datetime import UTC, datetime

import pytest

from rolling_thunder.contact_logging import ContactCommitError, ContactLoggingService
from rolling_thunder.domain import (
    Contact,
    Frequency,
    RadioConnectionState,
    RadioMode,
    RadioState,
    SynchronizationState,
)


class FixedClock:
    """Return one deterministic timestamp."""

    def __init__(self, value: datetime) -> None:
        self._value = value

    def now(self) -> datetime:
        return self._value


class RecordingRepository:
    """Record contacts without physical storage."""

    def __init__(self) -> None:
        self.contacts: list[Contact] = []

    def add(self, contact: Contact) -> None:
        self.contacts.append(contact)


class FailingRepository:
    """Simulate a durable storage failure."""

    def add(self, contact: Contact) -> None:
        raise RuntimeError(f"storage failed for {contact.callsign}")


def connected_radio_state(*, transmitting: bool = False) -> RadioState:
    """Build a valid connected radio snapshot."""
    return RadioState(
        connection_state=RadioConnectionState.CONNECTED,
        frequency=Frequency(hz=14_250_000),
        mode=RadioMode.USB,
        transmitting=transmitting,
        updated_at=datetime(2026, 7, 25, 14, 0, tzinfo=UTC),
    )


def test_commit_persists_normalized_contact_with_radio_state() -> None:
    """A successful Commit should persist exactly one complete local contact."""
    repository = RecordingRepository()
    started_at = datetime(2026, 7, 25, 14, 5, tzinfo=UTC)
    service = ContactLoggingService(repository, FixedClock(started_at))

    contact = service.commit(
        pending_callsign=" ki5vnb ",
        radio_state=connected_radio_state(),
    )

    assert repository.contacts == [contact]
    assert contact.callsign == "KI5VNB"
    assert contact.frequency_hz == 14_250_000
    assert contact.mode is RadioMode.USB
    assert contact.started_at == started_at
    assert contact.rst_sent == "59"
    assert contact.rst_received == "59"
    assert contact.synchronization_state is SynchronizationState.PENDING


def test_commit_supports_explicit_signal_reports() -> None:
    """Later UI workflows may provide reports without changing persistence logic."""
    repository = RecordingRepository()
    service = ContactLoggingService(repository)

    contact = service.commit(
        pending_callsign="GB90MGY",
        radio_state=connected_radio_state(),
        rst_sent="57",
        rst_received="59",
    )

    assert contact.rst_sent == "57"
    assert contact.rst_received == "59"


@pytest.mark.parametrize(
    ("callsign", "radio_state", "message"),
    [
        ("", connected_radio_state(), "No pending callsign"),
        (
            "KI5VNB",
            RadioState(
                connection_state=RadioConnectionState.DISCONNECTED,
                updated_at=datetime(2026, 7, 25, 14, 0, tzinfo=UTC),
            ),
            "radio must be connected",
        ),
        ("KI5VNB", connected_radio_state(transmitting=True), "while the radio is transmitting"),
    ],
)
def test_commit_rejects_unsafe_or_incomplete_state(
    callsign: str,
    radio_state: RadioState,
    message: str,
) -> None:
    """Commit must fail before persistence when operator or radio state is unsafe."""
    repository = RecordingRepository()
    service = ContactLoggingService(repository)

    with pytest.raises(ContactCommitError, match=message):
        service.commit(pending_callsign=callsign, radio_state=radio_state)

    assert repository.contacts == []


def test_storage_failure_is_not_reported_as_success() -> None:
    """A repository failure must propagate so pending state can remain available."""
    service = ContactLoggingService(FailingRepository())

    with pytest.raises(RuntimeError, match="storage failed for KI5VNB"):
        service.commit(
            pending_callsign="KI5VNB",
            radio_state=connected_radio_state(),
        )
