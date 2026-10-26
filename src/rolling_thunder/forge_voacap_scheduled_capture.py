"""Immutable four-times-daily VOACAP capture runs for the reviewed 15-site plan."""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import threading
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, Protocol, Self
from uuid import UUID, uuid5

from pydantic import Field, TypeAdapter, field_validator, model_validator

from rolling_thunder.domain import DomainModel
from rolling_thunder.forge_voacap_baseline import (
    EnvironmentSnapshot,
    ProviderFailure,
    ProviderResult,
    TargetGrid,
)
from rolling_thunder.value_types import MaidenheadGrid

CAPTURE_BANDS_M = (80, 40, 20, 17, 15, 12, 10)
CAPTURE_HOURS_UTC = (0, 6, 12, 18)
CAPTURE_MINUTE_UTC = 10
CAPTURE_REQUESTS_PER_RUN = 105
_RUN_NAMESPACE = UUID("f4bb76e2-940c-4e67-b084-7901ca33c23b")
_GRID = TypeAdapter(MaidenheadGrid)


class CapturePlan(DomainModel):
    """Versioned, immutable C6 contract; never reinterpret a legacy C4 plan."""

    schema_version: Literal[1] = 1
    plan_id: UUID
    parent_plan_id: UUID
    plan_version: str = Field(min_length=1, max_length=80)
    created_at_utc: datetime
    origin_grid: str = Field(min_length=6, max_length=6)
    origin_uncertainty: str = Field(min_length=1, max_length=160)
    target_inventory_version: str = Field(min_length=1, max_length=80)
    targets: tuple[TargetGrid, ...] = Field(min_length=15, max_length=15)
    bands_m: tuple[int, ...] = CAPTURE_BANDS_M
    hours_utc: tuple[int, ...] = CAPTURE_HOURS_UTC
    reference_power_watts: Literal[20] = 20
    model_version: str = Field(min_length=1, max_length=120)
    service_version: str = Field(min_length=1, max_length=120)
    ssn_source: str = Field(min_length=1, max_length=200)
    ssn_source_version: str = Field(min_length=1, max_length=120)
    ssn_value_semantics: Literal["monthly_smoothed_predicted_sunspot_number"]
    ssn_source_schema: str = Field(min_length=1, max_length=160)
    ssn_revision_policy: str = Field(min_length=1, max_length=300)
    provider_timeout_s: float = Field(default=10.0, ge=1.0, le=60.0)
    response_size_limit_bytes: int = Field(default=1_000_000, ge=1024, le=10_000_000)
    storage_limit_bytes: int = Field(default=250_000_000, ge=1_000_000, le=20_000_000_000)
    max_attempts: int = Field(default=3, ge=1, le=5)
    lease_seconds: int = Field(default=90, ge=30, le=3600)
    retry_delay_seconds: int = Field(default=60, ge=1, le=86400)

    @field_validator("created_at_utc")
    @classmethod
    def created_at_is_utc(cls, value: datetime) -> datetime:
        return _utc(value)

    @field_validator("origin_grid")
    @classmethod
    def origin_is_grid6(cls, value: str) -> str:
        normalized = _GRID.validate_python(value.upper())
        if len(normalized) != 6:
            raise ValueError("origin_grid must be a frozen grid6")
        return normalized

    @model_validator(mode="after")
    def exact_schedule(self) -> Self:
        if self.bands_m != CAPTURE_BANDS_M:
            raise ValueError("bands_m must equal the reviewed 80/40/20/17/15/12/10 m inventory")
        if self.hours_utc != CAPTURE_HOURS_UTC:
            raise ValueError("hours_utc must equal 00/06/12/18 UTC")
        identities = {target.region_id for target in self.targets}
        if len(identities) != 15:
            raise ValueError("target inventory must contain 15 unique region/grid identities")
        return self

    @property
    def canonical_sha256(self) -> str:
        return _sha(self.model_dump(mode="json"))


class CaptureProvider(Protocol):
    def predict(
        self,
        request: dict[str, Any],
        *,
        timeout_s: float,
        on_post_started: Callable[[], None],
    ) -> ProviderResult: ...


