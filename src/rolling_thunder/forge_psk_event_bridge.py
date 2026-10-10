"""Provider-free bridge from confirmed Forge FT8 snapshots to PSK's durable queue.

This command is intentionally separate from both contact-sync and PSK's
provider worker; neither primary logging nor HTTP provider access runs here.
"""

from __future__ import annotations

import argparse
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from pydantic import ValidationError

from rolling_thunder.domain import Contact
from rolling_thunder.forge_pskreporter import PskReporterConfig
from rolling_thunder.forge_pskreporter_orchestration import (
    CompletedFt8QsoEvent,
    PskReporterCompletedEventAdapter,
    PskReporterOrchestrationRepository,
)
from rolling_thunder.ft8.performance import FT8PerformanceAttempt


class ForgePskBridgeError(RuntimeError):
    """Input records are missing, malformed, or inconsistent."""


def candidate_events(
    *,
    contact_sync_database: Path,
    contact_snapshot_database: Path,
    limit: int = 50,
) -> tuple[CompletedFt8QsoEvent, ...]:
    """Read only synchronized snapshot/attempt pairs; no writes or provider I/O."""
    if not 1 <= limit <= 100:
        raise ValueError("bridge limit must be between 1 and 100")
    try:
        with (
            sqlite3.connect(f"file:{contact_sync_database.resolve()}?mode=ro", uri=True) as source,
            sqlite3.connect(
                f"file:{contact_snapshot_database.resolve()}?mode=ro", uri=True
            ) as snapshots,
        ):
            source.row_factory = sqlite3.Row
            source.execute("PRAGMA query_only=ON")
            snapshots.execute("PRAGMA query_only=ON")
            rows = source.execute(
                """
                SELECT p.* FROM ft8_performance_attempts p
                INNER JOIN forge_contact_sync_ledger l
                    ON l.contact_id=p.attempt_id AND l.state='synchronized'
                WHERE p.outcome='completed' AND p.success=1
                ORDER BY p.started_at_utc, p.attempt_id LIMIT ?
                """,
                (limit,),
            ).fetchall()
            events: list[CompletedFt8QsoEvent] = []
            for row in rows:
                identifier = str(row["attempt_id"])
                contact_row = snapshots.execute(
                    "SELECT contact_json FROM synchronized_contact_snapshots WHERE contact_id=?",
                    (identifier,),
                ).fetchone()
                if contact_row is None:
                    continue  # Older contacts require a separately verified backfill.
                fields = set(FT8PerformanceAttempt.model_fields)
                attempt_data = {
                    key: row[key] for key in dict(row) if key in fields and row[key] is not None
                }
                try:
                    contact = Contact.model_validate_json(contact_row[0])
                    attempt = FT8PerformanceAttempt.model_validate(attempt_data)
                    if contact.contact_id != UUID(identifier):
                        raise ForgePskBridgeError("Snapshot UUID does not match join key")
                    events.append(CompletedFt8QsoEvent(contact=contact, terminal_attempt=attempt))
                except (ValidationError, ValueError) as error:
                    raise ForgePskBridgeError(
                        f"Invalid confirmed FT8 event for {identifier}"
                    ) from error
            return tuple(events)
    except sqlite3.Error as error:
        raise ForgePskBridgeError("Forge PSK bridge source read failed") from error


def enqueue_confirmed_events(
    *,
    contact_sync_database: Path,
    contact_snapshot_database: Path,
    orchestration_database: Path,
    limit: int = 50,
    now_utc: datetime | None = None,
    dry_run: bool = True,
) -> tuple[int, int]:
    """Return (validated, enqueued); replay stays idempotent."""
    events = candidate_events(
        contact_sync_database=contact_sync_database,
        contact_snapshot_database=contact_snapshot_database,
        limit=limit,
    )
    if dry_run:
        return (len(events), 0)
    adapter = PskReporterCompletedEventAdapter(
        PskReporterOrchestrationRepository(orchestration_database),
        PskReporterConfig(),  # No provider enablement: queue only.
    )
    timestamp = now_utc or datetime.now(UTC)
    for event in events:
        adapter.enqueue(event, received_at_utc=timestamp)
    return (len(events), len(events))


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only by default Forge PSK bridge")
    parser.add_argument("--sync-db", required=True, type=Path)
    parser.add_argument("--snapshots-db", required=True, type=Path)
    parser.add_argument("--queue-db", required=True, type=Path)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--enqueue", action="store_true")
    args = parser.parse_args()
    validated, enqueued = enqueue_confirmed_events(
        contact_sync_database=args.sync_db,
        contact_snapshot_database=args.snapshots_db,
        orchestration_database=args.queue_db,
        limit=args.limit,
        dry_run=not args.enqueue,
    )
    print(f"validated={validated} enqueued={enqueued} provider_queries=0")


if __name__ == "__main__":
    main()
