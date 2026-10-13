"""Disabled-by-default C4 historical/pre-choice VOACAP baseline sampling.

This module is deliberately provider-neutral.  A caller must inject a provider,
clock and SQLite repository; no network adapter or process composition lives here.
"""

from __future__ import annotations

import hashlib
import math
import sqlite3
import threading
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from json import dumps, loads
from pathlib import Path
from typing import Any, Literal, Protocol, Self
from uuid import UUID, uuid4

from pydantic import Field, TypeAdapter, field_validator, model_validator

from rolling_thunder.domain import DomainModel
from rolling_thunder.value_types import MaidenheadGrid

BASELINE_SCHEMA_VERSION = 1
SUPPORTED_BANDS = (40, 30, 20, 17, 15, 12, 10)
SCHEDULE_HOURS_UTC = (0, 6, 12, 18)
REFERENCE_POWER_WATTS = 20
_MAX_ERROR = 500
_GRID_ADAPTER = TypeAdapter(MaidenheadGrid)


class BaselineStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    RETRY = "retry"
    READY = "ready"
    UNAVAILABLE = "unavailable"
    SKIPPED = "skipped"
    FAILED = "failed"
    MISSED = "missed"


class TimingClass(StrEnum):
    PRE_CHOICE = "pre_choice"
    LATE = "late"
    BACKFILL = "backfill"
    MISSED = "missed"


TERMINAL_STATUSES = {
    BaselineStatus.READY,
    BaselineStatus.UNAVAILABLE,
    BaselineStatus.SKIPPED,
    BaselineStatus.FAILED,
    BaselineStatus.MISSED,
}


class TargetGrid(DomainModel):
    region_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9._:-]+$")
    grid: str = Field(min_length=4, max_length=6)
    uncertainty: str = Field(min_length=1, max_length=160)

    @field_validator("grid")
    @classmethod
    def normalize_grid(cls, value: str) -> str:
        return _GRID_ADAPTER.validate_python(value.upper())

    @property
    def precision(self) -> int:
        return len(self.grid)


class BaselinePlan(DomainModel):
    """Immutable, explicitly bounded plan. A changed model creates a new plan."""

    schema_version: Literal[1] = 1
    plan_id: UUID
    plan_version: str = Field(min_length=1, max_length=80)
    parent_plan_id: UUID | None = None
    created_at_utc: datetime
    origin_grid: str = Field(min_length=6, max_length=6)
    origin_uncertainty: str = Field(min_length=1, max_length=160)
    target_inventory_version: str = Field(min_length=1, max_length=80)
    targets: tuple[TargetGrid, ...] = Field(min_length=1, max_length=64)
    bands_m: tuple[int, ...] = SUPPORTED_BANDS
    hours_utc: tuple[int, ...] = SCHEDULE_HOURS_UTC
    reference_power_watts: Literal[20] = 20
    model_version: str = Field(min_length=1, max_length=120)
    service_version: str = Field(min_length=1, max_length=120)
    ssn_source: str = Field(min_length=1, max_length=200)
    ssn_source_version: str = Field(min_length=1, max_length=120)
    ssn_value_semantics: Literal["monthly_smoothed_predicted_sunspot_number"]
    ssn_source_schema: str = Field(min_length=1, max_length=160)
    ssn_revision_policy: str = Field(min_length=1, max_length=300)
    max_provider_calls_per_cycle: int = Field(default=8, ge=1, le=64)
    max_provider_calls_per_day: int = Field(default=128, ge=1, le=1024)
    max_slots_per_cycle: int = Field(default=64, ge=1, le=512)
    provider_timeout_s: float = Field(default=10.0, ge=1.0, le=60.0)
    response_size_limit_bytes: int = Field(default=1_000_000, ge=1024, le=10_000_000)
    storage_limit_bytes: int = Field(default=250_000_000, ge=1_000_000)
    lease_seconds: int = Field(default=120, ge=10, le=3600)
    max_attempts: int = Field(default=3, ge=1, le=10)
    retry_base_seconds: int = Field(default=60, ge=1, le=86400)
    retry_cap_seconds: int = Field(default=3600, ge=1, le=604800)
    backlog_limit_days: int = Field(default=2, ge=0, le=31)
    concurrency: Literal[1] = 1

    @field_validator("created_at_utc")
    @classmethod
    def utc_time(cls, value: datetime) -> datetime:
        return _utc(value)

    @field_validator("origin_grid")
    @classmethod
    def origin_grid6(cls, value: str) -> str:
        normalized = _GRID_ADAPTER.validate_python(value.upper())
        if len(normalized) != 6:
            raise ValueError("origin_grid must be frozen grid6")
        return normalized

    @model_validator(mode="after")
    def exact_contract(self) -> Self:
        if self.bands_m != SUPPORTED_BANDS:
            raise ValueError("bands_m must equal the C4 supported-band inventory")
        if self.hours_utc != SCHEDULE_HOURS_UTC:
            raise ValueError("hours_utc must equal 00/06/12/18 UTC")
        if self.retry_cap_seconds < self.retry_base_seconds:
            raise ValueError("retry cap must be at least retry base")
        identities = {(target.region_id, target.grid) for target in self.targets}
        if len(identities) != len(self.targets):
            raise ValueError("target inventory contains duplicates")
        return self

    @property
    def canonical_sha256(self) -> str:
        return _sha(self.model_dump(mode="json"))


