"""Tests for non-blocking dashboard contact commits."""

from datetime import UTC, datetime
from threading import Event

from rolling_thunder.contact_commit_controller import ContactCommitController
from rolling_thunder.contact_logging import ContactLoggingService
from rolling_thunder.domain import (
    Contact,
    Frequency,
    GPSFixState,
    GPSPosition,
    RadioConnectionState,
    RadioMode,
    RadioState,
)
from rolling_thunder.gps import GPSConnectionState, GPSState
from rolling_thunder.pota_spots import ParkReference, PotaSpot
from rolling_thunder.storage import StorageError


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 7, 25, 14, 0, tzinfo=UTC)


class BlockingRepository:
    def __init__(self) -> None:
        self.started = Event()
        self.release = Event()
        self.contacts: list[Contact] = []

    def add(self, contact: Contact) -> None:
        self.started.set()
        assert self.release.wait(timeout=2)
        self.contacts.append(contact)


class FailingRepository:
    def add(self, contact: Contact) -> None:
        del contact
        raise StorageError("database is unwritable")


def connected_radio() -> RadioState:
    return RadioState(
        connection_state=RadioConnectionState.CONNECTED,
        frequency=Frequency(hz=14_250_000),
        mode=RadioMode.USB,
        updated_at=datetime(2026, 7, 25, 14, 0, tzinfo=UTC),
    )


def test_controller_commits_once_and_reports_success() -> None:
    repository = BlockingRepository()
    succeeded = Event()
    callbacks: list[tuple[str, str]] = []
    controller = ContactCommitController(
        ContactLoggingService(repository, FixedClock()),
        on_started=lambda callsign: callbacks.append(("started", callsign)),
        on_succeeded=lambda callsign: (
            callbacks.append(("succeeded", callsign)),
            succeeded.set(),
        ),
        on_failed=lambda message: callbacks.append(("failed", message)),
    )

    assert controller.start_commit("ki5vnb", connected_radio()) is True
    assert repository.started.wait(timeout=2)
    assert controller.start_commit("W8O", connected_radio()) is False

    repository.release.set()
    assert succeeded.wait(timeout=2)

    assert [contact.callsign for contact in repository.contacts] == ["KI5VNB"]
    assert callbacks == [("started", "KI5VNB"), ("succeeded", "KI5VNB")]
    assert controller.status.committing is False
    assert controller.status.committed_contact is not None
    assert controller.status.last_error is None


def test_controller_snapshots_cached_gps_and_pota_context() -> None:
    repository = BlockingRepository()
    succeeded = Event()
    now = datetime(2026, 7, 25, 14, 0, tzinfo=UTC)
    position = GPSPosition(
        fix_state=GPSFixState.THREE_DIMENSIONAL,
        latitude=39.5309,
        longitude=-84.0866,
        altitude_m=250.0,
        updated_at=now,
    )
    gps_state = GPSState(
        connection_state=GPSConnectionState.CONNECTED,
        position=position,
        updated_at=now,
    )
    pota_spot = PotaSpot(
        activator="KI5VNB",
        park=ParkReference(
            reference="US-1234",
            latitude=40.0,
            longitude=-83.0,
        ),
        frequency=Frequency(hz=14_250_000),
        mode=RadioMode.USB,
        spotted_at=now,
    )
    controller = ContactCommitController(
        ContactLoggingService(repository, FixedClock()),
        on_started=lambda callsign: None,
        on_succeeded=lambda callsign: succeeded.set(),
        on_failed=lambda message: None,
        gps_state_provider=lambda: gps_state,
        pota_context_provider=lambda: True,
        pota_spots_provider=lambda: (pota_spot,),
    )

    assert controller.start_commit("KI5VNB", connected_radio()) is True
    assert repository.started.wait(timeout=2)
    repository.release.set()
    assert succeeded.wait(timeout=2)

    contact = repository.contacts[0]
    assert contact.my_grid == "EM79wm"
    assert contact.grid == "EN80ma"
    assert contact.pota_reference == "US-1234"


def test_controller_reports_storage_failure() -> None:
    failed = Event()
    messages: list[str] = []
    controller = ContactCommitController(
        ContactLoggingService(FailingRepository(), FixedClock()),
        on_started=lambda callsign: None,
        on_succeeded=lambda callsign: None,
        on_failed=lambda message: (messages.append(message), failed.set()),
    )

    assert controller.start_commit("KI5VNB", connected_radio()) is True
    assert failed.wait(timeout=2)

    assert messages == ["database is unwritable"]
    assert controller.status.committing is False
    assert controller.status.committed_contact is None
    assert controller.status.last_error == "database is unwritable"
