"""Tests for the mobile LOG panel background state and retention policy."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event

from rolling_thunder.contact_sync import ContactSyncResult
from rolling_thunder.domain import SynchronizationState
from rolling_thunder.log_panel import ContactLogRepository, LogPanelController
from rolling_thunder.radio_polling import PollCallback
from rolling_thunder.storage import initialize_database


class ManualScheduledPoll:
    def __init__(self, callback: PollCallback) -> None:
        self.callback = callback
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True

    def fire(self) -> None:
        if not self.cancelled:
            self.callback()


class ManualScheduler:
    def __init__(self) -> None:
        self.poll: ManualScheduledPoll | None = None

    def schedule_repeating(self, interval_s: float, callback: PollCallback) -> ManualScheduledPoll:
        assert interval_s > 0
        self.poll = ManualScheduledPoll(callback)
        return self.poll


class BlockingSync:
    def __init__(self) -> None:
        self.started = Event()
        self.release = Event()
        self.calls = 0

    def synchronize_now(self) -> ContactSyncResult:
        self.calls += 1
        self.started.set()
        self.release.wait(timeout=2)
        return ContactSyncResult(attempted=1, synchronized=1, failed=0)


def insert_contact(
    database: Path,
    *,
    contact_id: str,
    started_at: datetime,
    callsign: str = "W1AW",
    synchronization_state: SynchronizationState = SynchronizationState.SYNCHRONIZED,
) -> None:
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            INSERT INTO contacts (
                contact_id, callsign, frequency_hz, mode, started_at,
                rst_sent, rst_received, synchronization_state
            ) VALUES (?, ?, ?, 'USB', ?, '59', '59', ?)
            """,
            (
                contact_id,
                callsign,
                14_250_000,
                started_at.isoformat().replace("+00:00", "Z"),
                synchronization_state.value,
            ),
        )
        connection.commit()


def test_panel_snapshot_is_latest_ten_newest_first_with_counts(tmp_path: Path) -> None:
    database = tmp_path / "rolling.db"
    initialize_database(database)
    start = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
    for index in range(12):
        insert_contact(
            database,
            contact_id=f"00000000-0000-0000-0000-{index:012d}",
            started_at=start + timedelta(minutes=index),
            callsign="W1AW" if index % 2 == 0 else "DL1ABC",
            synchronization_state=(
                SynchronizationState.PENDING if index in {10, 11} else SynchronizationState.SYNCHRONIZED
            ),
        )

    snapshot = ContactLogRepository(database).read_panel_state()

    assert len(snapshot.rows) == 10
    assert snapshot.rows[0].started_at == start + timedelta(minutes=11)
    assert snapshot.rows[-1].started_at == start + timedelta(minutes=2)
    assert snapshot.rows[0].callsign == "DL1ABC"
    assert snapshot.rows[0].band == "20M"
    assert snapshot.rows[0].country == "DEU"
    assert snapshot.rows[1].country == "USA"
    assert snapshot.rows[0].status_text == "○ WAIT"
    assert snapshot.unsynchronized_count == 2
    assert snapshot.total_count == 12
    assert snapshot.summary_text == "UNSYNCED 2 / TOTAL 12"


def test_retention_prunes_oldest_1000_synchronized_only(tmp_path: Path) -> None:
    database = tmp_path / "rolling.db"
    initialize_database(database)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    with sqlite3.connect(database) as connection:
        rows = []
        for index in range(5_001):
            state = "pending" if index in {0, 1} else "synchronized"
            rows.append(
                (
                    f"00000000-0000-0000-0001-{index:012d}",
                    f"K{index % 9 + 1}ABC",
                    14_250_000,
                    "USB",
                    (base + timedelta(minutes=index)).isoformat().replace("+00:00", "Z"),
                    "59",
                    "59",
                    state,
                )
            )
        connection.executemany(
            """
            INSERT INTO contacts (
                contact_id, callsign, frequency_hz, mode, started_at,
                rst_sent, rst_received, synchronization_state
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        connection.commit()

    repository = ContactLogRepository(database)
    pruned = repository.prune_synchronized_contacts()
    state = repository.read_panel_state()

    assert pruned == 1_000
    assert state.total_count == 4_001
    assert state.unsynchronized_count == 2
    with sqlite3.connect(database) as connection:
        pending = connection.execute(
            "SELECT contact_id FROM contacts WHERE synchronization_state='pending' ORDER BY contact_id"
        ).fetchall()
    assert pending == [
        ("00000000-0000-0000-0001-000000000000",),
        ("00000000-0000-0000-0001-000000000001",),
    ]


def test_retention_deletes_only_available_synchronized_records(tmp_path: Path) -> None:
    database = tmp_path / "rolling.db"
    initialize_database(database)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for index in range(5_001):
        insert_contact(
            database,
            contact_id=f"00000000-0000-0000-0002-{index:012d}",
            started_at=base + timedelta(seconds=index),
            synchronization_state=(
                SynchronizationState.SYNCHRONIZED
                if index < 10
                else SynchronizationState.FAILED
            ),
        )

    repository = ContactLogRepository(database)
    assert repository.prune_synchronized_contacts() == 10
    snapshot = repository.read_panel_state()
    assert snapshot.total_count == 4_991
    assert snapshot.unsynchronized_count == 4_991


def test_manual_sync_request_is_nonblocking_and_single_flight(tmp_path: Path) -> None:
    database = tmp_path / "rolling.db"
    initialize_database(database)
    sync = BlockingSync()
    controller = LogPanelController(
        ContactLogRepository(database),
        sync,
        scheduler=ManualScheduler(),
    )
    controller.start()

    assert controller.request_sync() is True
    assert sync.started.wait(timeout=1)
    assert controller.latest_state.syncing is True
    assert controller.request_sync() is False
    assert sync.calls == 1

    sync.release.set()
    controller.stop()
