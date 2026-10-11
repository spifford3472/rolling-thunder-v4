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

from pydantic import Field, field_validator

from rolling_thunder.domain import DomainModel
from rolling_thunder.ft8.attempt_ledger import FT8AttemptEvent

FORGE_ATTEMPT_SCHEMA_VERSION = 1
MODEL_INPUT_SCHEMA_VERSION = 1
_MAX_BATCH = 100


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
        return hashlib.sha256(_canonical(self.model_dump(mode="json")).encode()).hexdigest()

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

    def record_input(self, model_input: VoacapModelInput) -> str:
        input_hash = model_input.input_hash
        payload = _canonical(model_input.model_dump(mode="json"))
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
                    _time(requested_at_utc),
                    _time(available_at_utc),
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
                        relation is VoacapRelation.PRE_CHOICE
                        and _utc(available_at_utc) <= model_input.choice_at_utc
                    ),
                ),
            )
        return run_uuid

    def has_terminal_run(self, input_hash: str) -> bool:
        """Reconcile a lease replay without repeating already-durable provider work."""
        with self._connect() as db:
            row = db.execute(
                """SELECT 1 FROM voacap_prediction_run_v1
                WHERE input_hash=? AND status IN ('ready','unavailable','skipped')
                LIMIT 1""",
                (input_hash,),
            ).fetchone()
        return row is not None

    def diagnostics(self, attempt_uuid: UUID) -> dict[str, Any]:
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
                """
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
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._inbox = inbox
        self._history = history
        self._client = client
        self._worker_id = worker_id
        self._batch_size = batch_size
        self._lease_duration = lease_duration
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
            results_by_request: dict[str, VoacapProviderResult] = {}
            try:
                for model_input in model_inputs_for_attempt(lease.event):
                    if self._history.has_terminal_run(model_input.input_hash):
                        continue
                    request = model_input.provider_request()
                    if request is None:
                        self._history.record_run(
                            model_input,
                            requested_at_utc=now_utc,
                            available_at_utc=now_utc,
                            status=VoacapRunStatus.SKIPPED,
                            relation=VoacapRelation.RETROSPECTIVE,
                            failure_reason="required model input missing",
                        )
                        continue
                    requested_at = now_utc
                    request_hash = hashlib.sha256(_canonical(request).encode()).hexdigest()
                    result = results_by_request.get(request_hash)
                    if result is None:
                        try:
                            result = self._client.predict(model_input)
                        except Exception as error:
                            self._history.record_run(
                                model_input,
                                requested_at_utc=requested_at,
                                available_at_utc=self._now(),
                                status=VoacapRunStatus.FAILED,
                                relation=VoacapRelation.RETROSPECTIVE,
                                failure_reason=(
                                    str(error) or error.__class__.__name__
                                )[:1000],
                            )
                            raise
                        results_by_request[request_hash] = result
                    self._history.record_run(
                        model_input,
                        requested_at_utc=requested_at,
                        available_at_utc=self._now(),
                        status=VoacapRunStatus.READY,
                        relation=VoacapRelation.RETROSPECTIVE,
                        result=result,
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
    common: dict[str, Any] = {
        "attempt_uuid": event.attempt_uuid,
        "choice_at_utc": event.started_at_utc,
        "event_hour_utc": event.started_at_utc,
        "frequency_hz": event.dial_frequency_hz,
        "band": event.band,
    }
    forward_periods = tuple(period for period in event.tx_periods if period.transmitted)
    if not forward_periods:
        forward: tuple[VoacapModelInput, ...] = (
            VoacapModelInput(
                **common,
                direction=VoacapDirection.LOCAL_TO_REMOTE,
                tx_grid=event.local_grid,
                rx_grid=event.remote_grid,
                tx_grid_precision=_precision(event.local_grid),
                rx_grid_precision=_precision(event.remote_grid),
                grid_point_assumption=_grid_assumption(event.local_grid, event.remote_grid),
            ),
        )
    else:
        forward = tuple(
            VoacapModelInput(
                **common,
                direction=VoacapDirection.LOCAL_TO_REMOTE,
                period_sequence=period.sequence,
                tx_grid=event.local_grid,
                rx_grid=event.remote_grid,
                tx_grid_precision=_precision(event.local_grid),
                rx_grid_precision=_precision(event.remote_grid),
                grid_point_assumption=_grid_assumption(event.local_grid, event.remote_grid),
                tx_power_watts=period.configured_power_watts,
                tx_power_source=period.power_source,
            )
            for period in forward_periods
        )
    reverse = VoacapModelInput(
        **common,
        direction=VoacapDirection.REMOTE_TO_LOCAL,
        tx_grid=event.remote_grid,
        rx_grid=event.local_grid,
        tx_grid_precision=_precision(event.remote_grid),
        rx_grid_precision=_precision(event.local_grid),
        grid_point_assumption=_grid_assumption(event.remote_grid, event.local_grid),
        # Remote station power is not observed by Rolling Thunder.
        tx_power_watts=None,
        tx_power_source=None,
    )
    return forward + (reverse,)


def _precision(grid: str | None) -> int | None:
    return None if grid is None else len(grid)


def _grid_assumption(
    tx_grid: str | None, rx_grid: str | None
) -> Literal["maidenhead_cell_center"] | None:
    return None if tx_grid is None or rx_grid is None else "maidenhead_cell_center"


def _canonical(value: object) -> str:
    return dumps(value, sort_keys=True, separators=(",", ":"))


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC)


def _time(value: datetime) -> str:
    return _utc(value).isoformat().replace("+00:00", "Z")