class EnvironmentSnapshot(DomainModel):
    schema_version: Literal[2] = 2
    ssn: float = Field(ge=0)
    value_semantics: Literal["monthly_smoothed_predicted_sunspot_number"]
    target_month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    source: str = Field(min_length=1, max_length=200)
    source_url: str = Field(min_length=1, max_length=500)
    source_version: str = Field(min_length=1, max_length=120)
    source_schema: str = Field(min_length=1, max_length=160)
    source_revision_policy: str = Field(min_length=1, max_length=300)
    source_record_id: str = Field(min_length=1, max_length=200)
    source_released_at_utc: datetime | None = None
    captured_at_utc: datetime
    raw_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshot_canonical_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("source_released_at_utc", "captured_at_utc")
    @classmethod
    def utc_times(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _utc(value)

    @model_validator(mode="after")
    def temporal_provenance(self) -> Self:
        if (
            self.source_released_at_utc is not None
            and self.source_released_at_utc > self.captured_at_utc
        ):
            raise ValueError("SSN source release cannot postdate capture")
        return self


class ProviderResult(DomainModel):
    response_json: dict[str, Any]
    service_version: str = Field(min_length=1, max_length=120)
    model_version: str = Field(min_length=1, max_length=120)


class BaselineProvider(Protocol):
    def predict(self, request: Mapping[str, Any], *, timeout_s: float) -> ProviderResult: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


class BaselineConfig(DomainModel):
    enabled: bool = False
    scheduler_enabled: bool = False
    provider_enabled: bool = False

    @model_validator(mode="after")
    def gates(self) -> Self:
        if self.scheduler_enabled and not self.enabled:
            raise ValueError("scheduler requires process enabled")
        if self.provider_enabled and not self.scheduler_enabled:
            raise ValueError("provider requires scheduler enabled")
        return self


class ProviderFailure(RuntimeError):
    """Typed provider failure suitable for durable status without response bodies."""

    def __init__(self, reason: str, *, retryable: bool) -> None:
        super().__init__(reason)
        self.reason = reason
        self.retryable = retryable


class BaselineRepository:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._initialize()

    def add_plan(self, plan: BaselinePlan) -> bool:
        payload = plan.model_dump_json()
        with self._connect() as db:
            if plan.parent_plan_id is not None:
                parent = db.execute(
                    "SELECT 1 FROM baseline_plan_v1 WHERE plan_id=?",
                    (str(plan.parent_plan_id),),
                ).fetchone()
                if parent is None:
                    raise ValueError("parent plan does not exist")
            existing = db.execute(
                "SELECT canonical_sha256 FROM baseline_plan_v1 WHERE plan_id=?",
                (str(plan.plan_id),),
            ).fetchone()
            if existing is not None:
                if existing[0] != plan.canonical_sha256:
                    raise ValueError("plan UUID replay changed immutable content")
                return False
            db.execute(
                """INSERT INTO baseline_plan_v1
                (plan_id,parent_plan_id,plan_version,model_version,service_version,
                 created_at_utc,canonical_sha256,payload_json)
                VALUES (?,?,?,?,?,?,?,?)""",
                (
                    str(plan.plan_id),
                    None if plan.parent_plan_id is None else str(plan.parent_plan_id),
                    plan.plan_version,
                    plan.model_version,
                    plan.service_version,
                    _time(plan.created_at_utc),
                    plan.canonical_sha256,
                    payload,
                ),
            )
        return True

    def schedule_day(
        self,
        plan: BaselinePlan,
        day: date,
        environment: EnvironmentSnapshot,
        *,
        scheduled_at_utc: datetime,
    ) -> int:
        self.add_plan(plan)
        if (
            environment.source != plan.ssn_source
            or environment.source_version != plan.ssn_source_version
            or environment.value_semantics != plan.ssn_value_semantics
            or environment.source_schema != plan.ssn_source_schema
            or environment.source_revision_policy != plan.ssn_revision_policy
        ):
            raise ValueError("environment SSN identity does not match immutable plan")
        target_month = f"{day.year:04d}-{day.month:02d}"
        if environment.target_month != target_month:
            raise ValueError("environment SSN target month does not match scheduled day")
        scheduled = _utc(scheduled_at_utc)
        rows: list[tuple[Any, ...]] = []
        for target in plan.targets:
            for band in plan.bands_m:
                for hour in plan.hours_utc:
                    forecast = datetime(day.year, day.month, day.day, hour, tzinfo=UTC)
                    slot_key = _sha(
                        {
                            "plan_id": str(plan.plan_id),
                            "forecast_for_utc": _time(forecast),
                            "region_id": target.region_id,
                            "grid": target.grid,
                            "band_m": band,
                        }
                    )
                    rows.append(
                        (
                            slot_key,
                            str(plan.plan_id),
                            _time(forecast),
                            _time(scheduled),
                            target.region_id,
                            target.grid,
                            target.precision,
                            target.uncertainty,
                            band,
                            environment.ssn,
                            environment.source,
                            environment.source_version,
                            environment.value_semantics,
                            environment.target_month,
                            environment.source_url,
                            environment.source_schema,
                            environment.source_revision_policy,
                            environment.source_record_id,
                            None if environment.source_released_at_utc is None else _time(
                                environment.source_released_at_utc
                            ),
                            _time(environment.captured_at_utc),
                            environment.raw_sha256,
                            environment.snapshot_canonical_sha256,
                            _time(scheduled),
                        )
                    )
        inserted = 0
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for row in rows:
                cursor = db.execute(
                    """INSERT OR IGNORE INTO baseline_slot_v1
                    (slot_key,plan_id,forecast_for_utc,scheduled_at_utc,region_id,
                     target_grid,target_grid_precision,target_uncertainty,band_m,ssn,
                     ssn_source,ssn_source_version,ssn_value_semantics,ssn_target_month,
                     ssn_source_url,ssn_source_schema,ssn_revision_policy,ssn_source_record_id,
                     ssn_source_released_at_utc,ssn_captured_at_utc,ssn_raw_sha256,
                     ssn_snapshot_sha256,
                     next_attempt_at_utc,status,attempt_count)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'pending',0)""",
                    row,
                )
                inserted += cursor.rowcount
            self._ledger(db, plan.plan_id, scheduled, "scheduled", {"inserted": inserted})
        return inserted

    def claim_one(self, plan: BaselinePlan, now: datetime) -> dict[str, Any] | None:
        now = _utc(now)
        cutoff = now - timedelta(days=plan.backlog_limit_days)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                """UPDATE baseline_slot_v1 SET status='missed',timing_class='missed',
                generated_at_utc=?,reason='restart_backlog_limit',lease_token=NULL,
                leased_until_utc=NULL WHERE plan_id=? AND status IN ('pending','retry')
                AND forecast_for_utc<?""",
                (_time(now), str(plan.plan_id), _time(cutoff)),
            )
            db.execute(
                """UPDATE baseline_slot_v1 SET status=CASE WHEN attempt_count>=? THEN 'failed'
                ELSE 'retry' END, reason='expired_lease',lease_token=NULL,leased_until_utc=NULL
                WHERE plan_id=? AND status='processing' AND leased_until_utc<=?""",
                (plan.max_attempts, str(plan.plan_id), _time(now)),
            )
            active = db.execute(
                """SELECT 1 FROM baseline_slot_v1 WHERE status='processing'
                AND leased_until_utc>? LIMIT 1""",
                (_time(now),),
            ).fetchone()
            if active is not None:
                return None
            row = db.execute(
                """SELECT slot_key,forecast_for_utc,scheduled_at_utc,region_id,target_grid,
                target_grid_precision,target_uncertainty,band_m,ssn,ssn_source,
                ssn_source_version,ssn_value_semantics,ssn_target_month,ssn_source_url,
                ssn_source_schema,ssn_revision_policy,ssn_source_record_id,
                ssn_source_released_at_utc,ssn_captured_at_utc,ssn_raw_sha256,
                ssn_snapshot_sha256,attempt_count
                FROM baseline_slot_v1 WHERE plan_id=? AND status IN ('pending','retry')
                AND next_attempt_at_utc<=? ORDER BY forecast_for_utc,band_m,region_id LIMIT 1""",
                (str(plan.plan_id), _time(now)),
            ).fetchone()
            if row is None:
                return None
            token = str(uuid4())
            db.execute(
                """UPDATE baseline_slot_v1 SET status='processing',attempt_count=attempt_count+1,
                lease_token=?,leased_until_utc=? WHERE slot_key=?""",
                (token, _time(now + timedelta(seconds=plan.lease_seconds)), row[0]),
            )
        keys = (
            "slot_key", "forecast_for_utc", "scheduled_at_utc", "region_id", "target_grid",
            "target_grid_precision", "target_uncertainty", "band_m", "ssn", "ssn_source",
            "ssn_source_version", "ssn_value_semantics", "ssn_target_month", "ssn_source_url",
            "ssn_source_schema", "ssn_revision_policy", "ssn_source_record_id",
            "ssn_source_released_at_utc", "ssn_captured_at_utc", "ssn_raw_sha256",
            "ssn_snapshot_sha256", "attempt_count",
        )
        result = dict(zip(keys, row, strict=True))
        result["attempt_count"] = int(result["attempt_count"]) + 1
        result["lease_token"] = token
        return result

    def cached_response(self, request_sha256: str) -> ProviderResult | None:
        with self._connect() as db:
            row = db.execute(
                """SELECT response_json,service_version,model_version FROM baseline_provider_response_v1
                WHERE request_sha256=?""",
                (request_sha256,),
            ).fetchone()
        if row is None:
            return None
        return ProviderResult(response_json=loads(row[0]), service_version=row[1], model_version=row[2])

    def complete(
        self,
        plan: BaselinePlan,
        claim: Mapping[str, Any],
        *,
        now: datetime,
        status: BaselineStatus,
        reason: str,
        timing_class: TimingClass,
        request: Mapping[str, Any],
        result: ProviderResult | None,
        provider_called: bool,
    ) -> None:
        if status not in TERMINAL_STATUSES:
            raise ValueError("completion status must be terminal")
        now = _utc(now)
        request_json = _canonical(request)
        request_sha = hashlib.sha256(request_json.encode()).hexdigest()
        response_json: str | None = None
        response_sha: str | None = None
        if result is not None:
            response_json = _canonical(result.response_json)
            response_sha = hashlib.sha256(response_json.encode()).hexdigest()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if result is not None:
                db.execute(
                    """INSERT OR IGNORE INTO baseline_provider_response_v1
                    (request_sha256,canonical_request_json,response_sha256,response_json,
                     service_version,model_version,generated_at_utc)
                    VALUES (?,?,?,?,?,?,?)""",
                    (request_sha, request_json, response_sha, response_json,
                     result.service_version, result.model_version, _time(now)),
                )
                existing = db.execute(
                    """SELECT canonical_request_json,response_sha256,service_version,model_version
                    FROM baseline_provider_response_v1 WHERE request_sha256=?""",
                    (request_sha,),
                ).fetchone()
                if existing != (request_json, response_sha, result.service_version, result.model_version):
                    raise ValueError("provider response cache identity conflict")
            cursor = db.execute(
                """UPDATE baseline_slot_v1 SET status=?,reason=?,timing_class=?,generated_at_utc=?,
                canonical_request_sha256=?,canonical_request_json=?,response_sha256=?,
                provider_called=?,lease_token=NULL,leased_until_utc=NULL
                WHERE slot_key=? AND status='processing' AND lease_token=?""",
                (status.value, reason[:_MAX_ERROR], timing_class.value, _time(now), request_sha,
                 request_json, response_sha, int(provider_called), claim["slot_key"], claim["lease_token"]),
            )
            if cursor.rowcount != 1:
                raise ValueError("stale lease or terminal slot replay")
            self._ledger(db, plan.plan_id, now, status.value, {"provider_called": provider_called})

    def retry(
        self,
        plan: BaselinePlan,
        claim: Mapping[str, Any],
        *,
        now: datetime,
        reason: str,
        request: Mapping[str, Any],
    ) -> None:
        now = _utc(now)
        attempt = int(claim["attempt_count"])
        terminal = attempt >= plan.max_attempts
        # Stable SHA-derived jitter prevents synchronized retries without random test behavior.
        jitter = int(str(claim["slot_key"])[:4], 16) % max(1, plan.retry_base_seconds)
        delay = min(plan.retry_cap_seconds, plan.retry_base_seconds * (2 ** (attempt - 1)) + jitter)
        request_json = _canonical(request)
        request_sha = hashlib.sha256(request_json.encode()).hexdigest()
        with self._connect() as db:
            cursor = db.execute(
                """UPDATE baseline_slot_v1 SET status=?,reason=?,generated_at_utc=?,
                timing_class=CASE WHEN ? THEN 'late' ELSE timing_class END,
                next_attempt_at_utc=?,canonical_request_sha256=?,canonical_request_json=?,
                provider_called=1,lease_token=NULL,leased_until_utc=NULL
                WHERE slot_key=? AND status='processing' AND lease_token=?""",
                ("failed" if terminal else "retry", reason[:_MAX_ERROR], _time(now) if terminal else None,
                 terminal, _time(now + timedelta(seconds=delay)), request_sha, request_json,
                 claim["slot_key"], claim["lease_token"]),
            )
            if cursor.rowcount != 1:
                raise ValueError("stale lease")
            self._ledger(db, plan.plan_id, now, "failed" if terminal else "retry", {"reason": reason[:_MAX_ERROR]})

    def calls_on_day(self, plan_id: UUID, day: date) -> int:
        prefix = day.isoformat()
        with self._connect() as db:
            row = db.execute(
                """SELECT COUNT(*) FROM baseline_activity_v1 WHERE plan_id=?
                AND occurred_at_utc LIKE ? AND action='provider_call'""",
                (str(plan_id), f"{prefix}%"),
            ).fetchone()
        return int(row[0])

    def record_provider_call(self, plan_id: UUID, now: datetime, slot_key: str) -> None:
        with self._connect() as db:
            self._ledger(db, plan_id, now, "provider_call", {"slot_key": slot_key})

    def storage_bytes(self) -> int:
        return sum(
            candidate.stat().st_size
            for candidate in (
                self.path,
                Path(f"{self.path}-wal"),
                Path(f"{self.path}-shm"),
            )
            if candidate.exists()
        )

    def diagnostics(self, *, generated_at_utc: datetime) -> dict[str, Any]:
        """Deterministic provider-free JSON summary from a query-only connection."""
        generated = _utc(generated_at_utc)
        uri = f"file:{self.path.resolve()}?mode=ro"
        with sqlite3.connect(uri, uri=True) as db:
            db.execute("PRAGMA query_only=ON")
            rows = db.execute(
                """SELECT plan_id,plan_version,model_version,service_version FROM baseline_plan_v1
                ORDER BY plan_id"""
            ).fetchall()
            groups = db.execute(
                """SELECT plan_id,substr(forecast_for_utc,1,10),band_m,
                substr(forecast_for_utc,12,2),region_id,status,COALESCE(timing_class,'pending'),COUNT(*)
                FROM baseline_slot_v1 GROUP BY 1,2,3,4,5,6,7 ORDER BY 1,2,3,4,5,6,7"""
            ).fetchall()
            oldest = db.execute(
                "SELECT MIN(forecast_for_utc),MAX(forecast_for_utc),SUM(provider_called) FROM baseline_slot_v1"
            ).fetchone()
            ledger = db.execute(
                "SELECT action,COUNT(*) FROM baseline_activity_v1 GROUP BY action ORDER BY action"
            ).fetchall()
        return {
            "schema_version": 1,
            "generated_at_utc": _time(generated),
            "training_eligible": False,
            "plans": [
                {"plan_id": row[0], "plan_version": row[1], "model_version": row[2], "service_version": row[3]}
                for row in rows
            ],
            "coverage": [
                {"plan_id": row[0], "day": row[1], "band_m": row[2], "hour_utc": int(row[3]),
                 "region_id": row[4], "status": row[5], "timing": row[6], "count": row[7]}
                for row in groups
            ],
            "retention": {"oldest_forecast_for_utc": oldest[0], "newest_forecast_for_utc": oldest[1]},
            "age_seconds": (
                None
                if oldest[1] is None
                else max(0, int((generated - datetime.fromisoformat(oldest[1])).total_seconds()))
            ),
            "budget": {"provider_calls": int(oldest[2] or 0), "activity": dict(ledger)},
            "scientific_semantics": {
                "voacap_reliability": "modeled-day circuit reliability, not QSO success probability",
                "voacap_snr": "dB-Hz; not FT8 decoder dB",
                "reference_power": "configured model input; not measured RF output",
            },
        }

    def _initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            existing_slot = db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='baseline_slot_v1'"
            ).fetchone()
            if existing_slot is not None:
                columns = {
                    str(row[1]) for row in db.execute("PRAGMA table_info(baseline_slot_v1)")
                }
                required_ssn_columns = {
                    "ssn_value_semantics",
                    "ssn_target_month",
                    "ssn_source_url",
                    "ssn_source_schema",
                    "ssn_revision_policy",
                    "ssn_source_record_id",
                    "ssn_source_released_at_utc",
                    "ssn_captured_at_utc",
                    "ssn_raw_sha256",
                    "ssn_snapshot_sha256",
                }
                if not required_ssn_columns <= columns:
                    raise ValueError(
                        "baseline database predates predicted-SSN provenance; "
                        "use a new reviewed C4 database"
                    )
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS baseline_schema_v1(version INTEGER PRIMARY KEY);
                INSERT OR IGNORE INTO baseline_schema_v1(version) VALUES (1);
                CREATE TABLE IF NOT EXISTS baseline_plan_v1(
                  plan_id TEXT PRIMARY KEY,parent_plan_id TEXT REFERENCES baseline_plan_v1(plan_id),
                  plan_version TEXT NOT NULL,model_version TEXT NOT NULL,service_version TEXT NOT NULL,
                  created_at_utc TEXT NOT NULL,canonical_sha256 TEXT NOT NULL,payload_json TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS baseline_provider_response_v1(
                  request_sha256 TEXT PRIMARY KEY,canonical_request_json TEXT NOT NULL,
                  response_sha256 TEXT NOT NULL,response_json TEXT NOT NULL,service_version TEXT NOT NULL,
                  model_version TEXT NOT NULL,generated_at_utc TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS baseline_slot_v1(
                  slot_key TEXT PRIMARY KEY,plan_id TEXT NOT NULL REFERENCES baseline_plan_v1(plan_id),
                  forecast_for_utc TEXT NOT NULL,scheduled_at_utc TEXT NOT NULL,region_id TEXT NOT NULL,
                  target_grid TEXT NOT NULL,target_grid_precision INTEGER NOT NULL,target_uncertainty TEXT NOT NULL,
                  band_m INTEGER NOT NULL,ssn REAL NOT NULL,ssn_source TEXT NOT NULL,
                  ssn_source_version TEXT NOT NULL,ssn_value_semantics TEXT NOT NULL,
                  ssn_target_month TEXT NOT NULL,ssn_source_url TEXT NOT NULL,
                  ssn_source_schema TEXT NOT NULL,ssn_revision_policy TEXT NOT NULL,
                  ssn_source_record_id TEXT NOT NULL,ssn_source_released_at_utc TEXT,
                  ssn_captured_at_utc TEXT NOT NULL,ssn_raw_sha256 TEXT NOT NULL,
                  ssn_snapshot_sha256 TEXT NOT NULL,
                  status TEXT NOT NULL,reason TEXT,timing_class TEXT,
                  attempt_count INTEGER NOT NULL,next_attempt_at_utc TEXT NOT NULL,lease_token TEXT,
                  leased_until_utc TEXT,generated_at_utc TEXT,canonical_request_sha256 TEXT,
                  canonical_request_json TEXT,response_sha256 TEXT,provider_called INTEGER NOT NULL DEFAULT 0,
                  UNIQUE(plan_id,forecast_for_utc,region_id,target_grid,band_m));
                CREATE INDEX IF NOT EXISTS baseline_slot_due_v1
                  ON baseline_slot_v1(plan_id,status,next_attempt_at_utc,forecast_for_utc);
                CREATE TABLE IF NOT EXISTS baseline_activity_v1(
                  activity_id INTEGER PRIMARY KEY AUTOINCREMENT,plan_id TEXT NOT NULL REFERENCES baseline_plan_v1(plan_id),
                  occurred_at_utc TEXT NOT NULL,action TEXT NOT NULL,detail_json TEXT NOT NULL);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=5)
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=5000")
        return db

    @staticmethod
    def _ledger(db: sqlite3.Connection, plan_id: UUID, now: datetime, action: str, detail: Mapping[str, Any]) -> None:
        db.execute(
            "INSERT INTO baseline_activity_v1(plan_id,occurred_at_utc,action,detail_json) VALUES (?,?,?,?)",
            (str(plan_id), _time(now), action, _canonical(detail)),
        )


class BaselineService:
    """One bounded cycle. The in-process lock enforces the advertised concurrency=1."""

    def __init__(self, repository: BaselineRepository, provider: BaselineProvider, clock: Clock) -> None:
        self._repository = repository
        self._provider = provider
        self._clock = clock
        self._lock = threading.Lock()

    def run_cycle(self, plan: BaselinePlan, config: BaselineConfig) -> dict[str, int | str]:
        if not config.enabled or not config.scheduler_enabled:
            return {"state": "disabled", "slots": 0, "provider_calls": 0}
        if not self._lock.acquire(blocking=False):
            return {"state": "busy", "slots": 0, "provider_calls": 0}
        slots = calls = 0
        try:
            while slots < plan.max_slots_per_cycle and calls < plan.max_provider_calls_per_cycle:
                now = _utc(self._clock.now())
                claim = self._repository.claim_one(plan, now)
                if claim is None:
                    break
                slots += 1
                if int(claim["band_m"]) not in SUPPORTED_BANDS:
                    self._complete_skip(plan, claim, now, "unsupported_band")
                    continue
                request = _request(plan, claim)
                request_sha = _sha(request)
                cached = self._repository.cached_response(request_sha)
                if cached is not None:
                    self._complete_ready(plan, claim, now, request, cached, False)
                    continue
                if not config.provider_enabled:
                    self._complete_skip(plan, claim, now, "provider_disabled", request)
                    continue
                if self._repository.calls_on_day(plan.plan_id, now.date()) >= plan.max_provider_calls_per_day:
                    self._complete_skip(plan, claim, now, "daily_call_budget_exhausted", request)
                    continue
                if self._repository.storage_bytes() >= plan.storage_limit_bytes:
                    self._complete_skip(plan, claim, now, "storage_budget_exhausted", request)
                    continue
                try:
                    self._repository.record_provider_call(plan.plan_id, now, str(claim["slot_key"]))
                    calls += 1
                    result = self._provider.predict(request, timeout_s=plan.provider_timeout_s)
                    if result.service_version != plan.service_version or result.model_version != plan.model_version:
                        raise ProviderFailure("provider_version_mismatch", retryable=False)
                    encoded = _canonical(result.response_json).encode()
                    if len(encoded) > plan.response_size_limit_bytes:
                        raise ProviderFailure("response_oversized", retryable=False)
                    _validate_response(result.response_json, int(claim["band_m"]), int(claim["forecast_for_utc"][11:13]))
                except ProviderFailure as error:
                    if error.retryable:
                        self._repository.retry(
                            plan, claim, now=now, reason=error.reason, request=request
                        )
                    else:
                        status = (
                            BaselineStatus.UNAVAILABLE
                            if error.reason == "requested_hour_band_missing"
                            else BaselineStatus.FAILED
                        )
                        self._repository.complete(
                            plan, claim, now=now, status=status, reason=error.reason,
                            timing_class=_timing(claim, now), request=request, result=None, provider_called=True,
                        )
                except Exception as error:  # noqa: BLE001 - injected adapters are failure-isolated
                    self._repository.retry(
                        plan,
                        claim,
                        now=now,
                        reason=f"provider_error:{type(error).__name__}",
                        request=request,
                    )
                else:
                    self._complete_ready(plan, claim, now, request, result, True)
            return {"state": "complete", "slots": slots, "provider_calls": calls}
        finally:
            self._lock.release()

    def _complete_ready(self, plan: BaselinePlan, claim: Mapping[str, Any], now: datetime,
                        request: Mapping[str, Any], result: ProviderResult, called: bool) -> None:
        self._repository.complete(
            plan, claim, now=now, status=BaselineStatus.READY,
            reason="provider_ready" if called else "deduplicated_cached_response",
            timing_class=_timing(claim, now), request=request, result=result, provider_called=called,
        )

    def _complete_skip(self, plan: BaselinePlan, claim: Mapping[str, Any], now: datetime,
                       reason: str, request: Mapping[str, Any] | None = None) -> None:
        self._repository.complete(
            plan, claim, now=now, status=BaselineStatus.SKIPPED, reason=reason,
            timing_class=_timing(claim, now), request=request or _request(plan, claim),
            result=None, provider_called=False,
        )


def _request(plan: BaselinePlan, claim: Mapping[str, Any]) -> dict[str, Any]:
    forecast = datetime.fromisoformat(str(claim["forecast_for_utc"]))
    # Hour is intentionally absent: the provider returns all monthly hourly cells.
    return {
        "contract": "voacap-summary-v1",
        "tx_grid": plan.origin_grid,
        "rx_grid": claim["target_grid"],
        "year": forecast.year,
        "month": forecast.month,
        "bands_m": [int(claim["band_m"])],
        "power_watts": REFERENCE_POWER_WATTS,
        "mode": "FT8",
        "timezone": "UTC",
        "ssn": claim["ssn"],
        "ssn_source": claim["ssn_source"],
        "ssn_source_version": claim["ssn_source_version"],
        "ssn_value_semantics": claim["ssn_value_semantics"],
        "ssn_target_month": claim["ssn_target_month"],
        "ssn_source_url": claim["ssn_source_url"],
        "ssn_source_schema": claim["ssn_source_schema"],
        "ssn_revision_policy": claim["ssn_revision_policy"],
        "ssn_source_record_id": claim["ssn_source_record_id"],
        "ssn_source_released_at_utc": claim["ssn_source_released_at_utc"],
        "ssn_captured_at_utc": claim["ssn_captured_at_utc"],
        "ssn_raw_sha256": claim["ssn_raw_sha256"],
        "ssn_snapshot_sha256": claim["ssn_snapshot_sha256"],
        "model_version": plan.model_version,
        "service_version": plan.service_version,
    }


def _validate_response(response: Mapping[str, Any], band: int, hour: int) -> None:
    cells = response.get("analysis", {}).get("best_band_by_hour") if isinstance(response.get("analysis"), dict) else None
    if not isinstance(cells, Sequence) or isinstance(cells, (str, bytes)):
        raise ProviderFailure("malformed_response", retryable=False)
    matches = [
        cell for cell in cells
        if isinstance(cell, dict) and cell.get("hour_utc") == hour and cell.get("band_m") == band
    ]
    if not matches:
        raise ProviderFailure("requested_hour_band_missing", retryable=False)
    if len(matches) != 1:
        raise ProviderFailure("duplicate_requested_hour_band", retryable=False)
    cell = matches[0]
    reliability = cell.get("reliability")
    snr = cell.get("snr_db")
    if (
        isinstance(reliability, bool)
        or not isinstance(reliability, (int, float))
        or not math.isfinite(float(reliability))
        or not 0 <= float(reliability) <= 1
        or isinstance(snr, bool)
        or not isinstance(snr, (int, float))
        or not math.isfinite(float(snr))
    ):
        raise ProviderFailure("malformed_requested_hour_band", retryable=False)


def _timing(claim: Mapping[str, Any], generated: datetime) -> TimingClass:
    forecast = datetime.fromisoformat(str(claim["forecast_for_utc"]))
    scheduled = datetime.fromisoformat(str(claim["scheduled_at_utc"]))
    if generated <= forecast:
        return TimingClass.PRE_CHOICE
    if scheduled > forecast:
        return TimingClass.BACKFILL
    return TimingClass.LATE


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC)


def _time(value: datetime) -> str:
    return _utc(value).isoformat().replace("+00:00", "Z")


def _canonical(value: Any) -> str:
    return dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()