class ScheduledCaptureRepository:
    """Additive SQLite evidence store. It never updates legacy C4 rows."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS baseline_capture_plan_v1(
                  plan_id TEXT PRIMARY KEY,parent_plan_id TEXT NOT NULL,plan_version TEXT NOT NULL,
                  plan_sha256 TEXT NOT NULL,payload_json TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS baseline_capture_run_v1(
                  run_id TEXT PRIMARY KEY,plan_id TEXT NOT NULL REFERENCES baseline_capture_plan_v1(plan_id),
                  scheduled_for_utc TEXT NOT NULL,captured_at_utc TEXT NOT NULL,forecast_day_utc TEXT NOT NULL,
                  environment_json TEXT NOT NULL,expected_requests INTEGER NOT NULL,
                  status TEXT NOT NULL,created_at_utc TEXT NOT NULL,updated_at_utc TEXT NOT NULL,
                  UNIQUE(plan_id,scheduled_for_utc));
                CREATE TABLE IF NOT EXISTS baseline_capture_response_v1(
                  response_sha256 TEXT PRIMARY KEY,response_json TEXT NOT NULL,
                  service_version TEXT NOT NULL,model_version TEXT NOT NULL,stored_at_utc TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS baseline_capture_request_v1(
                  request_id TEXT PRIMARY KEY,run_id TEXT NOT NULL REFERENCES baseline_capture_run_v1(run_id),
                  region_id TEXT NOT NULL,target_grid TEXT NOT NULL,band_m INTEGER NOT NULL,
                  request_json TEXT NOT NULL,request_sha256 TEXT NOT NULL,status TEXT NOT NULL,
                  attempts INTEGER NOT NULL DEFAULT 0,next_attempt_at_utc TEXT NOT NULL,
                  lease_token TEXT,leased_until_utc TEXT,provider_called INTEGER NOT NULL DEFAULT 0,
                  provider_version TEXT,model_version TEXT,response_json TEXT,response_sha256 TEXT
                    REFERENCES baseline_capture_response_v1(response_sha256),
                  generated_at_utc TEXT,reason TEXT,
                  UNIQUE(run_id,region_id,target_grid,band_m));
                CREATE INDEX IF NOT EXISTS baseline_capture_request_due_v1
                  ON baseline_capture_request_v1(run_id,status,next_attempt_at_utc,region_id,band_m);
                CREATE TABLE IF NOT EXISTS baseline_capture_cell_v1(
                  request_id TEXT NOT NULL REFERENCES baseline_capture_request_v1(request_id),
                  hour_utc INTEGER NOT NULL,status TEXT NOT NULL,reliability REAL,snr_db REAL,
                  reason TEXT,PRIMARY KEY(request_id,hour_utc));
                CREATE TABLE IF NOT EXISTS baseline_capture_activity_v1(
                  activity_id INTEGER PRIMARY KEY AUTOINCREMENT,run_id TEXT NOT NULL
                    REFERENCES baseline_capture_run_v1(run_id),occurred_at_utc TEXT NOT NULL,
                  action TEXT NOT NULL,request_id TEXT,detail_json TEXT NOT NULL);
                """
            )

    def prepare_run(
        self, plan: CapturePlan, environment: EnvironmentSnapshot, scheduled_for: datetime,
        *, captured_at_utc: datetime,
    ) -> tuple[str, datetime, bool]:
        scheduled = _utc(scheduled_for)
        if scheduled.minute != CAPTURE_MINUTE_UTC or scheduled.second or scheduled.microsecond:
            raise ValueError("scheduled_for_utc must be a :10 UTC capture boundary")
        if scheduled.hour not in CAPTURE_HOURS_UTC:
            raise ValueError("scheduled_for_utc is outside the four daily UTC capture hours")
        _validate_environment(plan, environment, scheduled.date(), _utc(captured_at_utc))
        run_id = str(uuid5(_RUN_NAMESPACE, f"{plan.canonical_sha256}:{_time(scheduled)}"))
        plan_json = plan.model_dump_json()
        env_json = environment.model_dump_json()
        created = False
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute(
                "SELECT plan_sha256 FROM baseline_capture_plan_v1 WHERE plan_id=?",
                (str(plan.plan_id),),
            ).fetchone()
            if prior is None:
                db.execute(
                    "INSERT INTO baseline_capture_plan_v1 VALUES (?,?,?,?,?)",
                    (str(plan.plan_id),str(plan.parent_plan_id),plan.plan_version,
                     plan.canonical_sha256,plan_json),
                )
            elif prior[0] != plan.canonical_sha256:
                raise ValueError("capture plan UUID replay changed immutable content")
            row = db.execute(
                "SELECT captured_at_utc,environment_json FROM baseline_capture_run_v1 WHERE run_id=?",
                (run_id,),
            ).fetchone()
            if row is not None:
                if row[1] != env_json:
                    raise ValueError("capture run replay changed immutable environment evidence")
                return run_id, datetime.fromisoformat(row[0]), False
            captured = _utc(captured_at_utc)
            db.execute(
                """INSERT INTO baseline_capture_run_v1
                (run_id,plan_id,scheduled_for_utc,captured_at_utc,forecast_day_utc,environment_json,
                 expected_requests,status,created_at_utc,updated_at_utc)
                VALUES (?,?,?,?,?,?,?,'pending',?,?)""",
                (run_id,str(plan.plan_id),_time(scheduled),_time(captured),scheduled.date().isoformat(),
                 env_json,CAPTURE_REQUESTS_PER_RUN,_time(captured),_time(captured)),
            )
            for target in plan.targets:
                for band in plan.bands_m:
                    request = _provider_request(plan, environment, scheduled.date(), target, band)
                    request_json = _canonical(request)
                    request_sha = _sha(request)
                    request_id = _sha({"run_id":run_id,"region":target.region_id,
                                       "grid":target.grid,"band_m":band})
                    db.execute(
                        """INSERT INTO baseline_capture_request_v1
                        (request_id,run_id,region_id,target_grid,band_m,request_json,request_sha256,
                         status,next_attempt_at_utc) VALUES (?,?,?,?,?,?,?,'pending',?)""",
                        (request_id,run_id,target.region_id,target.grid,band,request_json,
                         request_sha,_time(captured)),
                    )
            created = True
            self._activity(db,run_id,captured,"scheduled",None,{"expected_requests":CAPTURE_REQUESTS_PER_RUN})
            return run_id, captured, created

    def capture_response_bytes(self) -> int:
        with self._connect() as db:
            row = db.execute(
                "SELECT COALESCE(SUM(length(response_json)),0) FROM baseline_capture_response_v1"
            ).fetchone()
        return int(row[0])

    def skip_remaining_for_storage(self, run_id: str, now: datetime) -> int:
        moment = _utc(now)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute(
                "SELECT request_id FROM baseline_capture_request_v1 WHERE run_id=? "
                "AND status IN ('pending','retry')",
                (run_id,),
            ).fetchall()
            db.execute(
                """UPDATE baseline_capture_request_v1 SET status='skipped',reason='storage_budget_exhausted',
                generated_at_utc=?,lease_token=NULL,leased_until_utc=NULL
                WHERE run_id=? AND status IN ('pending','retry')""",
                (_time(moment), run_id),
            )
            if rows:
                self._activity(
                    db, run_id, moment, "storage_budget_exhausted", None,
                    {"skipped_requests": len(rows)},
                )
            return len(rows)

    def claim_one(self, run_id: str, now: datetime, plan: CapturePlan) -> dict[str, Any] | None:
        moment = _utc(now)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                """UPDATE baseline_capture_request_v1 SET status=CASE WHEN attempts>=? THEN 'failed' ELSE 'retry' END,
                lease_token=NULL,leased_until_utc=NULL,reason='expired_lease'
                WHERE run_id=? AND status='processing' AND leased_until_utc<=?""",
                (plan.max_attempts,run_id,_time(moment)),
            )
            row = db.execute(
                """SELECT request_id,request_json,region_id,target_grid,band_m,attempts
                FROM baseline_capture_request_v1 WHERE run_id=? AND status IN ('pending','retry')
                AND next_attempt_at_utc<=? AND attempts<?
                ORDER BY region_id,band_m LIMIT 1""",
                (run_id,_time(moment),plan.max_attempts),
            ).fetchone()
            if row is None:
                return None
            token = str(uuid5(_RUN_NAMESPACE,f"{row[0]}:{int(row[5])+1}:{_time(moment)}"))
            db.execute(
                """UPDATE baseline_capture_request_v1 SET status='processing',attempts=attempts+1,
                lease_token=?,leased_until_utc=? WHERE request_id=?""",
                (token,_time(moment+timedelta(seconds=plan.lease_seconds)),row[0]),
            )
            self._activity(db,run_id,moment,"provider_attempt_started",row[0],{"attempt":int(row[5])+1})
            return {"request_id":row[0],"request":json.loads(row[1]),"region_id":row[2],
                    "target_grid":row[3],"band_m":int(row[4]),"attempt":int(row[5])+1,
                    "lease_token":token}

    def mark_provider_post_started(
        self, run_id: str, claim: Mapping[str, Any], now: datetime
    ) -> None:
        """Record the actual HTTP POST boundary after version preflight succeeds."""
        moment = _utc(now)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            cursor = db.execute(
                """UPDATE baseline_capture_request_v1 SET provider_called=1
                WHERE request_id=? AND status='processing' AND lease_token=?""",
                (claim["request_id"], claim["lease_token"]),
            )
            if cursor.rowcount != 1:
                raise ValueError("stale capture request lease before provider POST")
            self._activity(
                db, run_id, moment, "provider_post_started", str(claim["request_id"]),
                {"attempt": int(claim["attempt"])},
            )

    def complete(
        self, run_id: str, claim: Mapping[str, Any], result: ProviderResult,
        now: datetime, plan: CapturePlan,
    ) -> None:
        moment = _utc(now)
        encoded = _canonical(result.response_json)
        if len(encoded.encode("utf-8")) > plan.response_size_limit_bytes:
            raise ProviderFailure("response_oversized",retryable=False)
        if result.service_version != plan.service_version or result.model_version != plan.model_version:
            raise ProviderFailure("provider_version_mismatch",retryable=False)
        band = int(claim["band_m"])
        analysis=result.response_json.get("analysis")
        cells=analysis.get("best_band_by_hour") if isinstance(analysis,dict) else None
        if not isinstance(cells,Sequence) or isinstance(cells,(str,bytes)):
            raise ProviderFailure("malformed_response",retryable=False)
        parsed: list[tuple[int,str,float|None,float|None,str|None]] = []
        for hour in plan.hours_utc:
            matches = [cell for cell in cells if isinstance(cell,dict)
                       and cell.get("hour_utc")==hour and cell.get("band_m")==band]
            if len(matches)!=1:
                parsed.append((hour,"unavailable",None,None,
                               "requested_hour_band_missing" if not matches else "duplicate_hour_band"))
                continue
            reliability,snr=matches[0].get("reliability"),matches[0].get("snr_db")
            if (isinstance(reliability,bool) or not isinstance(reliability,(int,float))
                or not math.isfinite(float(reliability)) or not 0<=float(reliability)<=1
                or isinstance(snr,bool) or not isinstance(snr,(int,float)) or not math.isfinite(float(snr))):
                parsed.append((hour,"unavailable",None,None,"malformed_hour_band"))
            else:
                parsed.append((hour,"ready",float(reliability),float(snr),None))
        request_id=str(claim["request_id"])
        response_sha=_sha(result.response_json)
        request_status="ready" if all(cell[1]=="ready" for cell in parsed) else "unavailable"
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                """INSERT OR IGNORE INTO baseline_capture_response_v1
                (response_sha256,response_json,service_version,model_version,stored_at_utc)
                VALUES (?,?,?,?,?)""",
                (response_sha,encoded,result.service_version,result.model_version,_time(moment)),
            )
            stored=db.execute(
                "SELECT response_json,service_version,model_version FROM baseline_capture_response_v1 "
                "WHERE response_sha256=?",(response_sha,),
            ).fetchone()
            if stored!=(encoded,result.service_version,result.model_version):
                raise ValueError("capture response hash identity conflict")
            cursor=db.execute(
                """UPDATE baseline_capture_request_v1 SET status=?,provider_version=?,model_version=?,
                response_json=?,response_sha256=?,generated_at_utc=?,reason=NULL,lease_token=NULL,
                leased_until_utc=NULL WHERE request_id=? AND status='processing' AND lease_token=?""",
                (request_status,result.service_version,result.model_version,None,response_sha,
                 _time(moment),request_id,claim["lease_token"]),
            )
            if cursor.rowcount!=1:
                raise ValueError("stale capture request lease")
            db.executemany(
                """INSERT INTO baseline_capture_cell_v1
                (request_id,hour_utc,status,reliability,snr_db,reason) VALUES (?,?,?,?,?,?)""",
                [(request_id,*cell) for cell in parsed],
            )
            self._activity(db,run_id,moment,"provider_result",request_id,
                           {"status":request_status,"response_sha256":_sha(result.response_json)})

    def fail(self, run_id: str, claim: Mapping[str, Any], error: str, now: datetime, plan: CapturePlan,
             *, retryable: bool) -> None:
        moment=_utc(now)
        attempt=int(claim["attempt"])
        retry=retryable and attempt<plan.max_attempts
        status="retry" if retry else "failed"
        next_at=moment+timedelta(seconds=plan.retry_delay_seconds) if retry else moment
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            cursor=db.execute(
                """UPDATE baseline_capture_request_v1 SET status=?,reason=?,next_attempt_at_utc=?,
                lease_token=NULL,leased_until_utc=NULL,generated_at_utc=?
                WHERE request_id=? AND status='processing' AND lease_token=?""",
                (status,error[:500],_time(next_at),_time(moment),claim["request_id"],claim["lease_token"]),
            )
            if cursor.rowcount!=1:
                raise ValueError("stale capture request lease")
            self._activity(db,run_id,moment,status,str(claim["request_id"]),{"reason":error[:500]})

    def finish_run(self, run_id: str, now: datetime) -> dict[str, Any]:
        moment = _utc(now)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute(
                "SELECT status,COUNT(*) FROM baseline_capture_request_v1 WHERE run_id=? GROUP BY status",
                (run_id,),
            ).fetchall()
            counts = {str(status): int(count) for status, count in rows}
            cells = db.execute(
                """SELECT status,COUNT(*) FROM baseline_capture_cell_v1 WHERE request_id IN
                (SELECT request_id FROM baseline_capture_request_v1 WHERE run_id=?) GROUP BY status""",
                (run_id,),
            ).fetchall()
            cell_counts = {str(status): int(count) for status, count in cells}
            attempts = int(db.execute(
                """SELECT COUNT(*) FROM baseline_capture_activity_v1
                WHERE run_id=? AND action='provider_attempt_started'""",
                (run_id,),
            ).fetchone()[0])
            expected = int(db.execute(
                "SELECT expected_requests FROM baseline_capture_run_v1 WHERE run_id=?",
                (run_id,),
            ).fetchone()[0])
            terminal = (
                counts.get("ready", 0) + counts.get("unavailable", 0)
                + counts.get("failed", 0) + counts.get("skipped", 0)
            )
            if counts.get("ready", 0) + counts.get("unavailable", 0) == expected:
                state = "complete" if counts.get("unavailable", 0) == 0 else "complete_with_unavailable"
            elif terminal == expected and counts.get("failed", 0) == expected:
                state = "failed"
            else:
                state = "incomplete"
            db.execute(
                "UPDATE baseline_capture_run_v1 SET status=?,updated_at_utc=? WHERE run_id=?",
                (state, _time(moment), run_id),
            )
            self._activity(
                db, run_id, moment, "cycle_finished", None,
                {"state": state, "provider_attempts": attempts},
            )
            successful_responses = int(db.execute(
                """SELECT COUNT(*) FROM baseline_capture_request_v1
                WHERE run_id=? AND response_sha256 IS NOT NULL""",
                (run_id,),
            ).fetchone()[0])
            distinct_responses = int(db.execute(
                """SELECT COUNT(DISTINCT response_sha256) FROM baseline_capture_request_v1
                WHERE run_id=? AND response_sha256 IS NOT NULL""",
                (run_id,),
            ).fetchone()[0])
        return {
            "run_id": run_id,
            "state": state,
            "expected_requests": expected,
            "provider_attempts": attempts,
            "provider_calls": int(db.execute(
                """SELECT COUNT(*) FROM baseline_capture_activity_v1
                WHERE run_id=? AND action='provider_post_started'""",
                (run_id,),
            ).fetchone()[0]),
            "request_status_counts": counts,
            "cell_status_counts": cell_counts,
            "cache_reuse": 0,
            "response_storage_deduplicated": successful_responses - distinct_responses,
            "read_only": False,
        }

    @staticmethod
    def health(path: Path, plan: CapturePlan, day: date) -> dict[str, Any]:
        expected_ids = {
            (target.region_id, target.grid, band)
            for target in plan.targets
            for band in plan.bands_m
        }
        expected_cells_per_run = CAPTURE_REQUESTS_PER_RUN * len(plan.hours_utc)
        base: dict[str, Any] = {
            "schema_version": 1,
            "day_utc": day.isoformat(),
            "plan_id": str(plan.plan_id),
            "plan_sha256": plan.canonical_sha256,
            "expected_runs": 4,
            "expected_provider_calls": 4 * CAPTURE_REQUESTS_PER_RUN,
            "expected_target_hour_cells": 4 * expected_cells_per_run,
            "read_only": True,
            "training_eligible": False,
        }
        if not path.is_file():
            return {
                **base,
                "observed_runs": 0,
                "actual_provider_attempts": 0,
                "actual_provider_calls": 0,
                "coverage_state": "incomplete",
                "reason": "capture_database_missing",
                "runs": [],
            }
        uri = f"file:{path.resolve()}?mode=ro"
        with sqlite3.connect(uri, uri=True) as db:
            db.execute("PRAGMA query_only=ON")
            tables = {
                str(row[0])
                for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            required = {
                "baseline_capture_plan_v1",
                "baseline_capture_run_v1",
                "baseline_capture_request_v1",
                "baseline_capture_response_v1",
                "baseline_capture_cell_v1",
                "baseline_capture_activity_v1",
            }
            if not required <= tables:
                return {
                    **base,
                    "observed_runs": 0,
                    "actual_provider_attempts": 0,
                    "actual_provider_calls": 0,
                    "coverage_state": "incomplete",
                    "reason": "capture_schema_missing",
                    "runs": [],
                }
            plan_row = db.execute(
                "SELECT plan_sha256 FROM baseline_capture_plan_v1 WHERE plan_id=?",
                (str(plan.plan_id),),
            ).fetchone()
            if plan_row is None or plan_row[0] != plan.canonical_sha256:
                return {
                    **base,
                    "observed_runs": 0,
                    "actual_provider_attempts": 0,
                    "actual_provider_calls": 0,
                    "coverage_state": "failed",
                    "reason": "registered_plan_identity_missing_or_changed",
                    "runs": [],
                }
            runs = db.execute(
                """SELECT run_id,scheduled_for_utc,captured_at_utc,status,expected_requests
                FROM baseline_capture_run_v1 WHERE plan_id=? AND forecast_day_utc=?
                ORDER BY scheduled_for_utc""",
                (str(plan.plan_id), day.isoformat()),
            ).fetchall()
            run_reports: list[dict[str, Any]] = []
            expected_schedules = {
                _time(datetime(day.year, day.month, day.day, hour, CAPTURE_MINUTE_UTC, tzinfo=UTC))
                for hour in CAPTURE_HOURS_UTC
            }
            for run_id, scheduled, captured, status, expected_requests in runs:
                requests = db.execute(
                    """SELECT request_id,region_id,target_grid,band_m,status,provider_version,model_version
                    FROM baseline_capture_request_v1 WHERE run_id=? ORDER BY region_id,band_m""",
                    (run_id,),
                ).fetchall()
                observed_ids = {(row[1], row[2], int(row[3])) for row in requests}
                status_counts: dict[str, int] = {}
                for row in requests:
                    status_counts[row[4]] = status_counts.get(row[4], 0) + 1
                cell_rows = db.execute(
                    """SELECT c.request_id,c.hour_utc,c.status FROM baseline_capture_cell_v1 c
                    JOIN baseline_capture_request_v1 q USING(request_id)
                    WHERE q.run_id=? ORDER BY c.request_id,c.hour_utc""",
                    (run_id,),
                ).fetchall()
                cell_counts: dict[str, int] = {}
                for row in cell_rows:
                    cell_counts[row[2]] = cell_counts.get(row[2], 0) + 1
                expected_cell_ids = {
                    (str(request[0]), hour)
                    for request in requests
                    for hour in plan.hours_utc
                }
                observed_cell_ids = {(str(row[0]), int(row[1])) for row in cell_rows}
                missing_cell_ids = expected_cell_ids - observed_cell_ids
                unexpected_cell_ids = observed_cell_ids - expected_cell_ids
                attempts = int(db.execute(
                    """SELECT COUNT(*) FROM baseline_capture_activity_v1
                    WHERE run_id=? AND action='provider_attempt_started'""",
                    (run_id,),
                ).fetchone()[0])
                versions = sorted({str(row[5]) for row in requests if row[5] is not None})
                models = sorted({str(row[6]) for row in requests if row[6] is not None})
                missing_ids = expected_ids - observed_ids
                unexpected_ids = observed_ids - expected_ids
                observed_requests = len(requests)
                complete = (
                    status == "complete"
                    and int(expected_requests) == CAPTURE_REQUESTS_PER_RUN
                    and observed_requests == CAPTURE_REQUESTS_PER_RUN
                    and not missing_ids
                    and not unexpected_ids
                    and len(cell_rows) == expected_cells_per_run
                    and not missing_cell_ids
                    and not unexpected_cell_ids
                    and cell_counts.get("ready", 0) == expected_cells_per_run
                    and str(scheduled) in expected_schedules
                )
                response_count = int(db.execute(
                    """SELECT COUNT(*) FROM baseline_capture_request_v1
                    WHERE run_id=? AND response_sha256 IS NOT NULL""",
                    (run_id,),
                ).fetchone()[0])
                distinct_response_count = int(db.execute(
                    """SELECT COUNT(DISTINCT response_sha256) FROM baseline_capture_request_v1
                    WHERE run_id=? AND response_sha256 IS NOT NULL""",
                    (run_id,),
                ).fetchone()[0])
                run_reports.append(
                    {
                        "run_id": run_id,
                        "scheduled_for_utc": scheduled,
                        "captured_at_utc": captured,
                        "status": status,
                        "expected_requests": CAPTURE_REQUESTS_PER_RUN,
                        "observed_requests": observed_requests,
                        "missing_requests": len(missing_ids),
                        "unexpected_requests": len(unexpected_ids),
                        "request_identity_sha256": _sha(sorted(observed_ids)),
                        "missing_request_identity_sha256": _sha(sorted(missing_ids)),
                        "expected_target_hour_cells": expected_cells_per_run,
                        "observed_target_hour_cells": len(cell_rows),
                        "missing_target_hour_cells": len(missing_cell_ids),
                        "unexpected_target_hour_cells": len(unexpected_cell_ids),
                        "target_hour_identity_sha256": _sha(sorted(observed_cell_ids)),
                        "provider_attempts": attempts,
                        "provider_calls": int(db.execute(
                            """SELECT COUNT(*) FROM baseline_capture_activity_v1
                            WHERE run_id=? AND action='provider_post_started'""",
                            (run_id,),
                        ).fetchone()[0]),
                        "request_status_counts": status_counts,
                        "target_cell_status_counts": cell_counts,
                        "provider_versions": versions,
                        "model_versions": models,
                        "response_storage_deduplicated": response_count - distinct_response_count,
                        "complete": complete,
                    }
                )
        complete_runs = sum(bool(run["complete"]) for run in run_reports)
        observed_schedules = {str(run["scheduled_for_utc"]) for run in run_reports}
        missing_schedules = expected_schedules - observed_schedules
        return {
            **base,
            "observed_runs": len(run_reports),
            "missing_scheduled_boundaries": sorted(missing_schedules),
            "actual_provider_attempts": sum(run["provider_attempts"] for run in run_reports),
            "actual_provider_calls": sum(run["provider_calls"] for run in run_reports),
            "coverage_state": "complete" if complete_runs == 4 and len(run_reports) == 4 and not missing_schedules else "incomplete",
            "runs": run_reports,
        }

    def settle_prior_runs(
        self, plan_id: UUID, current_scheduled_for: datetime, now: datetime, plan: CapturePlan
    ) -> list[str]:
        """Miss unattempted old work; return same-day due retries only."""
        scheduled = _utc(current_scheduled_for)
        moment = _utc(now)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                """UPDATE baseline_capture_request_v1 SET status='missed',reason='utc_day_ended',
                generated_at_utc=?,lease_token=NULL,leased_until_utc=NULL
                WHERE run_id IN (SELECT run_id FROM baseline_capture_run_v1
                  WHERE plan_id=? AND forecast_day_utc<?)
                  AND status IN ('pending','retry')""",
                (_time(moment),str(plan_id),scheduled.date().isoformat()),
            )
            db.execute(
                """UPDATE baseline_capture_request_v1 SET status='missed',reason='utc_day_ended',
                generated_at_utc=?,lease_token=NULL,leased_until_utc=NULL
                WHERE run_id IN (SELECT run_id FROM baseline_capture_run_v1
                  WHERE plan_id=? AND forecast_day_utc<?)
                  AND status='processing' AND leased_until_utc<=?""",
                (_time(moment),str(plan_id),scheduled.date().isoformat(),_time(moment)),
            )
            db.execute(
                """UPDATE baseline_capture_request_v1 SET status='missed',reason='capture_window_elapsed',
                generated_at_utc=? WHERE run_id IN (SELECT run_id FROM baseline_capture_run_v1
                  WHERE plan_id=? AND forecast_day_utc=? AND scheduled_for_utc<?)
                  AND status='pending' AND attempts=0""",
                (_time(moment),str(plan_id),scheduled.date().isoformat(),_time(scheduled)),
            )
            db.execute(
                """UPDATE baseline_capture_request_v1 SET status=CASE WHEN attempts>=? THEN 'failed' ELSE 'retry' END,
                reason='expired_lease',lease_token=NULL,leased_until_utc=NULL
                WHERE run_id IN (SELECT run_id FROM baseline_capture_run_v1
                  WHERE plan_id=? AND forecast_day_utc=? AND scheduled_for_utc<?)
                  AND status='processing' AND leased_until_utc<=?""",
                (plan.max_attempts,str(plan_id),scheduled.date().isoformat(),_time(scheduled),_time(moment)),
            )
            run_ids = [
                str(row[0])
                for row in db.execute(
                    """SELECT DISTINCT q.run_id FROM baseline_capture_request_v1 q
                    JOIN baseline_capture_run_v1 r USING(run_id)
                    WHERE r.plan_id=? AND r.forecast_day_utc=? AND r.scheduled_for_utc<?
                    AND q.status='retry' AND q.next_attempt_at_utc<=?
                    ORDER BY r.scheduled_for_utc""",
                    (str(plan_id),scheduled.date().isoformat(),_time(scheduled),_time(moment)),
                ).fetchall()
            ]
            return run_ids

    def _connect(self)->sqlite3.Connection:
        db=sqlite3.connect(self.path,timeout=5)
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=5000")
        return db

    @staticmethod
    def _activity(db:sqlite3.Connection,run_id:str,now:datetime,action:str,
                  request_id:str|None,detail:Mapping[str,Any])->None:
        db.execute("""INSERT INTO baseline_capture_activity_v1
                    (run_id,occurred_at_utc,action,request_id,detail_json) VALUES (?,?,?,?,?)""",
                   (run_id,_time(now),action,request_id,_canonical(detail)))


