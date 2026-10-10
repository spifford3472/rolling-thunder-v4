"""Read-only normalized PSK Reporter pre-contact coverage audit.

Intended for an authorized operator with existing read access; no permission
changes, polling, database writes, or receiver callsign disclosure.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

_REQUIRED = {"sender_callsign", "receiver_callsign", "receiver_locator_normalized",
             "frequency_hz", "flow_start_utc", "mode", "snr_db"}


def audit_coverage(path: Path, *, sender: str, now: datetime) -> dict[str, object]:
    """Return aggregate observation counts; fail explicitly on inaccessible data."""
    if now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if not sender.strip():
        raise ValueError("sender must be nonempty")
    try:
        exists = path.is_file()
    except PermissionError:
        return {"status": "unavailable", "reason": "database_inaccessible_or_invalid"}
    if not exists:
        return {"status": "unavailable", "reason": "database_missing"}
    try:
        with sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True, timeout=0.2) as db:
            cols = {row[1] for row in db.execute("PRAGMA table_info(psk_reception)")}
            if not _REQUIRED <= cols:
                return {"status": "unavailable", "reason": "normalized_schema_missing"}
            summary: dict[str, object] = {"status": "ok", "sender": sender.upper().strip()}
            for minutes in (30, 120, 1440):
                start = (now.astimezone(UTC) - timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")
                end = now.astimezone(UTC).isoformat().replace("+00:00", "Z")
                count, receivers, with_grid = db.execute(
                    """SELECT count(*), count(DISTINCT receiver_callsign),
                       count(DISTINCT CASE WHEN receiver_locator_normalized IS NOT NULL
                            AND length(receiver_locator_normalized) >= 4
                            THEN receiver_callsign END)
                       FROM psk_reception
                       WHERE sender_callsign = ? COLLATE NOCASE
                       AND upper(mode) = 'FT8'
                       AND flow_start_utc BETWEEN ? AND ?""",
                    (sender.strip(), start, end),
                ).fetchone()
                summary[f"last_{minutes}m"] = {
                    "receptions": count, "independent_receivers": receivers,
                    "receivers_with_grid": with_grid,
                }
            return summary
    except (sqlite3.Error, OSError):
        return {"status": "unavailable", "reason": "database_inaccessible_or_invalid"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Forge normalized PSK history coverage")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--sender", default="KI5VNB")
    args = parser.parse_args()
    result = audit_coverage(args.database, sender=args.sender, now=datetime.now(UTC))
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
