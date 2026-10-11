"""Non-actuating Forge C5.1 readiness observation CLI.

Reads C4 SQLite through SQLite immutable read-only URI. Does not manufacture
C5 calibration labels from historical model forecasts or retrospective QSOs.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

from rolling_thunder.forge_ft8_power_advisor_config import (
    PowerAdvisorMode,
    load_ft8_power_advisor_policy,
)


def inspect_c4(path: Path) -> dict[str, object]:
    """Read-only conservative inventory; not a model training cohort."""
    if not path.is_file():
        return {"available": False, "reason": "c4_store_missing", "stored_slots": 0, "independent_requests": 0}
    uri = "file:" + quote(str(path.resolve()), safe="/") + "?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True, timeout=2) as db:
            db.execute("PRAGMA query_only=ON")
            db.execute("PRAGMA busy_timeout=2000")
            db.execute("PRAGMA trusted_schema=OFF")
            existing = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "baseline_slot_v1" not in existing:
                return {"available": False, "reason": "c4_schema_missing", "stored_slots": 0, "independent_requests": 0}
            slots = db.execute(
                "SELECT COUNT(*) FROM baseline_slot_v1 WHERE status='generated'"
            ).fetchone()[0]
            requests = db.execute(
                """SELECT COUNT(DISTINCT canonical_request_sha256)
                   FROM baseline_slot_v1 WHERE status='generated'
                   AND canonical_request_sha256 IS NOT NULL"""
            ).fetchone()[0]
            return {"available": True, "reason": "inventory_only_not_qualified_prospective_evidence",
                    "stored_slots": slots, "independent_requests": requests}
    except (sqlite3.Error, OSError) as exc:
        return {"available": False, "reason": f"c4_read_error:{type(exc).__name__}",
                "stored_slots": 0, "independent_requests": 0}


def evaluate_once(policy_path: Path, c4_path: Path, *, now: datetime | None = None) -> dict[str, object]:
    now = now or datetime.now(UTC)
    status: dict[str, object] = {
        "schema_version": 1, "observed_at_utc": now.isoformat(),
        "shadow_only": True, "apply_allowed": False, "may_transmit": False,
        "suggested_start_watts": None, "empirical_success_probability": None,
        "current_operational_baseline_watts": 20,
        "readiness": "DEGRADED/SUSPENDED", "reason_codes": [],
    }
    try:
        policy = load_ft8_power_advisor_policy(policy_path)
        status["policy_mode"] = policy.mode.value
        if policy.mode is PowerAdvisorMode.OFF:
            status["readiness"] = "OFF"
            status["reason_codes"] = ["configuration_off"]
        else:
            status["readiness"] = "INSUFFICIENT_EVIDENCE/COLLECTING"
            status["reason_codes"] = [
                "verified_prospective_c5_pairing_not_connected",
                "heldout_calibration_not_established",
                "heldout_noninferiority_not_established",
            ]
    except (OSError, ValueError) as exc:
        status["policy_mode"] = "invalid"
        status["reason_codes"] = ["configuration_unavailable_or_invalid", type(exc).__name__]
    status["c4_inventory"] = inspect_c4(c4_path)
    return status


def main() -> None:
    parser = argparse.ArgumentParser(description="Forge C5.1 safe readiness snapshot (no RF authority)")
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--c4-db", type=Path, required=True)
    args = parser.parse_args()
    # Never open privileged configuration or write to live Forge history.
    print(json.dumps(evaluate_once(args.policy, args.c4_db), sort_keys=True))


if __name__ == "__main__":
    main()