class ScheduledCaptureService:
    """Run only the explicit scheduled boundary; never consult the monthly cache."""

    def __init__(self,repository:ScheduledCaptureRepository,provider:CaptureProvider)->None:
        self._repository=repository
        self._provider=provider
        self._lock=threading.Lock()

    def run_cycle(self, plan: CapturePlan, environment: EnvironmentSnapshot, now: datetime) -> dict[str, Any]:
        moment = _utc(now)
        scheduled = _scheduled_boundary(moment)
        if scheduled is None or moment - scheduled > timedelta(minutes=30):
            return {
                "state": "outside_capture_window",
                "provider_calls": 0,
                "expected_requests": CAPTURE_REQUESTS_PER_RUN,
                "cache_reuse": 0,
            }
        if not self._lock.acquire(blocking=False):
            return {
                "state": "busy",
                "provider_calls": 0,
                "expected_requests": CAPTURE_REQUESTS_PER_RUN,
            }
        try:
            run_id, captured, _ = self._repository.prepare_run(
                plan, environment, scheduled, captured_at_utc=moment
            )
            prior_run_ids = self._repository.settle_prior_runs(
                plan.plan_id, scheduled, moment, plan
            )
            current = self._process_run(run_id, plan, moment)
            prior_results = [
                self._process_run(prior_run_id, plan, moment)
                for prior_run_id in prior_run_ids
            ]
            prior_attempts = sum(
                int(item["provider_attempts_this_invocation"]) for item in prior_results
            )
            prior_provider_calls = sum(
                int(item["provider_calls_this_invocation"]) for item in prior_results
            )
            current["scheduled_for_utc"] = _time(scheduled)
            current["captured_at_utc"] = _time(captured)
            current["current_run_provider_calls"] = current["provider_calls_this_invocation"]
            current["prior_run_retry_attempts"] = prior_attempts
            current["prior_run_retry_provider_calls"] = prior_provider_calls
            current["provider_attempts_this_invocation"] += prior_attempts
            current["provider_calls_this_invocation"] += prior_provider_calls
            current["prior_run_retries"] = [
                {key: value for key, value in item.items()
                 if key in {"run_id", "state", "provider_attempts", "provider_calls",
                            "provider_attempts_this_invocation", "provider_calls_this_invocation"}}
                for item in prior_results
            ]
            current["expected_provider_calls_this_run"] = CAPTURE_REQUESTS_PER_RUN
            return current
        finally:
            self._lock.release()

    def _process_run(self, run_id: str, plan: CapturePlan, moment: datetime) -> dict[str, Any]:
        prediction_attempts = 0
        provider_posts = 0
        while True:
            if self._repository.capture_response_bytes() >= plan.storage_limit_bytes:
                self._repository.skip_remaining_for_storage(run_id, moment)
                break
            claim = self._repository.claim_one(run_id, moment, plan)
            if claim is None:
                break
            prediction_attempts += 1

            def mark_post_started(claimed: dict[str, Any] = claim) -> None:
                nonlocal provider_posts
                self._repository.mark_provider_post_started(run_id, claimed, moment)
                provider_posts += 1

            try:
                result = self._provider.predict(
                    claim["request"],
                    timeout_s=plan.provider_timeout_s,
                    on_post_started=mark_post_started,
                )
                self._repository.complete(run_id, claim, result, moment, plan)
            except ProviderFailure as error:
                self._repository.fail(
                    run_id, claim, error.reason, moment, plan, retryable=error.retryable
                )
            except Exception as error:  # noqa: BLE001 - isolate one provider failure per request
                self._repository.fail(
                    run_id, claim, f"provider_error:{type(error).__name__}",
                    moment, plan, retryable=True,
                )
        run_result = self._repository.finish_run(run_id, moment)
        run_result["provider_attempts_this_invocation"] = prediction_attempts
        run_result["provider_calls_this_invocation"] = provider_posts
        return run_result


