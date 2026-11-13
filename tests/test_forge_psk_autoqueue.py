"""Provider-free bounded and restart-safe queue automation tests."""

from datetime import timedelta
from pathlib import Path

import pytest
from test_forge_psk_event_bridge import START, seed

from rolling_thunder.forge_psk_autoqueue import AutoQueueError, run_once, unqueued_events
from rolling_thunder.forge_pskreporter_orchestration import PskReporterOrchestrationRepository


def config(tmp_path: Path) -> dict[str, Path]:
    source, snapshots, queue = seed(tmp_path)
    PskReporterOrchestrationRepository(queue)
    return {"sync_database": source, "snapshot_database": snapshots, "queue_database": queue}


def test_dry_run_is_readonly_and_no_provider(tmp_path: Path) -> None:
    kwargs = config(tmp_path)
    original = kwargs["queue_database"].read_bytes()
    assert run_once(**kwargs) == (1, 0)
    assert kwargs["queue_database"].read_bytes() == original


def test_restart_safe_dedupe_and_no_oldest_starvation(tmp_path: Path) -> None:
    kwargs = config(tmp_path)
    assert run_once(**kwargs, enqueue_enabled=True, now_utc=START + timedelta(minutes=20)) == (1, 1)
    assert run_once(**kwargs, enqueue_enabled=True, now_utc=START + timedelta(minutes=21)) == (0, 0)
    assert unqueued_events(**kwargs) == ()
    assert (
        PskReporterOrchestrationRepository(kwargs["queue_database"])
        .health(
            now_utc=START + timedelta(minutes=21),
            enabled=False,
            minimum_interval=timedelta(minutes=10),
        )
        .pending_count
        == 1
    )


def test_missing_databases_fail_closed_without_creating_files(tmp_path: Path) -> None:
    kwargs = {
        "sync_database": tmp_path / "source",
        "snapshot_database": tmp_path / "snap",
        "queue_database": tmp_path / "queue",
    }
    with pytest.raises(AutoQueueError, match="Required database missing"):
        run_once(**kwargs, enqueue_enabled=True)
    assert not any(tmp_path.iterdir())


def test_batch_bounds(tmp_path: Path) -> None:
    kwargs = config(tmp_path)
    with pytest.raises(ValueError, match="batch_size"):
        unqueued_events(**kwargs, batch_size=101)


def test_operator_county_snapshot_enqueues_without_duplicates(tmp_path: Path) -> None:
    """A county-bearing synchronized QSO must survive the PSK queue boundary."""
    import json
    import sqlite3

    kwargs = config(tmp_path)
    with sqlite3.connect(kwargs["snapshot_database"]) as db:
        row = db.execute(
            "SELECT contact_id, contact_json FROM synchronized_contact_snapshots"
        ).fetchone()
        assert row is not None
        payload = json.loads(row[1])
        payload.update(
            my_state="OH",
            my_county="CLINTON",
            my_latitude=39.55,
            my_longitude=-83.95,
            my_cq_zone=4,
            my_itu_zone=8,
        )
        db.execute(
            "UPDATE synchronized_contact_snapshots SET contact_json=? WHERE contact_id=?",
            (json.dumps(payload), row[0]),
        )
    events = unqueued_events(**kwargs)
    assert len(events) == 1
    assert events[0].contact.my_county == "CLINTON"
    assert run_once(**kwargs, enqueue_enabled=True, now_utc=START + timedelta(minutes=20)) == (1, 1)
    assert run_once(**kwargs, enqueue_enabled=True, now_utc=START + timedelta(minutes=21)) == (0, 0)
