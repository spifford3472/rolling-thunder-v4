#!/usr/bin/env python3
"""Read-only, reproducible CP3.1 FT8 trial cohort report (CAT watts, not RF)."""
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path

TRIAL_START = "2026-10-11T00:45"
TRIAL_END = "2026-10-11T02:00"


def report(db_path: Path) -> dict[str, object]:
    # SQLite URI mode=ro forbids writing to the historical production archive.
    from urllib.parse import quote
    uri = "file:" + quote(str(db_path.resolve()), safe="/") + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as db:
        db.row_factory = sqlite3.Row
        attempts = db.execute(
            "SELECT attempt_id,callsign,band,outcome,success,received_report_db,"
            "distance_km,last_qso_state,terminal_reason,attempt_count "
            "FROM ft8_performance_attempts WHERE started_at_utc >= ? "
            "AND started_at_utc < ? ORDER BY started_at_utc,attempt_id",
            (TRIAL_START, TRIAL_END),
        ).fetchall()
        periods = db.execute(
            "SELECT p.qso_id,p.emission_index,p.configured_power_watts,"
            "p.power_readback_verified,p.started_at_utc "
            "FROM forge_ft8_transmit_period p "
            "JOIN ft8_performance_attempts a ON a.attempt_id=p.qso_id "
            "WHERE a.started_at_utc >= ? AND a.started_at_utc < ? "
            "ORDER BY p.qso_id,p.emission_index",
            (TRIAL_START, TRIAL_END),
        ).fetchall()
    groups: dict[str, list[sqlite3.Row]] = {}
    for period in periods:
        groups.setdefault(period["qso_id"], []).append(period)
    details = []
    for attempt in attempts:
        emissions = groups.get(attempt["attempt_id"], [])
        details.append({
            "callsign": attempt["callsign"],
            "band": attempt["band"],
            "outcome": attempt["outcome"],
            "received_report_db": attempt["received_report_db"],
            "distance_km": attempt["distance_km"],
            "last_qso_state": attempt["last_qso_state"],
            "terminal_reason": attempt["terminal_reason"],
            "attempt_count": attempt["attempt_count"],
            "emission_count": len(emissions),
            "cat_power_watts": [p["configured_power_watts"] for p in emissions],
            "verified_cat_periods": sum(int(p["power_readback_verified"]) for p in emissions),
        })
    return {
        "window_utc": [TRIAL_START, TRIAL_END],
        "attempts": len(attempts),
        "periods": len(periods),
        "by_outcome": dict(sorted(Counter(a["outcome"] for a in attempts).items())),
        "by_band": dict(sorted(Counter(a["band"] for a in attempts).items())),
        "orphan_attempts_without_period": [a["callsign"] for a in attempts if not groups.get(a["attempt_id"])],
        "notes": [
            "Configured CAT watts are not calibrated RF output.",
            "Received signal report does not prove completion or the first reply emission power.",
            "Archived periods lack message-class and receive-state transition events.",
            "Missing PSK observations cannot be interpreted as path failure.",
        ],
        "attempt_details": details,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path, help="Existing SQLite DB, opened read-only")
    args = parser.parse_args()
    print(json.dumps(report(args.database), indent=2))


if __name__ == "__main__":
    main()