def _scheduled_boundary(now:datetime)->datetime|None:
    hour=(now.hour//6)*6
    candidate=now.replace(hour=hour,minute=CAPTURE_MINUTE_UTC,second=0,microsecond=0)
    return candidate if candidate<=now and candidate.hour in CAPTURE_HOURS_UTC else None


def _provider_request(plan:CapturePlan,environment:EnvironmentSnapshot,day:date,
                      target:TargetGrid,band:int)->dict[str,Any]:
    return {"contract":"voacap-summary-v1","tx_grid":plan.origin_grid,"rx_grid":target.grid,
            "year":day.year,"month":day.month,"bands_m":[band],
            "power_watts":plan.reference_power_watts,"mode":"FT8","timezone":"UTC",
            "ssn":environment.ssn,"model_version":plan.model_version,
            "service_version":plan.service_version}


def _validate_environment(plan:CapturePlan,environment:EnvironmentSnapshot,day:date,
                          captured_at:datetime)->None:
    if environment.target_month!=f"{day.year:04d}-{day.month:02d}":
        raise ValueError("environment SSN target month does not match capture UTC day")
    identity=(environment.source,environment.source_version,environment.value_semantics,
              environment.source_schema,environment.source_revision_policy)
    expected=(plan.ssn_source,plan.ssn_source_version,plan.ssn_value_semantics,
              plan.ssn_source_schema,plan.ssn_revision_policy)
    if identity!=expected:
        raise ValueError("environment SSN identity does not match immutable capture plan")
    if environment.captured_at_utc>captured_at:
        raise ValueError("environment SSN capture is future-dated")
    if captured_at-environment.captured_at_utc>timedelta(hours=24):
        raise ValueError("environment SSN capture is older than 24 hours")


def day_end(day:date)->datetime:
    return datetime(day.year,day.month,day.day,tzinfo=UTC)+timedelta(days=1)


def _utc(value:datetime)->datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(UTC)


def _time(value:datetime)->str:
    return _utc(value).isoformat(timespec="microseconds").replace("+00:00","Z")


def _canonical(value:Any)->str:
    return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=True,allow_nan=False)


def _sha(value:Any)->str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()
