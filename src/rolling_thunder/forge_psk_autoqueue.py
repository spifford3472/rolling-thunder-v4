"""Restart-safe Forge-only FT8-to-PSK queue feeder, with zero provider I/O.

The durable PSK queue itself is the processing cursor: every run selects only
confirmed FT8 contacts whose UUID has not yet been enqueued.
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from time import sleep

from pydantic import ValidationError

from rolling_thunder.domain import Contact
from rolling_thunder.forge_pskreporter import PskReporterConfig
from rolling_thunder.forge_pskreporter_orchestration import (
    CompletedFt8QsoEvent,
    PskReporterCompletedEventAdapter,
    PskReporterOrchestrationRepository,
)
from rolling_thunder.ft8.performance import FT8PerformanceAttempt

_LOGGER = logging.getLogger(__name__)


class AutoQueueError(RuntimeError):
    """Untrusted or unavailable source records fail closed."""


def unqueued_events(
    *,
    sync_database: Path,
    snapshot_database: Path,
    queue_database: Path,
    batch_size: int = 50,
) -> tuple[CompletedFt8QsoEvent, ...]:
    """Get the next bounded page using read-only attached databases."""
    if not 1 <= batch_size <= 100:
        raise ValueError("batch_size must be between 1 and 100")
    for path in (sync_database, snapshot_database, queue_database):
        if not path.is_file():
            raise AutoQueueError(f"Required database missing: {path}")
    try:
        with sqlite3.connect(":memory:") as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA query_only=ON")
            for alias, path in (
                ("src", sync_database),
                ("snap", snapshot_database),
                ("queued", queue_database),
            ):
                db.execute(
                    f"ATTACH DATABASE ? AS {alias}",
                    (f"file:{path.resolve()}?mode=ro",),
                )
            rows = db.execute(
                """
                SELECT p.*, s.contact_json
                FROM src.ft8_performance_attempts p
                JOIN src.forge_contact_sync_ledger l
                  ON l.contact_id=p.attempt_id AND l.state='synchronized'
                JOIN snap.synchronized_contact_snapshots s
                  ON s.contact_id=p.attempt_id
                LEFT JOIN queued.pskreporter_completed_ft8_event q
                  ON q.contact_id=p.attempt_id
                WHERE p.outcome='completed' AND p.success=1
                  AND q.contact_id IS NULL
                ORDER BY p.started_at_utc, p.attempt_id
                LIMIT ?
                """,
                (batch_size,),
            ).fetchall()
    except sqlite3.Error as error:
        raise AutoQueueError("Cannot read confirmed FT8 autoqueue sources") from error

    validated: list[CompletedFt8QsoEvent] = []
    for row in rows:
        identifier = str(row["attempt_id"])
        attempt_data = {
            field: row[field]
            for field in FT8PerformanceAttempt.model_fields
            if field in dict(row) and row[field] is not None
        }
        try:
            validated.append(
                CompletedFt8QsoEvent(
                    contact=Contact.model_validate_json(row["contact_json"]),
                    terminal_attempt=FT8PerformanceAttempt.model_validate(attempt_data),
                )
            )
        except (ValidationError, ValueError) as error:
            raise AutoQueueError(f"Invalid confirmed FT8 event {identifier}") from error
    return tuple(validated)


def run_once(
    *,
    sync_database: Path,
    snapshot_database: Path,
    queue_database: Path,
    batch_size: int = 50,
    enqueue_enabled: bool = False,
    now_utc: datetime | None = None,
) -> tuple[int, int]:
    """(eligible, inserted); enqueue disabled by default, never query provider."""
    events = unqueued_events(
        sync_database=sync_database,
        snapshot_database=snapshot_database,
        queue_database=queue_database,
        batch_size=batch_size,
    )
    if not enqueue_enabled:
        return len(events), 0
    adapter = PskReporterCompletedEventAdapter(
        PskReporterOrchestrationRepository(queue_database),
        PskReporterConfig(enabled=False),
    )
    now = now_utc or datetime.now(UTC)
    inserted = 0
    for event in events:
        adapter.enqueue(event, received_at_utc=now)
        inserted += 1
    return len(events), inserted


def main() -> None:
    parser = argparse.ArgumentParser(description="Safe, provider-free Forge PSK queue feeder")
    parser.add_argument("--sync-db", required=True, type=Path)
    parser.add_argument("--snapshots-db", required=True, type=Path)
    parser.add_argument("--queue-db", required=True, type=Path)
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--enqueue", action="store_true", help="Permit writing only to PSK queue")
    parser.add_argument("--continuous", action="store_true", help="Repeat every interval seconds")
    parser.add_argument("--interval-seconds", type=int, default=60)
    args = parser.parse_args()
    if args.continuous and not 30 <= args.interval_seconds <= 3600:
        parser.error("continuous interval must be 30–3600 seconds")
    logging.basicConfig(level=logging.INFO)
    while True:
        eligible, inserted = run_once(
            sync_database=args.sync_db,
            snapshot_database=args.snapshots_db,
            queue_database=args.queue_db,
            batch_size=args.batch_size,
            enqueue_enabled=args.enqueue,
        )
        _LOGGER.info("PSK feeder eligible=%d inserted=%d provider_requests=0", eligible, inserted)
        if not args.continuous:
            break
        sleep(args.interval_seconds)


if __name__ == "__main__":
    main()
