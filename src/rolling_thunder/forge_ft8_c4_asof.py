"""Offline, conservative C4 regional-forecast/FT8 v2 choice-time comparison.

C4 forecasts are coarse regional research, not station-specific success odds.
Only validates as-of timing and immutable input identities, never qualifies power.
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
from collections import Counter
from datetime import datetime, timedelta
from json import loads
from pathlib import Path

from rolling_thunder.forge_ft8_prospective_inventory import _connect
from rolling_thunder.forge_voacap_baseline import BaselinePlan
from rolling_thunder.ft8.attempt_ledger import FT8AttemptEvent

_BAND = re.compile(r"^([0-9]+)m$")


def audit_c4_choice_pairs(
    inbox_path: Path, history_path: Path, c4_path: Path,
) -> dict[str, object]:
    """Return evidence counts only after independent source/as-of/hash checks.

    Never mark calibration, statistical qualification, or experimental proof.
    """
    rejected: Counter[str] = Counter()
    matched: set[str] = set()
    input_families: set[str] = set()
    segments: Counter[str] = Counter()
    total = 0
    if not all(path.is_file() for path in (inbox_path, history_path, c4_path)):
        return _report(False, 0, matched, input_families, segments, {"missing_source": 1})
    try:
        with _connect(inbox_path) as inbox, _connect(history_path) as history, _connect(c4_path) as c4:
            required = [
                (inbox, "ft8_attempt_inbox"),
                (history, "ft8_attempt_provenance_v1"),
                (c4, "baseline_slot_v1"),
                (c4, "baseline_provider_response_v1"),
                (c4, "baseline_plan_v1"),
            ]
            for db, name in required:
                if db.execute("SELECT 1 FROM sqlite_master WHERE name=? AND type='table'",
                              (name,)).fetchone() is None:
                    return _report(False, 0, matched, input_families, segments,
                                   {"missing_source_schema": 1})
            plans: dict[str, BaselinePlan] = {}
            for plan_id, payload, digest in c4.execute(
                "SELECT plan_id,payload_json,canonical_sha256 FROM baseline_plan_v1"
            ):
                try:
                    plan = BaselinePlan.model_validate_json(payload)
                    if str(plan.plan_id) != plan_id or plan.canonical_sha256 != digest:
                        rejected["invalid_plan_identity"] += 1
                        continue
                    plans[plan_id] = plan
                except ValueError:
                    rejected["invalid_plan_payload"] += 1
            slots = c4.execute(
                """SELECT s.plan_id,s.target_grid,s.band_m,s.forecast_for_utc,
                   s.generated_at_utc,s.canonical_request_sha256,
                   s.canonical_request_json,s.response_sha256,s.ssn_value_semantics,
                   s.ssn_target_month,s.ssn_source,s.ssn_source_version,
                   s.ssn_source_schema,s.ssn_revision_policy,s.ssn_source_record_id,
                   s.ssn_source_released_at_utc,s.ssn_captured_at_utc,s.ssn_raw_sha256,
                   s.ssn_snapshot_sha256,
                   p.response_json,p.service_version,
                   p.model_version,p.response_sha256
                   FROM baseline_slot_v1 s JOIN baseline_provider_response_v1 p
                   ON s.canonical_request_sha256=p.request_sha256
                   WHERE s.status='ready' AND s.timing_class='pre_choice'"""
            ).fetchall()
            verified_slots: list[tuple[str, str, int, datetime, datetime, str]] = []
            for (plan_id, target_grid, band, forecast_utc, generated_utc,
                 request_sha, request_json, response_sha, ssn_semantics, ssn_month,
                 ssn_source, ssn_source_version, ssn_source_schema, ssn_revision_policy,
                 ssn_record_id, ssn_released, ssn_captured, ssn_raw_sha, ssn_snapshot_sha,
                 response_json, service_version, model_version, stored_response_sha) in slots:
                try:
                    plan = plans[plan_id]
                    forecast = datetime.fromisoformat(forecast_utc)
                    generated = datetime.fromisoformat(generated_utc)
                    request = loads(request_json)
                    if (not forecast.tzinfo or not generated.tzinfo
                        or generated > forecast
                        or datetime.fromisoformat(ssn_captured) > generated
                        or (ssn_released is not None
                            and datetime.fromisoformat(ssn_released) > generated)
                        or ssn_semantics != "monthly_smoothed_predicted_sunspot_number"
                        or ssn_month != forecast.strftime("%Y-%m")
                        or ssn_source != plan.ssn_source
                        or ssn_source_version != plan.ssn_source_version
                        or ssn_source_schema != plan.ssn_source_schema
                        or ssn_revision_policy != plan.ssn_revision_policy
                        or not isinstance(ssn_record_id, str) or not ssn_record_id
                        or not isinstance(ssn_raw_sha, str) or len(ssn_raw_sha) != 64
                        or not isinstance(ssn_snapshot_sha, str) or len(ssn_snapshot_sha) != 64
                        or plan.model_version != model_version
                        or plan.service_version != service_version
                        or response_sha != stored_response_sha
                        or hashlib.sha256(request_json.encode()).hexdigest() != request_sha
                        or hashlib.sha256(response_json.encode()).hexdigest() != response_sha
                        or not isinstance(request, dict)
                        or request.get("ssn_value_semantics") != ssn_semantics
                        or request.get("ssn_target_month") != ssn_month
                        or request.get("ssn_source") != ssn_source
                        or request.get("ssn_source_version") != ssn_source_version
                        or request.get("ssn_source_schema") != ssn_source_schema
                        or request.get("ssn_revision_policy") != ssn_revision_policy
                        or request.get("ssn_source_record_id") != ssn_record_id
                        or request.get("ssn_raw_sha256") != ssn_raw_sha
                        or request.get("ssn_snapshot_sha256") != ssn_snapshot_sha):
                        rejected["invalid_forecast_source"] += 1
                        continue
                    # Do not silently broaden 4-character target-grid uncertainty.
                    if target_grid.upper() not in {t.grid.upper() for t in plan.targets}:
                        rejected["plan_target_mismatch"] += 1
                        continue
                    verified_slots.append((
                        plan.origin_grid.upper(), str(target_grid).upper(), int(band),
                        forecast, generated, request_sha,
                    ))
                except (ValueError, KeyError, TypeError, AttributeError):
                    rejected["invalid_forecast_slot"] += 1
            for attempt_id, digest, payload in inbox.execute(
                "SELECT attempt_uuid,payload_sha256,payload_json FROM ft8_attempt_inbox"
            ):
                total += 1
                try:
                    event = FT8AttemptEvent.model_validate_json(payload)
                    if (str(event.attempt_uuid) != attempt_id
                        or event.payload_sha256 != digest
                        or event.schema_version != 2
                        or event.choice_at_utc is None):
                        rejected["missing_choice_or_invalid_source"] += 1
                        continue
                    provenance = history.execute(
                        "SELECT provenance FROM ft8_attempt_provenance_v1 WHERE attempt_uuid=?",
                        (attempt_id,),
                    ).fetchone()
                    if provenance != ("field_observed",):
                        rejected["unverified_provenance"] += 1
                        continue
                    if not event.remote_grid or not event.local_grid or not event.band:
                        rejected["missing_path_identity"] += 1
                        continue
                    match = _BAND.fullmatch(event.band)
                    if match is None or not any(t.transmitted for t in event.tx_periods):
                        rejected["unusable_band_or_nontransmitted"] += 1
                        continue
                    assert event.choice_at_utc is not None
                    candidates = [
                        (forecast, request_sha)
                        for origin, target, band, forecast, available, request_sha in verified_slots
                        if event.local_grid.upper() == origin
                        and event.remote_grid.upper().startswith(target)
                        and int(match.group(1)) == band
                        and forecast <= event.choice_at_utc < forecast + timedelta(hours=6)
                        and available <= event.choice_at_utc
                    ]
                    if not candidates:
                        rejected["no_matching_prechoice_c4_forecast"] += 1
                        continue
                    latest_forecast, request_sha = max(candidates)
                    del latest_forecast
                    matched.add(attempt_id)
                    input_families.add(request_sha)
                    segments[event.band] += 1
                except (ValueError, TypeError, AttributeError, sqlite3.Error):
                    rejected["invalid_event_or_asof_data"] += 1
        return _report(True, total, matched, input_families, segments, dict(rejected))
    except (sqlite3.Error, OSError, ValueError):
        return _report(False, total, set(), set(), Counter(), {"source_read_failed": 1})


def _report(
    available: bool, inspected: int, attempts: set[str], families: set[str],
    segments: Counter[str], excluded: dict[str, int],
) -> dict[str, object]:
    return {
        "available": available, "inspected_attempts": inspected,
        "regional_asof_comparisons": len(attempts),
        "distinct_provider_request_inputs": len(families),
        "operating_segments": dict(sorted(segments.items())),
        "reason_counts": dict(sorted(excluded.items())),
        "training_eligible": False,
        "calibrated_for_power": False,
        "noninferiority_vs_20w_established": False,
    }
