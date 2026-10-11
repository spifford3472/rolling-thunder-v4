"""Read-only C3 v2 prospective evidence audit; never calls a provider or radio.

Counts potential pairs ONLY when immutable event identity, field provenance,
frozen operator choice, and as-of link timing all agree. This is not proof of
calibration or experimental noninferiority.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from rolling_thunder.ft8.attempt_ledger import FT8AttemptEvent


def _connect(path: Path) -> sqlite3.Connection:
    uri = "file:" + quote(str(path.resolve()), safe="/") + "?mode=ro"
    db = sqlite3.connect(uri, uri=True, timeout=3)
    db.execute("PRAGMA query_only=ON")
    db.execute("PRAGMA trusted_schema=OFF")
    db.execute("PRAGMA busy_timeout=3000")
    return db


def audit_prospective_inbox(inbox_path: Path, history_path: Path) -> dict[str, object]:
    """Audit fixed source schemas without modifying C3 history or promoting power."""
    reasons: Counter[str] = Counter()
    qualified: set[str] = set()
    families: set[str] = set()
    segments: Counter[str] = Counter()
    total = 0
    if not inbox_path.is_file() or not history_path.is_file():
        return {"available": False, "reason_codes": ["required_c3_store_missing"],
                "inspected_attempts": 0, "prospective_pairs": 0,
                "unique_forecast_families": 0, "segments": {}}
    try:
        with _connect(inbox_path) as inbox, _connect(history_path) as history:
            itables = {r[0] for r in inbox.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            htables = {r[0] for r in history.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {"ft8_attempt_inbox"} <= itables or not {
                "ft8_attempt_provenance_v1", "voacap_attempt_link_v1",
                "voacap_prediction_run_v1", "voacap_prediction_input_v1",
            } <= htables:
                raise ValueError("required_c3_schema_missing")
            # Read-only snapshot in each DB, no arbitrary cross-database attachment.
            for attempt_id, digest, payload in inbox.execute(
                "SELECT attempt_uuid,payload_sha256,payload_json FROM ft8_attempt_inbox"
            ):
                total += 1
                try:
                    event = FT8AttemptEvent.model_validate_json(payload)
                    canonical = json.dumps(event.model_dump(mode="json"), sort_keys=True,
                                           separators=(",", ":")).encode()
                    if event.payload_sha256 != digest or hashlib.sha256(canonical).hexdigest() != digest:
                        reasons["immutable_payload_mismatch"] += 1
                        continue
                    if str(event.attempt_uuid) != attempt_id:
                        reasons["attempt_uuid_mismatch"] += 1
                        continue
                    if event.schema_version != 2 or event.choice_at_utc is None:
                        reasons["legacy_or_missing_choice"] += 1
                        continue
                    if event.transmit_attempt_count < 1 or not any(p.transmitted for p in event.tx_periods):
                        reasons["no_transmitted_period"] += 1
                        continue
                    provenance = history.execute(
                        "SELECT provenance FROM ft8_attempt_provenance_v1 WHERE attempt_uuid=?",
                        (attempt_id,),
                    ).fetchone()
                    if provenance != ("field_observed",):
                        reasons["unverified_or_synthetic_provenance"] += 1
                        continue
                    rows = history.execute(
                        """SELECT l.relation,l.as_of_cutoff_utc,l.training_eligible,
                           l.input_hash,r.available_at_utc,r.status,i.input_json
                           FROM voacap_attempt_link_v1 l
                           JOIN voacap_prediction_run_v1 r ON r.prediction_uuid=l.prediction_uuid
                           JOIN voacap_prediction_input_v1 i ON i.input_hash=l.input_hash
                           WHERE l.attempt_uuid=?""", (attempt_id,),
                    ).fetchall()
                    valid_inputs: set[str] = set()
                    for relation, cutoff, allowed, input_hash, available, run_status, input_json in rows:
                        try:
                            parsed = json.loads(input_json)
                            if not isinstance(parsed, dict):
                                continue
                            cutoff_utc = datetime.fromisoformat(cutoff)
                            available_utc = datetime.fromisoformat(available)
                        except (ValueError, TypeError, AttributeError):
                            continue
                        if (relation == "pre_choice" and allowed == 1
                            and run_status == "ready"
                            and available_utc <= event.choice_at_utc
                            and cutoff_utc <= event.choice_at_utc
                            and hashlib.sha256(
                                json.dumps(parsed, sort_keys=True, separators=(",", ":")).encode()
                            ).hexdigest() == input_hash):
                            valid_inputs.add(input_hash)
                    if not valid_inputs:
                        reasons["no_verified_prechoice_ready_forecast"] += 1
                        continue
                    qualified.add(attempt_id)
                    families.update(valid_inputs)
                    segments[event.band or "unknown"] += 1
                except (ValueError, TypeError, AttributeError, KeyError):
                    reasons["invalid_event_or_input"] += 1
        return {"available": True, "reason_codes": dict(sorted(reasons.items())),
                "inspected_attempts": total, "prospective_pairs": len(qualified),
                "unique_forecast_families": len(families), "segments": dict(sorted(segments.items())),
                "scientifically_calibrated": False}
    except (sqlite3.Error, OSError, ValueError) as exc:
        return {"available": False, "reason_codes": [type(exc).__name__],
                "inspected_attempts": total, "prospective_pairs": 0,
                "unique_forecast_families": 0, "segments": {}}
