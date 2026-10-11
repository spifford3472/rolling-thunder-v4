"""Non-actuating Forge C5.1 readiness observation CLI.

Reads C4 SQLite through SQLite immutable read-only URI. Does not manufacture
C5 calibration labels from historical model forecasts or retrospective QSOs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

from rolling_thunder.forge_ft8_power_advisor_config import (
    PowerAdvisorMode,
    load_ft8_power_advisor_policy,
)
from rolling_thunder.forge_ft8_prospective_inventory import audit_prospective_inbox


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


def evaluate_once(
    policy_path: Path, c4_path: Path, *, now: datetime | None = None,
    inbox_path: Path | None = None, history_path: Path | None = None,
) -> dict[str, object]:
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
    if inbox_path is not None and history_path is not None:
        status["prospective_inventory"] = audit_prospective_inbox(inbox_path, history_path)
    return status



def persist_status(status_path: Path, status: dict[str, object]) -> bool:
    """Atomically publish bounded status, append transition-only hash-linked audit."""
    status_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    encoded = json.dumps(status, sort_keys=True, separators=(",", ":")) + "\n"
    if len(encoded) > 16384:
        raise ValueError("readiness status exceeds size budget")
    previous = None
    if status_path.is_file():
        try:
            previous = json.loads(status_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeError):
            previous = None
    changed = (
        previous is None
        or previous.get("readiness") != status.get("readiness")
        or previous.get("reason_codes") != status.get("reason_codes")
        or previous.get("policy_mode") != status.get("policy_mode")
    )
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=status_path.parent,
            prefix=".readiness-", delete=False,
        ) as handle:
            temporary = handle.name
            os.fchmod(handle.fileno(), 0o600)
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, status_path)
    finally:
        if temporary is not None and os.path.exists(temporary):
            os.unlink(temporary)
    if changed:
        # Journal remains the durable transition log. Only an observation digest
        # is recorded; no remote callsigns, GPS or raw payloads are emitted.
        transition = {
            "event": "readiness_transition",
            "observed_at_utc": status["observed_at_utc"],
            "previous_state": None if previous is None else previous.get("readiness"),
            "new_state": status["readiness"],
            "reason_codes": status["reason_codes"],
            "snapshot_sha256": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
        }
        print(json.dumps(transition, sort_keys=True))
    return changed


def main() -> None:
    parser = argparse.ArgumentParser(description="Forge C5.1 safe readiness snapshot (no RF authority)")
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--c4-db", type=Path, required=True)
    parser.add_argument("--status-path", type=Path)
    parser.add_argument("--inbox-db", type=Path)
    parser.add_argument("--history-db", type=Path)
    args = parser.parse_args()
    # Never open privileged configuration or write to live Forge history.
    status = evaluate_once(
        args.policy, args.c4_db, inbox_path=args.inbox_db, history_path=args.history_db,
    )
    if args.status_path is not None:
        persist_status(args.status_path, status)
    print(json.dumps(status, sort_keys=True))


if __name__ == "__main__":
    main()
