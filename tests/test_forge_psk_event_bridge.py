"""Offline safety tests for joining confirmed Forge FT8 records."""

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest

from rolling_thunder.domain import Contact, ContactSource, RadioMode
from rolling_thunder.forge_contact_snapshots import ForgeContactSnapshotRepository
from rolling_thunder.forge_ft8_performance import ForgeFT8PerformanceRepository
from rolling_thunder.forge_psk_event_bridge import (
    ForgePskBridgeError,
    candidate_events,
    enqueue_confirmed_events,
)
from rolling_thunder.forge_pskreporter_orchestration import (
    PskReporterOrchestrationRepository,
)
from rolling_thunder.ft8.performance import FT8AttemptOutcome, FT8PerformanceAttempt

IDENTIFIER = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
START = datetime(2026, 10, 9, 13, 0, tzinfo=UTC)


def seed(tmp_path: Path, *, sync: bool = True, snapshot: bool = True) -> tuple[Path, Path, Path]:
    source = tmp_path / "contact-sync.db"
    snapshots = tmp_path / "snapshots.db"
    queue = tmp_path / "queue.db"
    ForgeFT8PerformanceRepository(source).persist(
        FT8PerformanceAttempt(
            attempt_id=IDENTIFIER,
            callsign="K1ABC",
            outcome=FT8AttemptOutcome.COMPLETED,
            success=True,
            terminal_state="completed",
            started_at_utc=START,
            ended_at_utc=START + timedelta(minutes=2),
            utc_date=START.date(),
            dial_frequency_hz=14074000,
            remote_grid="FN42",
        )
    )
    with sqlite3.connect(source) as db:
        db.execute(
            "CREATE TABLE forge_contact_sync_ledger (contact_id TEXT PRIMARY KEY,state TEXT)"
        )
        if sync:
            db.execute(
                "INSERT INTO forge_contact_sync_ledger VALUES (?,?)",
                (str(IDENTIFIER), "synchronized"),
            )
    store = ForgeContactSnapshotRepository(snapshots)
    if snapshot:
        store.record(
            Contact(
                contact_id=IDENTIFIER,
                callsign="K1ABC",
                frequency_hz=14074000,
                mode=RadioMode.FT8,
                source=ContactSource.FT8,
                started_at=START,
                rst_sent="-09",
                rst_received="-12",
                my_grid="EM79xm",
                grid="FN42",
            )
        )
    return source, snapshots, queue


def test_readonly_dry_run_does_not_create_queue(tmp_path: Path) -> None:
    source, snapshots, queue = seed(tmp_path)
    assert (
        len(candidate_events(contact_sync_database=source, contact_snapshot_database=snapshots))
        == 1
    )
    assert enqueue_confirmed_events(
        contact_sync_database=source,
        contact_snapshot_database=snapshots,
        orchestration_database=queue,
    ) == (1, 0)
    assert not queue.exists()


def test_enqueue_replays_without_duplicates(tmp_path: Path) -> None:
    source, snapshots, queue = seed(tmp_path)
    kwargs = {
        "contact_sync_database": source,
        "contact_snapshot_database": snapshots,
        "orchestration_database": queue,
        "now_utc": START + timedelta(minutes=20),
        "dry_run": False,
    }
    assert enqueue_confirmed_events(**kwargs) == (1, 1)
    assert enqueue_confirmed_events(**kwargs) == (1, 1)
    assert (
        PskReporterOrchestrationRepository(queue)
        .health(
            now_utc=START + timedelta(minutes=20),
            enabled=False,
            minimum_interval=timedelta(minutes=10),
        )
        .pending_count
        == 1
    )


def test_only_synchronized_and_snapshotted(tmp_path: Path) -> None:
    source, snapshots, _ = seed(tmp_path, sync=False)
    assert candidate_events(contact_sync_database=source, contact_snapshot_database=snapshots) == ()


def test_mismatched_payload_fails_closed(tmp_path: Path) -> None:
    source, snapshots, queue = seed(tmp_path)
    with sqlite3.connect(snapshots) as db:
        db.execute(
            "UPDATE synchronized_contact_snapshots SET contact_json=?",
            ('{"contact_id":"bad"}',),
        )
    with pytest.raises(ForgePskBridgeError):
        enqueue_confirmed_events(
            contact_sync_database=source,
            contact_snapshot_database=snapshots,
            orchestration_database=queue,
            dry_run=False,
        )
    assert not queue.exists()
