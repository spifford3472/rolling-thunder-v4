"""Tests for background persistence of immutable staged DMR contacts."""

from datetime import UTC, datetime
from pathlib import Path
from threading import Event, get_ident

from rolling_thunder.contact_repository import ContactRepository
from rolling_thunder.dmr_activity import DmrActivitySource, DmrCallIdentity
from rolling_thunder.dmr_commit import DmrContactCommitController
from rolling_thunder.dmr_selection import DmrStageOrigin, StagedDmrQso
from rolling_thunder.domain import Contact, RadioMode
from rolling_thunder.storage import StorageError


def _stage(*, callsign: str = "KC9KPJ") -> StagedDmrQso:
    started_at = datetime(2026, 8, 16, 0, 7, 8, 120_000, tzinfo=UTC)
    return StagedDmrQso(
        origin=DmrStageOrigin.CURRENT_AUDIO,
        identity=DmrCallIdentity(
            started_at=started_at,
            slot=1,
            source=DmrActivitySource.NETWORK,
            callsign=callsign,
            target="TG 3100",
        ),
        callsign=callsign,
        slot=1,
        target="TG 3100",
        talkgroup=3100,
        source=DmrActivitySource.NETWORK,
        started_at=started_at,
        ended_at=None,
        name=None,
        country=None,
        talker_alias=f"{callsign} Operator",
        duration_s=None,
        packet_loss_percent=None,
        ber_percent=None,
        radio_rx_hz=434_537_500,
        radio_tx_hz=439_537_500,
        my_grid="EM79xm",
    )


def test_worker_persists_frozen_dmr_contact_to_sqlite(tmp_path: Path) -> None:
    database_path = tmp_path / "contacts.db"
    repository = ContactRepository(database_path)
    succeeded = Event()
    staged = _stage()
    controller = DmrContactCommitController(
        repository,
        on_succeeded=lambda stage_id, contact: succeeded.set(),
    )

    assert controller.start_commit(staged)
    assert succeeded.wait(2.0)

    contacts = repository.list_recent()
    assert len(contacts) == 1
    contact = contacts[0]
    assert contact.callsign == "KC9KPJ"
    assert contact.frequency_hz == 439_537_500
    assert contact.mode is RadioMode.DMR
    assert contact.started_at == staged.started_at
    assert contact.my_grid == "EM79xm"
    assert contact.notes is not None
    assert "TG 3100" in contact.notes
    assert "TS1" in contact.notes
    assert "RX=434.537500 MHz" in contact.notes

    status = controller.status
    assert not status.committing
    assert status.committed_stage_id == staged.stage_id
    assert status.committed_contact == contact
    assert status.last_error is None


class RecordingWriter:
    def __init__(self) -> None:
        self.contacts: list[Contact] = []
        self.thread_ids: list[int] = []
        self.completed = Event()

    def add(self, contact: Contact) -> None:
        self.thread_ids.append(get_ident())
        self.contacts.append(contact)
        self.completed.set()


def test_writer_runs_off_the_calling_thread() -> None:
    writer = RecordingWriter()
    controller = DmrContactCommitController(writer)
    caller_thread = get_ident()

    assert controller.start_commit(_stage())
    assert writer.completed.wait(2.0)

    assert writer.thread_ids
    assert writer.thread_ids[0] != caller_thread


class BlockingWriter:
    def __init__(self) -> None:
        self.entered = Event()
        self.release = Event()
        self.completed = Event()
        self.contacts: list[Contact] = []

    def add(self, contact: Contact) -> None:
        self.entered.set()
        assert self.release.wait(2.0)
        self.contacts.append(contact)
        self.completed.set()


def test_second_commit_is_rejected_while_worker_is_busy() -> None:
    writer = BlockingWriter()
    controller = DmrContactCommitController(writer)

    assert controller.start_commit(_stage(callsign="KC9KPJ"))
    assert writer.entered.wait(2.0)
    assert not controller.start_commit(_stage(callsign="W3GSI"))

    writer.release.set()
    assert writer.completed.wait(2.0)
    assert len(writer.contacts) == 1


def test_successful_stage_cannot_be_committed_twice() -> None:
    writer = RecordingWriter()
    staged = _stage()
    controller = DmrContactCommitController(writer)

    assert controller.start_commit(staged)
    assert writer.completed.wait(2.0)
    assert not controller.start_commit(staged)
    assert len(writer.contacts) == 1


class FlakyWriter:
    def __init__(self) -> None:
        self.fail = True
        self.failed = Event()
        self.succeeded = Event()
        self.contacts: list[Contact] = []

    def add(self, contact: Contact) -> None:
        if self.fail:
            self.failed.set()
            raise StorageError("simulated SQLite failure")
        self.contacts.append(contact)
        self.succeeded.set()


def test_failed_stage_can_be_retried_without_changing_frozen_values() -> None:
    writer = FlakyWriter()
    staged = _stage()
    failures: list[tuple[object, str]] = []
    controller = DmrContactCommitController(
        writer,
        on_failed=lambda stage_id, message: failures.append((stage_id, message)),
    )

    assert controller.start_commit(staged)
    assert writer.failed.wait(2.0)

    failed_status = controller.status
    assert not failed_status.committing
    assert failed_status.committed_contact is None
    assert failed_status.last_error == "simulated SQLite failure"
    assert failures == [(staged.stage_id, "simulated SQLite failure")]

    writer.fail = False
    assert controller.start_commit(staged)
    assert writer.succeeded.wait(2.0)
    assert len(writer.contacts) == 1
    assert writer.contacts[0].callsign == staged.callsign
    assert writer.contacts[0].frequency_hz == staged.radio_tx_hz
    assert writer.contacts[0].my_grid == staged.my_grid
