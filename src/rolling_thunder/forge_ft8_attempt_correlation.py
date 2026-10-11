"""Forge durable FT8-attempt inbox and immutable VOACAP correlation history."""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from json import dumps, loads
from pathlib import Path
from typing import Any, Literal, Protocol
from uuid import UUID, uuid4

from pydantic import Field, TypeAdapter, ValidationError, field_validator

from rolling_thunder.domain import DomainModel, Frequency
from rolling_thunder.ft8.attempt_ledger import FT8AttemptEvent
from rolling_thunder.radio_band import RadioBandResolutionError, resolve_radio_band
from rolling_thunder.value_types import MaidenheadGrid

FORGE_ATTEMPT_SCHEMA_VERSION = 1
MODEL_INPUT_SCHEMA_VERSION = 1
_MAX_BATCH = 100
_GRID_ADAPTER = TypeAdapter(MaidenheadGrid)
DOCUMENTED_SYNTHETIC_ATTEMPTS = (
    (
        UUID("9ad2f0c2-ed0e-4ba7-8b03-732d8aa8c339"),
        "synthetic_test",
        "non-transmitted Forge FT8-P1 API acceptance record",
        "docs/engineering/FT8_P1_FORGE_STAGE_CUTOVER.md",
        "2026-10-10",
    ),
    (
        UUID("1d99bba6-0f38-4069-a706-77f9a90d4a8c"),
        "synthetic_test",
        "synthetic authenticated ingestion acceptance record; not real RF",
        "docs/engineering/voacap-ft8-phase-c.md",
        "2026-10-11",
    ),
)


class AttemptInboxConflict(RuntimeError):
    pass


