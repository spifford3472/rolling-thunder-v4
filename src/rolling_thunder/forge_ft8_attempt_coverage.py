"""Read-only Phase-C coverage of retrospective FT8/VOACAP correlation.

This module opens declared SQLite snapshots in read-only mode.  It never claims
leases, invokes a provider, changes provenance, or exposes callsigns, payloads,
or exact coordinates in its report.
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections import Counter
from collections.abc import Iterable
from contextlib import closing
from datetime import UTC, datetime
from json import dumps, loads
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from rolling_thunder.domain import DomainModel
from rolling_thunder.forge_ft8_attempt_correlation import (
    DOCUMENTED_SYNTHETIC_ATTEMPTS,
    AttemptProvenance,
    VoacapModelInput,
    VoacapRelation,
    VoacapRunStatus,
    model_inputs_for_attempt,
)
from rolling_thunder.ft8.attempt_ledger import FT8AttemptEvent

RETROSPECTIVE_COVERAGE_SCHEMA_VERSION = 1
EXCLUSION_SET_VERSION = "phase-c1-2026-10-11"
_INBOX_TABLES = {"ft8_attempt_inbox", "ft8_attempt_inbox_metadata"}
_HISTORY_TABLES = {
    "voacap_attempt_schema_metadata",
    "voacap_prediction_input_v1",
    "voacap_prediction_run_v1",
    "voacap_attempt_link_v1",
    "ft8_attempt_provenance_v1",
}


class CoverageRatio(DomainModel):
    numerator: int = Field(ge=0)
    denominator: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_ratio(self) -> CoverageRatio:
        if self.numerator > self.denominator:
            raise ValueError("coverage numerator cannot exceed denominator")
        return self


class RetrospectiveCoverageReport(DomainModel):
    """Privacy-minimized deterministic machine-readable C2 artifact."""

    schema_version: Literal[1] = 1
    release_identifier: str = Field(min_length=1, max_length=200)
    generated_at_utc: datetime
    window_start_utc: datetime
    window_end_utc: datetime
    inbox_snapshot_identifier: str = Field(min_length=1, max_length=500)
    history_snapshot_identifier: str = Field(min_length=1, max_length=500)
    inbox_schema_version: int
    history_schema_version: int
    exclusion_set_version: str
    denominators: dict[str, int]
    event_partitions: dict[str, dict[str, int]]
    event_coverage: dict[str, CoverageRatio]
    modeled_input_partitions: dict[str, dict[str, int]]
    run_partitions: dict[str, dict[str, int]]
    reconciliation: dict[str, int]

    @field_validator("generated_at_utc", "window_start_utc", "window_end_utc")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("report timestamps must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_window(self) -> RetrospectiveCoverageReport:
        if self.window_end_utc <= self.window_start_utc:
            raise ValueError("coverage window end must follow its start")
        return self


def build_retrospective_coverage_report(
    inbox_database: Path,
    history_database: Path,
    *,
    window_start_utc: datetime,
    window_end_utc: datetime,
    generated_at_utc: datetime,
    release_identifier: str,
    inbox_snapshot_identifier: str,
    history_snapshot_identifier: str,
) -> RetrospectiveCoverageReport:
    """Correlate existing immutable evidence without writes or provider access."""
    start = _utc(window_start_utc)
    end = _utc(window_end_utc)
    generated = _utc(generated_at_utc)
    if end <= start:
        raise ValueError("coverage window end must follow its start")

    with closing(_read_only(inbox_database)) as inbox, closing(
        _read_only(history_database)
    ) as history:
        _require_tables(inbox, _INBOX_TABLES, "inbox")
        _require_tables(history, _HISTORY_TABLES, "history")
        inbox_version = _schema_version(
            inbox, "ft8_attempt_inbox_metadata", "inbox"
        )
        history_version = _schema_version(
            history, "voacap_attempt_schema_metadata", "history"
        )
        _check_foreign_keys(inbox, "inbox")
        _check_foreign_keys(history, "history")
        _check_documented_exclusions(history)
        all_inbox_uuids, selected = _read_events(inbox, start=start, end=end)
        provenance = _read_provenance(history)
        inputs = _read_inputs(history)
        runs = _read_runs(history)
        links = _read_links(history)

    history_attempt_uuids = {row["attempt_uuid"] for row in inputs}
    unknown_history_uuids = history_attempt_uuids - all_inbox_uuids
    if unknown_history_uuids:
        raise ValueError("history contains attempt UUIDs absent from the inbox snapshot")
    _validate_links(inputs, runs, links)
    _validate_training_links(links, runs, provenance)

    selected_uuids = set(selected)
    selected_inputs = [row for row in inputs if row["attempt_uuid"] in selected_uuids]
    selected_hashes = {row["input_hash"] for row in selected_inputs}
    selected_base_hashes = {row["base_input_hash"] for row in selected_inputs}
    base_hash_by_input_hash = {
        row["input_hash"]: row["base_input_hash"] for row in selected_inputs
    }
    selected_runs = [row for row in runs if row["input_hash"] in selected_hashes]
    selected_run_uuids = {row["prediction_uuid"] for row in selected_runs}
    selected_links = [
        row
        for row in links
        if row["attempt_uuid"] in selected_uuids
        and row["prediction_uuid"] in selected_run_uuids
    ]

    event_partitions = {
        "utc_day": _counts(
            row["event"].started_at_utc.date().isoformat() for row in selected.values()
        ),
        "band": _counts(_missing(row["event"].band) for row in selected.values()),
        "terminal_classification": _counts(
            row["event"].classification.value for row in selected.values()
        ),
        "provenance": _counts(
            provenance.get(attempt_uuid, AttemptProvenance.UNKNOWN.value)
            for attempt_uuid in selected
        ),
        "remote_grid_precision": _counts(
            (
                "missing"
                if row["event"].remote_grid is None
                else f"grid{len(row['event'].remote_grid)}"
            )
            for row in selected.values()
        ),
        "processing_state": _counts(
            row["state"] for row in selected.values()
        ),
    }
    events: tuple[FT8AttemptEvent, ...] = tuple(
        row["event"] for row in selected.values()
    )
    transmitted_periods = sum(
        period.transmitted for event in events for period in event.tx_periods
    )
    event_count = len(events)
    event_coverage = {
        "local_grid_present": _ratio(sum(event.local_grid is not None for event in events), event_count),
        "paired_coordinates_present": _ratio(
            sum(event.local_latitude is not None for event in events), event_count
        ),
        "remote_grid_present": _ratio(sum(event.remote_grid is not None for event in events), event_count),
        "dial_frequency_present": _ratio(
            sum(event.dial_frequency_hz is not None for event in events), event_count
        ),
        "band_present": _ratio(sum(event.band is not None for event in events), event_count),
        "start_end_created_utc_present": _ratio(event_count, event_count),
        "directional_report_present": _ratio(sum(bool(event.reports) for event in events), event_count),
        "verified_power_period_present": _ratio(
            sum(
                any(
                    period.transmitted and period.configured_power_watts is not None
                    for period in event.tx_periods
                )
                for event in events
            ),
            event_count,
        ),
    }
    modeled_input_partitions = {
        "direction": _counts(row["direction"] for row in selected_inputs),
        "provider_request": _counts(
            "ready" if row["provider_ready"] else "missing_required_input"
            for row in selected_inputs
        ),
    }
    run_partitions = {
        "status": _counts(row["status"] for row in selected_runs),
        "relation": _counts(row["relation"] for row in selected_links),
        "service_version": _counts(_missing(row["service_version"]) for row in selected_runs),
        "training_eligible": _counts(
            "eligible" if row["training_eligible"] else "ineligible"
            for row in selected_links
        ),
    }
    linked_input_hashes = {row["input_hash"] for row in selected_links}
    linked_run_uuids = {row["prediction_uuid"] for row in selected_links}
    expected_inputs = tuple(
        model_input
        for attempt_uuid, row in selected.items()
        if provenance.get(attempt_uuid) != AttemptProvenance.SYNTHETIC_TEST.value
        for model_input in model_inputs_for_attempt(row["event"])
    )
    expected_hashes = {model_input.input_hash for model_input in expected_inputs}
    terminal_hashes = {
        base_hash_by_input_hash[row["input_hash"]]
        for row in selected_runs
        if row["status"]
        in {
            VoacapRunStatus.READY.value,
            VoacapRunStatus.UNAVAILABLE.value,
            VoacapRunStatus.SKIPPED.value,
        }
    }
    reverse_unknown_hashes = {
        model_input.input_hash
        for model_input in expected_inputs
        if model_input.direction.value == "remote_to_local"
        and model_input.tx_power_watts is None
    }
    skipped_hashes = {
        base_hash_by_input_hash[row["input_hash"]]
        for row in selected_runs
        if row["status"] == VoacapRunStatus.SKIPPED.value
    }
    excluded_after_model_history = sum(
        provenance.get(attempt_uuid) == AttemptProvenance.SYNTHETIC_TEST.value
        and any(row["attempt_uuid"] == attempt_uuid for row in selected_inputs)
        for attempt_uuid in selected
    )
    reconciliation = {
        "selected_unique_attempt_uuids": len(selected_uuids),
        "selected_inbox_rows": event_count,
        "selected_input_rows": len(selected_inputs),
        "selected_run_rows": len(selected_runs),
        "selected_link_rows": len(selected_links),
        "expected_model_inputs": len(expected_hashes),
        "missing_model_input_rows": len(expected_hashes - selected_base_hashes),
        "unexpected_model_input_rows": len(selected_base_hashes - expected_hashes),
        "missing_terminal_run_inputs": len(expected_hashes - terminal_hashes),
        "reverse_unknown_power_inputs": len(reverse_unknown_hashes),
        "reverse_unknown_power_skips": len(reverse_unknown_hashes & skipped_hashes),
        "reverse_unknown_power_gaps": len(reverse_unknown_hashes - skipped_hashes),
        "unlinked_input_rows": sum(
            row["input_hash"] not in linked_input_hashes for row in selected_inputs
        ),
        "unlinked_run_rows": sum(
            row["prediction_uuid"] not in linked_run_uuids for row in selected_runs
        ),
        "excluded_attempts_with_model_history": excluded_after_model_history,
    }
    return RetrospectiveCoverageReport(
        release_identifier=release_identifier,
        generated_at_utc=generated,
        window_start_utc=start,
        window_end_utc=end,
        inbox_snapshot_identifier=inbox_snapshot_identifier,
        history_snapshot_identifier=history_snapshot_identifier,
        inbox_schema_version=inbox_version,
        history_schema_version=history_version,
        exclusion_set_version=EXCLUSION_SET_VERSION,
        denominators={
            "events": event_count,
            "transmitted_periods": transmitted_periods,
            "modeled_inputs": len(selected_inputs),
        },
        event_partitions=event_partitions,
        event_coverage=event_coverage,
        modeled_input_partitions=modeled_input_partitions,
        run_partitions=run_partitions,
        reconciliation=reconciliation,
    )


def _read_events(
    db: sqlite3.Connection, *, start: datetime, end: datetime
) -> tuple[set[str], dict[str, dict[str, Any]]]:
    rows = db.execute(
        "SELECT attempt_uuid,payload_sha256,payload_json,state FROM ft8_attempt_inbox"
    ).fetchall()
    all_uuids: set[str] = set()
    selected: dict[str, dict[str, Any]] = {}
    for attempt_uuid, digest, payload, state in rows:
        uuid_text = str(attempt_uuid)
        if uuid_text in all_uuids:
            raise ValueError("duplicate attempt UUID in inbox snapshot")
        all_uuids.add(uuid_text)
        event = FT8AttemptEvent.model_validate_json(payload)
        if str(event.attempt_uuid) != uuid_text or event.payload_sha256 != digest:
            raise ValueError("inbox UUID or immutable payload digest mismatch")
        if start <= event.started_at_utc < end:
            selected[uuid_text] = {"event": event, "state": str(state)}
    return all_uuids, selected


def _read_provenance(db: sqlite3.Connection) -> dict[str, str]:
    rows = db.execute(
        "SELECT attempt_uuid,provenance FROM ft8_attempt_provenance_v1"
    ).fetchall()
    result: dict[str, str] = {}
    for attempt_uuid, classification in rows:
        value = str(classification)
        if value not in {
            AttemptProvenance.FIELD_OBSERVED.value,
            AttemptProvenance.SYNTHETIC_TEST.value,
        }:
            raise ValueError("invalid attempt provenance classification")
        result[str(attempt_uuid)] = value
    return result


def _read_inputs(db: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = db.execute(
        "SELECT input_hash,attempt_uuid,direction,input_json FROM voacap_prediction_input_v1"
    ).fetchall()
    result: list[dict[str, Any]] = []
    for input_hash, attempt_uuid, direction, input_json in rows:
        payload = loads(input_json)
        model_input = VoacapModelInput.model_validate(payload)
        if (
            model_input.input_hash != input_hash
            or str(model_input.attempt_uuid) != str(attempt_uuid)
            or model_input.direction.value != direction
        ):
            raise ValueError("VOACAP model input identity or digest mismatch")
        result.append(
            {
                "input_hash": str(input_hash),
                "base_input_hash": model_input.model_copy(
                    update={"model_service_version": None}
                ).input_hash,
                "attempt_uuid": str(attempt_uuid),
                "direction": str(direction),
                "provider_ready": all(
                    payload.get(key) is not None
                    for key in ("tx_grid", "rx_grid", "frequency_hz", "tx_power_watts")
                )
                and str(payload.get("band", "")).endswith("m"),
            }
        )
    return result


def _read_runs(db: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = db.execute(
        """SELECT prediction_uuid,input_hash,available_at_utc,status,service_version,
        response_json,response_sha256
        FROM voacap_prediction_run_v1"""
    ).fetchall()
    result: list[dict[str, Any]] = []
    for (
        prediction_uuid,
        input_hash,
        available_at_utc,
        status,
        service_version,
        response_json,
        response_sha256,
    ) in rows:
        expected_digest = (
            None
            if response_json is None
            else hashlib.sha256(
                dumps(
                    loads(response_json), sort_keys=True, separators=(",", ":")
                ).encode()
            ).hexdigest()
        )
        if response_sha256 != expected_digest:
            raise ValueError("VOACAP response digest mismatch")
        _valid_run_status(status)
        result.append({
            "prediction_uuid": str(prediction_uuid),
            "input_hash": str(input_hash),
            "available_at_utc": str(available_at_utc),
            "status": str(status),
            "service_version": service_version,
        })
    return result


def _read_links(db: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = db.execute(
        """SELECT attempt_uuid,direction,input_hash,prediction_uuid,relation,
        as_of_cutoff_utc,training_eligible FROM voacap_attempt_link_v1"""
    ).fetchall()
    return [
        {
            "attempt_uuid": str(attempt_uuid),
            "direction": str(direction),
            "input_hash": str(input_hash),
            "prediction_uuid": str(prediction_uuid),
            "relation": str(relation),
            "as_of_cutoff_utc": str(cutoff),
            "training_eligible": bool(eligible),
        }
        for attempt_uuid, direction, input_hash, prediction_uuid, relation, cutoff, eligible in rows
        if _valid_link(relation, eligible)
    ]


def _validate_links(
    inputs: list[dict[str, Any]],
    runs: list[dict[str, Any]],
    links: list[dict[str, Any]],
) -> None:
    input_by_hash = {row["input_hash"]: row for row in inputs}
    run_by_uuid = {row["prediction_uuid"]: row for row in runs}
    if any(
        (model_input := input_by_hash.get(link["input_hash"])) is None
        or model_input["attempt_uuid"] != link["attempt_uuid"]
        or model_input["direction"] != link["direction"]
        or (run := run_by_uuid.get(link["prediction_uuid"])) is None
        or run["input_hash"] != link["input_hash"]
        for link in links
    ):
        raise ValueError("VOACAP link does not match its immutable input and run")


def _validate_training_links(
    links: list[dict[str, Any]],
    runs: list[dict[str, Any]],
    provenance: dict[str, str],
) -> None:
    run_by_uuid = {row["prediction_uuid"]: row for row in runs}
    for link in links:
        if not link["training_eligible"]:
            continue
        run = run_by_uuid.get(link["prediction_uuid"])
        valid = (
            run is not None
            and run["status"] == VoacapRunStatus.READY.value
            and provenance.get(link["attempt_uuid"]) == AttemptProvenance.FIELD_OBSERVED.value
            and link["relation"] == VoacapRelation.PRE_CHOICE.value
            and _parse_time(run["available_at_utc"])
            <= _parse_time(link["as_of_cutoff_utc"])
        )
        if not valid:
            raise ValueError("training-eligible VOACAP link violates Phase C invariants")


def _check_documented_exclusions(db: sqlite3.Connection) -> None:
    for attempt_uuid, classification, reason, evidence, evidence_date in (
        DOCUMENTED_SYNTHETIC_ATTEMPTS
    ):
        row = db.execute(
            """SELECT provenance,reason,evidence_reference,evidence_date
            FROM ft8_attempt_provenance_v1 WHERE attempt_uuid=?""",
            (str(attempt_uuid),),
        ).fetchone()
        if row != (classification, reason, evidence, evidence_date):
            raise ValueError("documented synthetic/test exclusion changed or is missing")


def _valid_run_status(value: object) -> bool:
    try:
        VoacapRunStatus(str(value))
    except ValueError as error:
        raise ValueError("invalid VOACAP run status") from error
    return True


def _valid_link(relation: object, eligible: object) -> bool:
    try:
        VoacapRelation(str(relation))
    except ValueError as error:
        raise ValueError("invalid VOACAP link relation") from error
    if eligible not in (0, 1):
        raise ValueError("invalid VOACAP training eligibility value")
    return True


def _schema_version(db: sqlite3.Connection, table: str, label: str) -> int:
    row = db.execute(
        f"SELECT schema_version FROM {table} WHERE singleton_id=1"
    ).fetchone()
    if row is None or len(row) != 1 or not isinstance(row[0], int):
        raise ValueError(f"invalid {label} schema metadata")
    return row[0]


def _require_tables(db: sqlite3.Connection, required: set[str], label: str) -> None:
    tables = {
        str(row[0])
        for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    missing = required - tables
    if missing:
        raise ValueError(f"missing required {label} tables: {sorted(missing)}")


def _check_foreign_keys(db: sqlite3.Connection, label: str) -> None:
    if db.execute("PRAGMA foreign_key_check").fetchall():
        raise ValueError(f"{label} snapshot failed foreign-key validation")


def _read_only(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    db.execute("PRAGMA query_only=ON")
    return db


def _counts(values: Iterable[object]) -> dict[str, int]:
    return dict(sorted(Counter(str(value) for value in values).items()))


def _ratio(numerator: int, denominator: int) -> CoverageRatio:
    return CoverageRatio(numerator=numerator, denominator=denominator)


def _missing(value: object | None) -> str:
    return "missing" if value is None else str(value)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("report timestamps must be timezone-aware")
    return value.astimezone(UTC)


def _parse_time(value: object) -> datetime:
    if not isinstance(value, str):
        raise TypeError("stored VOACAP timestamp must be text")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError("stored VOACAP timestamp is invalid") from error
    return _utc(parsed)
