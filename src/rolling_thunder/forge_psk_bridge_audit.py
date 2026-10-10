"""Read-only eligibility audit for a future Forge-only PSK Reporter bridge.

The contact-sync ledger stores hashes and delivery states, NOT complete Contact
objects. Do not infer a completed PSK event from a successful attempt alone.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import date
from pathlib import Path

from pydantic import BaseModel, Field


class PskBridgeAudit(BaseModel):
    """Aggregate, non-sensitive evidence about available completed FT8 records."""

    utc_date: date
    attempts: int = Field(ge=0)
    completed_attempts: int = Field(ge=0)
    synchronized_completed_attempts: int = Field(ge=0)
    missing_synchronized_contacts: int = Field(ge=0)
    completed_with_grid: int = Field(ge=0)
    completed_with_frequency: int = Field(ge=0)
    completed_with_end_time: int = Field(ge=0)
    full_contact_payloads_in_sync_ledger: int = Field(default=0, ge=0)
    eligible_for_existing_event_contract: int = Field(default=0, ge=0)


def audit_completed_ft8(database: Path, utc_date: date) -> PskBridgeAudit:
    """Inspect Forge's SQLite ledger without writing, migrating, or opening providers."""
    connection = sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True)
    try:
        connection.execute("PRAGMA query_only = ON")
        tables = {
            str(row[0])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        required = {"ft8_performance_attempts", "forge_contact_sync_ledger"}
        if not required.issubset(tables):
            raise ValueError(f"Missing required Forge tables: {sorted(required - tables)}")
        cols = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(forge_contact_sync_ledger)")
        }
        # Fail closed if schema evolves: never assume payloads are unavailable.
        has_contact_payload = bool({"contact_json", "contact_payload", "payload_json"} & cols)
        result = connection.execute(
            """
            SELECT COUNT(*),
                   SUM(CASE WHEN p.outcome='completed' AND p.success=1 THEN 1 ELSE 0 END),
                   SUM(CASE WHEN p.outcome='completed' AND p.success=1
                             AND l.state='synchronized' THEN 1 ELSE 0 END),
                   SUM(CASE WHEN p.outcome='completed' AND p.success=1
                             AND (l.contact_id IS NULL OR l.state!='synchronized') THEN 1 ELSE 0 END),
                   SUM(CASE WHEN p.outcome='completed' AND p.success=1
                             AND p.remote_grid IS NOT NULL THEN 1 ELSE 0 END),
                   SUM(CASE WHEN p.outcome='completed' AND p.success=1
                             AND p.dial_frequency_hz IS NOT NULL THEN 1 ELSE 0 END),
                   SUM(CASE WHEN p.outcome='completed' AND p.success=1
                             AND p.ended_at_utc IS NOT NULL THEN 1 ELSE 0 END)
            FROM ft8_performance_attempts p
            LEFT JOIN forge_contact_sync_ledger l ON l.contact_id=p.attempt_id
            WHERE p.utc_date=?
            """,
            (utc_date.isoformat(),),
        ).fetchone()
        assert result is not None
        return (
            PskBridgeAudit(
                utc_date=utc_date,
                attempts=result[0] or 0,
                completed_attempts=result[1] or 0,
                synchronized_completed_attempts=result[2] or 0,
                missing_synchronized_contacts=result[3] or 0,
                completed_with_grid=result[4] or 0,
                completed_with_frequency=result[5] or 0,
                completed_with_end_time=result[6] or 0,
                full_contact_payloads_in_sync_ledger=0,
                eligible_for_existing_event_contract=0,
            )
            if not has_contact_payload
            else _schema_changed()
        )
    finally:
        connection.close()


def _schema_changed() -> PskBridgeAudit:
    raise ValueError("Contact ledger now has payload columns; review schema before proceeding")


def main() -> None:
    parser = argparse.ArgumentParser(description="Provider-free PSK bridge readiness audit")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--utc-date", type=date.fromisoformat, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            audit_completed_ft8(args.database, args.utc_date).model_dump(mode="json"), indent=2
        )
    )


if __name__ == "__main__":
    main()