class AttemptJobState(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    RETRY = "retry"
    COMPLETED = "completed"
    DEAD_LETTER = "dead_letter"


class VoacapDirection(StrEnum):
    LOCAL_TO_REMOTE = "local_to_remote"
    REMOTE_TO_LOCAL = "remote_to_local"


class VoacapRunStatus(StrEnum):
    READY = "ready"
    UNAVAILABLE = "unavailable"
    SKIPPED = "skipped"
    FAILED = "failed"


class VoacapRelation(StrEnum):
    PRE_CHOICE = "pre_choice"
    POST_ATTEMPT = "post_attempt"
    RETROSPECTIVE = "retrospective"


class AttemptProvenance(StrEnum):
    """Independent analytics provenance; absence never implies field evidence."""

    UNKNOWN = "unknown"
    FIELD_OBSERVED = "field_observed"
    SYNTHETIC_TEST = "synthetic_test"


class VoacapModelInput(DomainModel):
    """Canonical, fully hashed model input; unknown values remain null."""

    schema_version: Literal[1] = 1
    attempt_uuid: UUID
    direction: VoacapDirection
    period_sequence: int | None = Field(default=None, ge=1)
    choice_at_utc: datetime
    event_hour_utc: datetime
    tx_grid: str | None = Field(default=None, min_length=4, max_length=6)
    rx_grid: str | None = Field(default=None, min_length=4, max_length=6)
    tx_grid_precision: int | None = Field(default=None, ge=4, le=6)
    rx_grid_precision: int | None = Field(default=None, ge=4, le=6)
    grid_point_assumption: Literal["maidenhead_cell_center"] | None = None
    frequency_hz: int | None = Field(default=None, gt=0)
    band: str | None = Field(default=None, max_length=16)
    tx_power_watts: int | None = Field(default=None, gt=0, le=100)
    tx_power_source: Literal["cat_configured_readback"] | None = None
    mode: Literal["FT8"] = "FT8"
    antenna_configuration: str | None = Field(default=None, max_length=120)
    noise_configuration: str | None = Field(default=None, max_length=120)
    solar_index: float | None = None
    model_path: str | None = Field(default=None, max_length=64)
    service_contract_version: Literal["voacap-summary-v1"] = "voacap-summary-v1"
    model_service_version: str | None = Field(default=None, min_length=1, max_length=120)

    @field_validator("event_hour_utc")
    @classmethod
    def normalize_event_hour(cls, value: datetime) -> datetime:
        value = _utc(value)
        return value.replace(minute=0, second=0, microsecond=0)

    @field_validator("choice_at_utc")
    @classmethod
    def normalize_choice_time(cls, value: datetime) -> datetime:
        return _utc(value)

    @property
    def input_hash(self) -> str:
        return hashlib.sha256(_canonical(_model_input_payload(self)).encode()).hexdigest()

    def provider_request(self) -> dict[str, Any] | None:
        """Return the existing service shape only when every required input exists."""
        if None in (self.tx_grid, self.rx_grid, self.frequency_hz, self.tx_power_watts):
            return None
        if self.band is None or not self.band.endswith("m"):
            return None
        return {
            "tx_grid": self.tx_grid,
            "rx_grid": self.rx_grid,
            "year": self.event_hour_utc.year,
            "month": self.event_hour_utc.month,
            "bands_m": [int(self.band.removesuffix("m"))],
            "power_watts": self.tx_power_watts,
            "mode": "FT8",
            "timezone": "UTC",
        }


class VoacapProviderResult(DomainModel):
    service_version: str = Field(min_length=1, max_length=120)
    response_json: dict[str, Any]
    reliability_fraction: float | None = Field(default=None, ge=0, le=1)
    snr_db_hz: float | None = None
    muf_mhz: float | None = None
    rating: str | None = Field(default=None, max_length=80)


class VoacapAttemptClient(Protocol):
    def predict(self, model_input: VoacapModelInput) -> VoacapProviderResult: ...


class AttemptLease(DomainModel):
    event: FT8AttemptEvent
    lease_token: UUID
    worker_id: str
    attempt_count: int = Field(ge=1)


class AttemptInboxRepository:
    """Authenticated API sink and bounded worker queue; enqueue calls no provider."""

    def __init__(
        self,
        path: Path,
        *,
        max_attempts: int = 5,
        retry_base: timedelta = timedelta(minutes=1),
        retry_max: timedelta = timedelta(hours=1),
    ) -> None:
        if max_attempts < 1 or retry_base <= timedelta(0) or retry_max < retry_base:
            raise ValueError("invalid inbox retry bounds")
        self._path = path
        self._max_attempts = max_attempts
        self._retry_base = retry_base
        self._retry_max = retry_max
        self._initialize()

    def enqueue(self, event: FT8AttemptEvent, *, received_at_utc: datetime) -> bool:
        payload = event.model_dump_json()
        digest = event.payload_sha256
        now = _time(received_at_utc)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT payload_sha256 FROM ft8_attempt_inbox WHERE attempt_uuid=?",
                (str(event.attempt_uuid),),
            ).fetchone()
            if row is not None:
                if row[0] != digest:
                    raise AttemptInboxConflict(
                        f"attempt UUID replay changed payload: {event.attempt_uuid}"
                    )
                return False
            db.execute(
                """INSERT INTO ft8_attempt_inbox
                (attempt_uuid,payload_sha256,payload_json,state,attempt_count,
                 received_at_utc,next_attempt_at_utc)
                VALUES (?,?,?,'pending',0,?,?)""",
                (str(event.attempt_uuid), digest, payload, now, now),
            )
        return True

    def claim_due(
        self,
        *,
        now_utc: datetime,
        worker_id: str,
        lease_duration: timedelta,
        limit: int,
    ) -> tuple[AttemptLease, ...]:
        now = _utc(now_utc)
        if not worker_id.strip() or len(worker_id) > 120:
            raise ValueError("worker_id must contain 1..120 characters")
        if lease_duration <= timedelta(0) or not 1 <= limit <= _MAX_BATCH:
            raise ValueError("invalid lease duration or batch limit")
        claims: list[tuple[str, str, int, str]] = []
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                """UPDATE ft8_attempt_inbox SET state='dead_letter',lease_token=NULL,
                leased_until_utc=NULL,worker_id=NULL,last_error='lease expired after final attempt'
                WHERE state='processing' AND leased_until_utc<=? AND attempt_count>=?""",
                (_time(now), self._max_attempts),
            )
            rows = db.execute(
                """SELECT attempt_uuid,payload_json,attempt_count FROM ft8_attempt_inbox
                WHERE (((state IN ('pending','retry')) AND next_attempt_at_utc<=?) OR
                (state='processing' AND leased_until_utc<=?)) AND attempt_count<?
                ORDER BY next_attempt_at_utc,received_at_utc,attempt_uuid LIMIT ?""",
                (_time(now), _time(now), self._max_attempts, limit),
            ).fetchall()
            for attempt_uuid, payload, prior in rows:
                token = uuid4()
                count = int(prior) + 1
                db.execute(
                    """UPDATE ft8_attempt_inbox SET state='processing',attempt_count=?,
                    lease_token=?,leased_until_utc=?,worker_id=?,last_error=NULL
                    WHERE attempt_uuid=?""",
                    (
                        count,
                        str(token),
                        _time(now + lease_duration),
                        worker_id.strip(),
                        attempt_uuid,
                    ),
                )
                claims.append((attempt_uuid, payload, count, str(token)))
        return tuple(
            AttemptLease(
                event=FT8AttemptEvent.model_validate_json(payload),
                lease_token=UUID(token),
                worker_id=worker_id.strip(),
                attempt_count=count,
            )
            for _attempt_uuid, payload, count, token in claims
        )

    def finish(self, lease: AttemptLease, *, completed_at_utc: datetime) -> None:
        self._finalize(lease, AttemptJobState.COMPLETED, completed_at_utc, None)

    def fail(
        self, lease: AttemptLease, *, failed_at_utc: datetime, error: str
    ) -> AttemptJobState:
        state = (
            AttemptJobState.DEAD_LETTER
            if lease.attempt_count >= self._max_attempts
            else AttemptJobState.RETRY
        )
        self._finalize(lease, state, failed_at_utc, error)
        return state

    def snapshot(self, attempt_uuid: UUID) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute(
                """SELECT payload_json,state,attempt_count,received_at_utc,
                next_attempt_at_utc,completed_at_utc,last_error
                FROM ft8_attempt_inbox WHERE attempt_uuid=?""",
                (str(attempt_uuid),),
            ).fetchone()
        if row is None:
            return None
        return {
            "event": loads(row[0]),
            "state": row[1],
            "attempt_count": row[2],
            "received_at_utc": row[3],
            "next_attempt_at_utc": row[4],
            "completed_at_utc": row[5],
            "last_error": row[6],
        }

    def observe(self, *, now_utc: datetime) -> dict[str, int]:
        """Return provider-free bounded queue counts for service health."""
        now = _time(now_utc)
        with self._connect() as db:
            rows = db.execute(
                "SELECT state,COUNT(*) FROM ft8_attempt_inbox GROUP BY state"
            ).fetchall()
            due = db.execute(
                """SELECT COUNT(*) FROM ft8_attempt_inbox WHERE
                (state IN ('pending','retry') AND next_attempt_at_utc<=?) OR
                (state='processing' AND leased_until_utc<=?)""",
                (now, now),
            ).fetchone()
        counts = {str(state): int(count) for state, count in rows}
        return {
            "pending_count": counts.get("pending", 0),
            "processing_count": counts.get("processing", 0),
            "retry_count": counts.get("retry", 0),
            "completed_count": counts.get("completed", 0),
            "dead_letter_count": counts.get("dead_letter", 0),
            "due_count": int(0 if due is None else due[0]),
        }

    def _finalize(
        self,
        lease: AttemptLease,
        state: AttemptJobState,
        at_utc: datetime,
        error: str | None,
    ) -> None:
        at = _utc(at_utc)
        delay = min(
            self._retry_base * (2 ** max(0, lease.attempt_count - 1)), self._retry_max
        )
        with self._connect() as db:
            cursor = db.execute(
                """UPDATE ft8_attempt_inbox SET state=?,lease_token=NULL,
                leased_until_utc=NULL,worker_id=NULL,completed_at_utc=?,
                next_attempt_at_utc=?,last_error=? WHERE attempt_uuid=?
                AND state='processing' AND lease_token=? AND worker_id=?""",
                (
                    state.value,
                    _time(at) if state is AttemptJobState.COMPLETED else None,
                    _time(at + delay) if state is AttemptJobState.RETRY else _time(at),
                    None if error is None else (error.strip() or "unknown error")[:1000],
                    str(lease.event.attempt_uuid),
                    str(lease.lease_token),
                    lease.worker_id,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("attempt inbox lease is stale")

    def _initialize(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=NORMAL")
            db.executescript(
                """CREATE TABLE IF NOT EXISTS ft8_attempt_inbox_metadata(
                singleton_id INTEGER PRIMARY KEY CHECK(singleton_id=1),
                schema_version INTEGER NOT NULL);
                INSERT OR IGNORE INTO ft8_attempt_inbox_metadata VALUES(1,1);
                CREATE TABLE IF NOT EXISTS ft8_attempt_inbox(
                attempt_uuid TEXT PRIMARY KEY,payload_sha256 TEXT NOT NULL,
                payload_json TEXT NOT NULL,state TEXT NOT NULL CHECK(state IN
                ('pending','processing','retry','completed','dead_letter')),
                attempt_count INTEGER NOT NULL CHECK(attempt_count>=0),
                received_at_utc TEXT NOT NULL,next_attempt_at_utc TEXT NOT NULL,
                lease_token TEXT,leased_until_utc TEXT,worker_id TEXT,
                completed_at_utc TEXT,last_error TEXT);
                CREATE INDEX IF NOT EXISTS ft8_attempt_inbox_due
                ON ft8_attempt_inbox(state,next_attempt_at_utc);
                """
            )
            version = db.execute(
                "SELECT schema_version FROM ft8_attempt_inbox_metadata WHERE singleton_id=1"
            ).fetchone()
            if version != (FORGE_ATTEMPT_SCHEMA_VERSION,):
                raise RuntimeError("unsupported FT8 attempt inbox schema")

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self._path, timeout=5)
        db.execute("PRAGMA busy_timeout=5000")
        db.execute("PRAGMA foreign_keys=ON")
        return db


class VoacapAttemptHistoryRepository:
    """Append-only inputs, runs and as-of links with per-attempt diagnostics."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._initialize()

    def provenance(self, attempt_uuid: UUID) -> dict[str, Any]:
        """Return conservative provenance without modifying the source event."""
        with self._connect() as db:
            row = db.execute(
                """SELECT provenance,reason,evidence_reference,evidence_date
                FROM ft8_attempt_provenance_v1 WHERE attempt_uuid=?""",
                (str(attempt_uuid),),
            ).fetchone()
        if row is None:
            return {
                "classification": AttemptProvenance.UNKNOWN.value,
                "reason": "no audited provenance classification",
                "evidence_reference": None,
                "evidence_date": None,
                "voacap_processing_eligible": True,
                "training_eligible": False,
            }
        classification = AttemptProvenance(row[0])
        return {
            "classification": classification.value,
            "reason": row[1],
            "evidence_reference": row[2],
            "evidence_date": row[3],
            "voacap_processing_eligible": (
                classification is not AttemptProvenance.SYNTHETIC_TEST
            ),
            "training_eligible": classification is AttemptProvenance.FIELD_OBSERVED,
        }

    def processing_exclusion(self, attempt_uuid: UUID) -> dict[str, Any] | None:
        provenance = self.provenance(attempt_uuid)
        return None if provenance["voacap_processing_eligible"] else provenance

    def record_input(self, model_input: VoacapModelInput) -> str:
        input_hash = model_input.input_hash
        payload = _canonical(_model_input_payload(model_input))
        with self._connect() as db:
            db.execute(
                """INSERT OR IGNORE INTO voacap_prediction_input_v1
                (input_hash,attempt_uuid,direction,period_sequence,input_json)
                VALUES (?,?,?,?,?)""",
                (
                    input_hash,
                    str(model_input.attempt_uuid),
                    model_input.direction.value,
                    model_input.period_sequence,
                    payload,
                ),
            )
            row = db.execute(
                "SELECT input_json FROM voacap_prediction_input_v1 WHERE input_hash=?",
                (input_hash,),
            ).fetchone()
            if row != (payload,):
                raise RuntimeError("VOACAP input hash collision or changed canonical input")
        return input_hash

    def record_run(
        self,
        model_input: VoacapModelInput,
        *,
        requested_at_utc: datetime,
        available_at_utc: datetime,
        status: VoacapRunStatus,
        relation: VoacapRelation,
        result: VoacapProviderResult | None = None,
        failure_reason: str | None = None,
    ) -> UUID:
        requested_at = _utc(requested_at_utc)
        available_at = _utc(available_at_utc)
        if available_at < requested_at:
            raise ValueError("VOACAP availability cannot precede its request")
        if status is VoacapRunStatus.READY:
            if result is None or not _has_modeled_values(result) or failure_reason is not None:
                raise ValueError("ready VOACAP run requires modeled values and no failure")
        elif status is VoacapRunStatus.UNAVAILABLE:
            if result is None or _has_modeled_values(result):
                raise ValueError("unavailable VOACAP run requires a response without modeled values")
        elif result is not None:
            raise ValueError(f"{status.value} VOACAP run cannot contain a provider result")
        if status is not VoacapRunStatus.READY and not (failure_reason or "").strip():
            raise ValueError(f"{status.value} VOACAP run requires a reason")
        if result is not None:
            if model_input.model_service_version is None:
                model_input = model_input.model_copy(
                    update={"model_service_version": result.service_version}
                )
            elif model_input.model_service_version != result.service_version:
                raise ValueError("VOACAP input and result service versions must match")
        input_hash = self.record_input(model_input)
        run_uuid = uuid4()
        request_json = model_input.provider_request()
        response_json = None if result is None else result.response_json
        response_digest = (
            None
            if response_json is None
            else hashlib.sha256(_canonical(response_json).encode()).hexdigest()
        )
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                """INSERT INTO voacap_prediction_run_v1
                (prediction_uuid,input_hash,requested_at_utc,available_at_utc,status,
                 failure_reason,request_json,response_json,response_sha256,service_version,
                 reliability_fraction,snr_db_hz,muf_mhz,rating)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    str(run_uuid),
                    input_hash,
                    _time(requested_at),
                    _time(available_at),
                    status.value,
                    failure_reason,
                    None if request_json is None else _canonical(request_json),
                    None if response_json is None else _canonical(response_json),
                    response_digest,
                    None if result is None else result.service_version,
                    None if result is None else result.reliability_fraction,
                    None if result is None else result.snr_db_hz,
                    None if result is None else result.muf_mhz,
                    None if result is None else result.rating,
                ),
            )
            db.execute(
                """INSERT INTO voacap_attempt_link_v1
                (attempt_uuid,direction,input_hash,prediction_uuid,relation,
                 as_of_cutoff_utc,training_eligible)
                VALUES (?,?,?,?,?,?,?)""",
                (
                    str(model_input.attempt_uuid),
                    model_input.direction.value,
                    input_hash,
                    str(run_uuid),
                    relation.value,
                    _time(model_input.choice_at_utc),
                    int(
                        status is VoacapRunStatus.READY
                        and result is not None
                        and self.provenance(model_input.attempt_uuid)["training_eligible"]
                        and relation is VoacapRelation.PRE_CHOICE
                        and available_at <= model_input.choice_at_utc
                    ),
                ),
            )
        return run_uuid

    def has_terminal_run(self, input_hash: str) -> bool:
        """Return whether this exact versioned scientific input is terminal."""
        with self._connect() as db:
            row = db.execute(
                """SELECT 1 FROM voacap_prediction_run_v1
                WHERE input_hash=? AND status IN ('ready','unavailable','skipped')
                LIMIT 1""",
                (input_hash,),
            ).fetchone()
        return row is not None

    def has_terminal_run_for_input(self, model_input: VoacapModelInput) -> bool:
        """Check exact identity, with a no-egress fallback for legacy identities."""
        if self.has_terminal_run(model_input.input_hash):
            return True
        requested_version = model_input.model_service_version
        requested_legacy_payload = _canonical(
            _model_input_payload(
                model_input.model_copy(update={"model_service_version": None})
            )
        )
        with self._connect() as db:
            rows = db.execute(
                """SELECT i.input_json,r.service_version
                FROM voacap_prediction_input_v1 i
                JOIN voacap_prediction_run_v1 r ON r.input_hash=i.input_hash
                WHERE i.attempt_uuid=? AND i.direction=?
                AND i.period_sequence IS ?
                AND r.status IN ('ready','unavailable','skipped')""",
                (
                    str(model_input.attempt_uuid),
                    model_input.direction.value,
                    model_input.period_sequence,
                ),
            ).fetchall()
        for input_json, run_service_version in rows:
            stored_input = VoacapModelInput.model_validate_json(input_json)
            stored_legacy_payload = _canonical(
                _model_input_payload(
                    stored_input.model_copy(update={"model_service_version": None})
                )
            )
            if stored_legacy_payload != requested_legacy_payload:
                continue
            if requested_version is None:
                return True
            if (
                stored_input.model_service_version is None
                and run_service_version == requested_version
            ):
                return True
        return False

    def diagnostics(self, attempt_uuid: UUID) -> dict[str, Any]:
        provenance = self.provenance(attempt_uuid)
        with self._connect() as db:
            rows = db.execute(
                """SELECT l.direction,l.relation,l.as_of_cutoff_utc,l.training_eligible,
                i.input_hash,i.input_json,r.prediction_uuid,r.requested_at_utc,
                r.available_at_utc,r.status,r.failure_reason,r.request_json,
                r.response_json,r.response_sha256,r.service_version,
                r.reliability_fraction,r.snr_db_hz,r.muf_mhz,r.rating
                FROM voacap_attempt_link_v1 l
                JOIN voacap_prediction_input_v1 i ON i.input_hash=l.input_hash
                JOIN voacap_prediction_run_v1 r ON r.prediction_uuid=l.prediction_uuid
                WHERE l.attempt_uuid=?
                ORDER BY l.direction,i.period_sequence,r.requested_at_utc,r.rowid""",
                (str(attempt_uuid),),
            ).fetchall()
        keys = (
            "direction", "relation", "as_of_cutoff_utc", "training_eligible",
            "input_hash", "input", "prediction_uuid", "requested_at_utc",
            "available_at_utc", "status", "failure_reason", "request", "response",
            "response_sha256", "service_version", "reliability_fraction",
            "snr_db_hz", "muf_mhz", "rating",
        )
        items = []
        for row in rows:
            item = dict(zip(keys, row, strict=True))
            for key in ("input", "request", "response"):
                item[key] = None if item[key] is None else loads(item[key])
            item["training_eligible"] = bool(item["training_eligible"])
            items.append(item)
        return {
            "schema_version": "1",
            "attempt_uuid": str(attempt_uuid),
            "provenance": provenance,
            "semantic_notes": {
                "reliability_fraction": "modeled-day circuit reliability, not QSO odds",
                "snr_db_hz": "VOACAP dB-Hz; not FT8 decoder dB",
                "missing": "unknown or unavailable; never zero",
                "retrospective": "calculated after the attempt; not pre-choice evidence",
            },
            "correlations": items,
        }

    def _initialize(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=NORMAL")
            db.executescript(
                """CREATE TABLE IF NOT EXISTS voacap_attempt_schema_metadata(
                singleton_id INTEGER PRIMARY KEY CHECK(singleton_id=1),
                schema_version INTEGER NOT NULL);
                INSERT OR IGNORE INTO voacap_attempt_schema_metadata VALUES(1,1);
                CREATE TABLE IF NOT EXISTS voacap_prediction_input_v1(
                input_hash TEXT PRIMARY KEY,attempt_uuid TEXT NOT NULL,direction TEXT NOT NULL,
                period_sequence INTEGER,input_json TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS voacap_input_attempt
                ON voacap_prediction_input_v1(attempt_uuid,direction);
                CREATE TABLE IF NOT EXISTS voacap_prediction_run_v1(
                prediction_uuid TEXT PRIMARY KEY,input_hash TEXT NOT NULL REFERENCES
                voacap_prediction_input_v1(input_hash),requested_at_utc TEXT NOT NULL,
                available_at_utc TEXT NOT NULL,status TEXT NOT NULL,failure_reason TEXT,
                request_json TEXT,response_json TEXT,response_sha256 TEXT,service_version TEXT,
                reliability_fraction REAL,snr_db_hz REAL,muf_mhz REAL,rating TEXT);
                CREATE TABLE IF NOT EXISTS voacap_attempt_link_v1(
                attempt_uuid TEXT NOT NULL,direction TEXT NOT NULL,input_hash TEXT NOT NULL,
                prediction_uuid TEXT NOT NULL REFERENCES voacap_prediction_run_v1(prediction_uuid),
                relation TEXT NOT NULL,as_of_cutoff_utc TEXT NOT NULL,
                training_eligible INTEGER NOT NULL CHECK(training_eligible IN(0,1)),
                PRIMARY KEY(attempt_uuid,direction,input_hash,prediction_uuid));
                CREATE TABLE IF NOT EXISTS ft8_attempt_provenance_v1(
                attempt_uuid TEXT PRIMARY KEY,
                provenance TEXT NOT NULL CHECK(provenance IN
                ('field_observed','synthetic_test')),
                reason TEXT NOT NULL,evidence_reference TEXT NOT NULL,
                evidence_date TEXT NOT NULL);
                """
            )
            for attempt_uuid, provenance, reason, evidence, evidence_date in (
                DOCUMENTED_SYNTHETIC_ATTEMPTS
            ):
                db.execute(
                    """INSERT OR IGNORE INTO ft8_attempt_provenance_v1
                    (attempt_uuid,provenance,reason,evidence_reference,evidence_date)
                    VALUES (?,?,?,?,?)""",
                    (
                        str(attempt_uuid),
                        provenance,
                        reason,
                        evidence,
                        evidence_date,
                    ),
                )
                stored = db.execute(
                    """SELECT provenance,reason,evidence_reference,evidence_date
                    FROM ft8_attempt_provenance_v1 WHERE attempt_uuid=?""",
                    (str(attempt_uuid),),
                ).fetchone()
                expected = (provenance, reason, evidence, evidence_date)
                if stored != expected:
                    raise RuntimeError(
                        f"documented attempt provenance conflict: {attempt_uuid}"
                    )
            version = db.execute(
                "SELECT schema_version FROM voacap_attempt_schema_metadata "
                "WHERE singleton_id=1"
            ).fetchone()
            if version != (MODEL_INPUT_SCHEMA_VERSION,):
                raise RuntimeError("unsupported VOACAP attempt history schema")

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self._path, timeout=5)
        db.execute("PRAGMA busy_timeout=5000")
        db.execute("PRAGMA foreign_keys=ON")
        return db


