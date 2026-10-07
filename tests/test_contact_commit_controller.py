"""Tests for non-blocking dashboard contact commits."""

from datetime import UTC, datetime
from threading import Event

from rolling_thunder.contact_commit_controller import ContactCommitController
from rolling_thunder.contact_logging import ContactLoggingService
from rolling_thunder.domain import (
    Contact,
    ContactSource,
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


class RecordingPotaWorkedTracker:
    def __init__(self) -> None:
        self.records: list[tuple[Contact, tuple[PotaSpot, ...]]] = []

    def record_contact(
        self,
        contact: Contact,
        pota_spots: tuple[PotaSpot, ...],
    ) -> None:
        self.records.append((contact, pota_spots))


class RecordingDxWorkedTracker:
    def __init__(self) -> None:
        self.records: list[Contact] = []

    def record_contact(self, contact: Contact) -> None:
        self.records.append(contact)


def test_controller_records_worked_pota_only_after_durable_commit() -> None:
    repository = BlockingRepository()
    succeeded = Event()
    tracker = RecordingPotaWorkedTracker()
    now = datetime(2026, 7, 25, 14, 0, tzinfo=UTC)
    pota_spot = PotaSpot(
        activator="KI5VNB",
        park=ParkReference(reference="US-1234"),
        frequency=Frequency(hz=14_250_000),
        mode=RadioMode.USB,
        spot_mode="SSB",
        spotted_at=now,
    )
    controller = ContactCommitController(
        ContactLoggingService(repository, FixedClock()),
        on_started=lambda callsign: None,
        on_succeeded=lambda callsign: succeeded.set(),
        on_failed=lambda message: None,
        pota_context_provider=lambda: True,
        pota_spots_provider=lambda: (pota_spot,),
        pota_worked_tracker=tracker,
        tx_power_provider=lambda: 55,
        weather_notes_enabled=True,
    )

    assert controller.start_commit("KI5VNB", connected_radio()) is True
    assert repository.started.wait(timeout=2)
    assert tracker.records == []

    repository.release.set()
    assert succeeded.wait(timeout=2)

    assert len(tracker.records) == 1
    committed, spots = tracker.records[0]
    assert committed.pota_reference == "US-1234"
    assert committed.source is ContactSource.POTA
    assert committed.tx_power_watts == 55
    assert committed.weather_notes_enabled
    assert spots == (pota_spot,)


def test_controller_records_worked_dx_only_after_durable_commit() -> None:
    repository = BlockingRepository()
    succeeded = Event()
    tracker = RecordingDxWorkedTracker()
    controller = ContactCommitController(
        ContactLoggingService(repository, FixedClock()),
        on_started=lambda callsign: None,
        on_succeeded=lambda callsign: succeeded.set(),
        on_failed=lambda message: None,
        dx_context_provider=lambda: True,
        dx_worked_tracker=tracker,
    )

    assert controller.start_commit("KI5VNB", connected_radio()) is True
    assert repository.started.wait(timeout=2)
    assert tracker.records == []

    repository.release.set()
    assert succeeded.wait(timeout=2)

    assert [str(contact.callsign) for contact in tracker.records] == ["KI5VNB"]
    assert tracker.records[0].source is ContactSource.DX


def test_controller_does_not_record_worked_dx_after_failed_commit() -> None:
    failed = Event()
    tracker = RecordingDxWorkedTracker()
    controller = ContactCommitController(
        ContactLoggingService(FailingRepository(), FixedClock()),
        on_started=lambda callsign: None,
        on_succeeded=lambda callsign: None,
        on_failed=lambda message: failed.set(),
        dx_context_provider=lambda: True,
        dx_worked_tracker=tracker,
    )

    assert controller.start_commit("KI5VNB", connected_radio()) is True
    assert failed.wait(timeout=2)

    assert tracker.records == []


def test_controller_adds_browse_mobile_contact_note_from_current_gps() -> None:
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
    controller = ContactCommitController(
        ContactLoggingService(repository, FixedClock()),
        on_started=lambda callsign: None,
        on_succeeded=lambda callsign: succeeded.set(),
        on_failed=lambda message: None,
        gps_state_provider=lambda: gps_state,
        browse_context_provider=lambda: True,
    )

    assert controller.start_commit("KI5VNB", connected_radio()) is True
    assert repository.started.wait(timeout=2)
    repository.release.set()
    assert succeeded.wait(timeout=2)

    contact = repository.contacts[0]
    assert contact.notes == "Mobile Contact from 39.530900, -84.086600 (EM79wm)"
    assert contact.source is ContactSource.BROWSE
    assert contact.my_grid == "EM79wm"
    assert contact.pota_reference is None


def test_worker_uses_snapshot_when_gps_provider_moves() -> None:
    repository = BlockingRepository()
    succeeded = Event()
    now = FixedClock().now()
    current = GPSState(
        connection_state=GPSConnectionState.CONNECTED,
        position=GPSPosition(
            fix_state=GPSFixState.THREE_DIMENSIONAL,
            latitude=39.5309,
            longitude=-84.0866,
            updated_at=now,
        ),
        updated_at=now,
    )
    calls = 0

    def provider() -> GPSState:
        nonlocal calls
        calls += 1
        return current

    def move_before_worker(callsign: str) -> None:
        nonlocal current
        current = GPSState(
            connection_state=GPSConnectionState.CONNECTED,
            position=GPSPosition(
                fix_state=GPSFixState.THREE_DIMENSIONAL,
                latitude=40.0,
                longitude=-83.0,
                updated_at=now,
            ),
            updated_at=now,
        )

    controller = ContactCommitController(
        ContactLoggingService(repository, FixedClock()),
        on_started=move_before_worker,
        on_succeeded=lambda callsign: succeeded.set(),
        on_failed=lambda message: None,
        gps_state_provider=provider,
    )
    try:
        assert controller.start_commit("K1ABC", connected_radio())
        assert repository.started.wait(timeout=2)
    finally:
        repository.release.set()
    assert succeeded.wait(timeout=2)
    assert calls == 1
    assert current.position is not None and current.position.latitude == 40.0
    assert (repository.contacts[0].my_latitude, repository.contacts[0].my_longitude) == (
        39.5309,
        -84.0866,
    )