class FT8AttemptCorrelationWorker:
    """Correlate each direction/power input; failures retry the independent job."""

    def __init__(
        self,
        inbox: AttemptInboxRepository,
        history: VoacapAttemptHistoryRepository,
        client: VoacapAttemptClient,
        *,
        worker_id: str,
        batch_size: int = 20,
        lease_duration: timedelta = timedelta(minutes=5),
        model_service_version: str | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if not 1 <= batch_size <= _MAX_BATCH:
            raise ValueError(f"batch_size must be between 1 and {_MAX_BATCH}")
        if lease_duration <= timedelta(0):
            raise ValueError("lease_duration must be positive")
        if model_service_version is not None:
            model_service_version = model_service_version.strip()
            if not 1 <= len(model_service_version) <= 120:
                raise ValueError("model_service_version must contain 1..120 characters")
        self._inbox = inbox
        self._history = history
        self._client = client
        self._worker_id = worker_id
        self._batch_size = batch_size
        self._lease_duration = lease_duration
        self._model_service_version = model_service_version
        self._clock = clock

    def run_once(self, *, now_utc: datetime) -> tuple[int, int]:
        completed = failed = 0
        leases = self._inbox.claim_due(
            now_utc=now_utc,
            worker_id=self._worker_id,
            lease_duration=self._lease_duration,
            limit=self._batch_size,
        )
        for lease in leases:
            try:
                if self._history.processing_exclusion(lease.event.attempt_uuid) is not None:
                    self._inbox.finish(lease, completed_at_utc=self._now())
                    completed += 1
                    continue
                model_inputs = tuple(
                    model_input.model_copy(
                        update={"model_service_version": self._model_service_version}
                    )
                    for model_input in model_inputs_for_attempt(lease.event)
                )
                # Persist deterministic missing-input directions before any provider
                # request.  A forward outage must not erase the scientific fact that
                # reverse correlation was skipped because remote power is unknown.
                for model_input in model_inputs:
                    request = model_input.provider_request()
                    if request is None and not self._history.has_terminal_run_for_input(
                        model_input
                    ):
                        self._history.record_run(
                            model_input,
                            requested_at_utc=now_utc,
                            available_at_utc=now_utc,
                            status=VoacapRunStatus.SKIPPED,
                            relation=VoacapRelation.RETROSPECTIVE,
                            failure_reason="required model input missing",
                        )
                for model_input in model_inputs:
                    request = model_input.provider_request()
                    if request is None:
                        continue
                    if self._history.has_terminal_run_for_input(model_input):
                        continue
                    requested_at = self._now()
                    try:
                        result = self._client.predict(model_input)
                    except Exception as error:
                        self._history.record_run(
                            model_input,
                            requested_at_utc=requested_at,
                            available_at_utc=self._now(),
                            status=VoacapRunStatus.FAILED,
                            relation=VoacapRelation.RETROSPECTIVE,
                            failure_reason=(str(error) or error.__class__.__name__)[:1000],
                        )
                        raise
                    versioned_input = (
                        model_input.model_copy(
                            update={"model_service_version": result.service_version}
                        )
                        if model_input.model_service_version is None
                        else model_input
                    )
                    status = (
                        VoacapRunStatus.READY
                        if _has_modeled_values(result)
                        else VoacapRunStatus.UNAVAILABLE
                    )
                    self._history.record_run(
                        versioned_input,
                        requested_at_utc=requested_at,
                        available_at_utc=self._now(),
                        status=status,
                        relation=VoacapRelation.RETROSPECTIVE,
                        result=result,
                        failure_reason=(
                            None
                            if status is VoacapRunStatus.READY
                            else "provider response has no modeled values for requested UTC hour/band"
                        ),
                    )
                self._inbox.finish(lease, completed_at_utc=self._now())
                completed += 1
            except Exception as error:  # noqa: BLE001 - jobs are failure-isolated
                self._inbox.fail(
                    lease,
                    failed_at_utc=now_utc,
                    error=str(error) or error.__class__.__name__,
                )
                failed += 1
        return completed, failed

    def _now(self) -> datetime:
        return _utc(self._clock())


def model_inputs_for_attempt(event: FT8AttemptEvent) -> tuple[VoacapModelInput, ...]:
    local_grid = _model_grid(event.local_grid)
    remote_grid = _model_grid(event.remote_grid)
    common: dict[str, Any] = {
        "attempt_uuid": event.attempt_uuid,
        "choice_at_utc": event.started_at_utc,
    }
    forward_periods = tuple(period for period in event.tx_periods if period.transmitted)
    if not forward_periods:
        forward: tuple[VoacapModelInput, ...] = (
            VoacapModelInput(
                **common,
                direction=VoacapDirection.LOCAL_TO_REMOTE,
                event_hour_utc=event.started_at_utc,
                frequency_hz=event.dial_frequency_hz,
                band=event.band,
                tx_grid=local_grid,
                rx_grid=remote_grid,
                tx_grid_precision=_precision(local_grid),
                rx_grid_precision=_precision(remote_grid),
                grid_point_assumption=_grid_assumption(local_grid, remote_grid),
            ),
        )
    else:
        forward = tuple(
            VoacapModelInput(
                **common,
                direction=VoacapDirection.LOCAL_TO_REMOTE,
                period_sequence=period.sequence,
                event_hour_utc=period.started_at_utc,
                frequency_hz=period.frequency_hz,
                band=_band_for_frequency(period.frequency_hz),
                tx_grid=local_grid,
                rx_grid=remote_grid,
                tx_grid_precision=_precision(local_grid),
                rx_grid_precision=_precision(remote_grid),
                grid_point_assumption=_grid_assumption(local_grid, remote_grid),
                tx_power_watts=(
                    period.configured_power_watts
                    if period.power_source == "cat_configured_readback"
                    else None
                ),
                tx_power_source=(
                    "cat_configured_readback"
                    if period.power_source == "cat_configured_readback"
                    else None
                ),
            )
            for period in forward_periods
        )
    reverse = VoacapModelInput(
        **common,
        direction=VoacapDirection.REMOTE_TO_LOCAL,
        event_hour_utc=event.started_at_utc,
        frequency_hz=event.dial_frequency_hz,
        band=event.band,
        tx_grid=remote_grid,
        rx_grid=local_grid,
        tx_grid_precision=_precision(remote_grid),
        rx_grid_precision=_precision(local_grid),
        grid_point_assumption=_grid_assumption(remote_grid, local_grid),
        # Remote station power is not observed by Rolling Thunder.
        tx_power_watts=None,
        tx_power_source=None,
    )
    return forward + (reverse,)


def _model_grid(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        normalized = str(_GRID_ADAPTER.validate_python(value))
    except ValidationError:
        return None
    return normalized if len(normalized) in (4, 6) else None


def _precision(grid: str | None) -> int | None:
    return None if grid is None else len(grid)


def _grid_assumption(
    tx_grid: str | None, rx_grid: str | None
) -> Literal["maidenhead_cell_center"] | None:
    return None if tx_grid is None or rx_grid is None else "maidenhead_cell_center"


def _band_for_frequency(frequency_hz: int) -> str | None:
    try:
        return resolve_radio_band(Frequency(hz=frequency_hz)).value
    except RadioBandResolutionError:
        return None


def _canonical(value: object) -> str:
    return dumps(value, sort_keys=True, separators=(",", ":"))


def _model_input_payload(model_input: VoacapModelInput) -> dict[str, Any]:
    """Preserve legacy hashes while binding known service versions going forward."""
    payload = model_input.model_dump(mode="json")
    if model_input.model_service_version is None:
        payload.pop("model_service_version")
    return payload


def _has_modeled_values(result: VoacapProviderResult) -> bool:
    return any(
        value is not None
        for value in (
            result.reliability_fraction,
            result.snr_db_hz,
            result.muf_mhz,
            result.rating,
        )
    )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC)


def _time(value: datetime) -> str:
    return _utc(value).isoformat().replace("+00:00", "Z")
