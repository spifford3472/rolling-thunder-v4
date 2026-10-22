"""Forge-only, opt-in, bounded C4 prospective sampling cycle.

One-shot for systemd timers; no Pi, CAT, PTT, or QSO writes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field

from rolling_thunder.forge_propagation_collectors import VoacapSummaryClient
from rolling_thunder.forge_solar_ssn import SmoothedSsnSnapshot
from rolling_thunder.forge_voacap_baseline import (
    BaselineConfig,
    BaselinePlan,
    BaselineRepository,
    BaselineService,
    EnvironmentSnapshot,
    ProviderFailure,
    ProviderResult,
)


class SamplingRuntime(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    process_enabled: bool = False
    scheduler_enabled: bool = False
    provider_enabled: bool = False
    database_path: Path
    plan_path: Path
    environment_path: Path
    ssn_snapshot_path: Path
    provider_base_url: str = "http://127.0.0.1:8787"
    future_days_to_schedule: int = Field(default=1, ge=1, le=3)

    def gates(self) -> BaselineConfig:
        return BaselineConfig(
            enabled=self.process_enabled,
            scheduler_enabled=self.scheduler_enabled,
            provider_enabled=self.provider_enabled,
        )


class LocalVoacapProvider:
    """Real provider adapter with localhost-only endpoint and bounded timeout."""

    def __init__(
        self,
        url: str,
        *,
        service_version: str,
        model_version: str,
        max_posts: int | None = None,
    ) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.username or parsed.password:
            raise ValueError("C4 adapter permits only loopback HTTP")
        self.client = VoacapSummaryClient(url)
        self.service_version = service_version
        self.model_version = model_version
        self._max_posts = max_posts
        self._posts = 0
        self._version_verified = False

    @property
    def post_count(self) -> int:
        return self._posts

    def verify_version(self, *, timeout_s: float) -> None:
        """Validate the provider before any candidate slot is persisted."""
        if self._max_posts is not None and self._posts >= self._max_posts:
            raise ProviderFailure("pilot_post_limit_exhausted", retryable=False)
        self.client._timeout_s = timeout_s
        try:
            version = self.client._json_request("GET", "/version", None)
        except Exception as exc:
            raise ProviderFailure("loopback_voacap_version_unavailable", retryable=False) from exc
        if str(version.get("service", "")) != "voacap-service":
            raise ProviderFailure("provider_identity_mismatch", retryable=False)
        if str(version.get("version", "")) != self.service_version:
            raise ProviderFailure("provider_version_mismatch", retryable=False)
        if str(version.get("model_version", "")) != self.model_version:
            raise ProviderFailure("provider_model_identity_mismatch", retryable=False)
        self._version_verified = True

    def predict(self, request: dict[str, Any] | Any, *, timeout_s: float) -> ProviderResult:
        """Exclude C4 metadata that the existing provider API does not accept."""
        body = {key: request[key] for key in (
            "tx_grid", "rx_grid", "year", "month", "bands_m",
            "power_watts", "mode", "timezone", "ssn",
        )}
        self.client._timeout_s = timeout_s
        try:
            if self._max_posts is not None and self._posts >= self._max_posts:
                raise ProviderFailure("pilot_post_limit_exhausted", retryable=False)
            if not self._version_verified:
                self.verify_version(timeout_s=timeout_s)
            self._posts += 1
            response = self.client._json_request("POST", "/api/v1/summary", body)
        except ProviderFailure:
            raise
        except Exception as exc:
            raise ProviderFailure("loopback_voacap_unavailable", retryable=True) from exc
        if str(response.get("model_version", "")) != self.model_version:
            raise ProviderFailure("provider_response_model_mismatch", retryable=False)
        return ProviderResult(
            response_json=response, service_version=self.service_version,
            model_version=self.model_version,
        )


def run_once(
    config: SamplingRuntime,
    *,
    now: datetime | None = None,
    max_provider_posts: int | None = None,
) -> dict[str, object]:
    gates = config.gates()
    if not gates.enabled or not gates.scheduler_enabled or not gates.provider_enabled:
        return {"state": "disabled", "provider_calls": 0, "scheduled_slots": 0}
    moment = now or datetime.now(UTC)
    if moment.tzinfo is None:
        raise ValueError("clock must be timezone aware")
    # All plan days are UTC days.  A local-offset test/operator clock near
    # midnight must not accidentally schedule the current UTC day.
    moment = moment.astimezone(UTC)
    plan = BaselinePlan.model_validate_json(config.plan_path.read_text())
    environment = EnvironmentSnapshot.model_validate_json(config.environment_path.read_text())
    ssn_snapshot = SmoothedSsnSnapshot.model_validate_json(config.ssn_snapshot_path.read_text())
    if environment.captured_at_utc > moment:
        raise ValueError("environment is future-dated")
    if (
        environment.source_released_at_utc is not None
        and environment.source_released_at_utc > moment
    ):
        raise ValueError("environment release is future-dated")
    if moment - environment.captured_at_utc > timedelta(hours=24):
        raise ValueError("SSN snapshot older than 24 hours: cannot schedule")
    days = [
        (moment + timedelta(days=offset + 1)).date()
        for offset in range(config.future_days_to_schedule)
    ]
    target_months = {f"{day.year:04d}-{day.month:02d}" for day in days}
    if target_months != {environment.target_month}:
        raise ValueError("SSN forecast month does not cover every scheduled UTC day")
    ssn_snapshot.require_for_target(
        target_month=environment.target_month,
        as_of_utc=moment,
        max_capture_age=timedelta(hours=24),
    )
    if (
        environment.snapshot_canonical_sha256 != ssn_snapshot.canonical_sha256
        or environment.ssn != ssn_snapshot.value
        or environment.value_semantics != ssn_snapshot.value_semantics.value
        or environment.target_month != ssn_snapshot.target_month
        or environment.source != ssn_snapshot.source_id
        or environment.source_url != ssn_snapshot.source_url
        or environment.source_version != ssn_snapshot.source_version
        or environment.source_schema != ssn_snapshot.source_schema
        or environment.source_revision_policy != ssn_snapshot.source_revision_policy
        or environment.source_record_id != ssn_snapshot.source_record_id
        or environment.source_released_at_utc != ssn_snapshot.source_released_at_utc
        or environment.captured_at_utc != ssn_snapshot.captured_at_utc
        or environment.raw_sha256 != ssn_snapshot.raw_sha256
    ):
        raise ValueError("environment does not match the verified SSN snapshot artifact")
    if (
        environment.source != plan.ssn_source
        or environment.source_version != plan.ssn_source_version
        or environment.value_semantics != plan.ssn_value_semantics
        or environment.source_schema != plan.ssn_source_schema
        or environment.source_revision_policy != plan.ssn_revision_policy
    ):
        raise ValueError("environment SSN identity does not match immutable plan")
    provider = LocalVoacapProvider(
        config.provider_base_url, service_version=plan.service_version,
        model_version=plan.model_version, max_posts=max_provider_posts,
    )
    provider.verify_version(timeout_s=plan.provider_timeout_s)
    repo = BaselineRepository(config.database_path)
    slots = 0
    for day in days:
        slots += repo.schedule_day(plan, day, environment, scheduled_at_utc=moment)
    class FixedClock:
        def now(self) -> datetime:
            return moment
    outcome = BaselineService(repo, provider, FixedClock()).run_cycle(plan, gates)
    health = BaselineRepository.inspect_operational_health(
        config.database_path,
        plan,
        generated_at_utc=moment,
        forecast_days=days,
    )
    return {
        "state": outcome["state"],
        "provider_calls": outcome["provider_calls"],
        "scheduled_slots": slots,
        "processed_slots": outcome["slots"],
        "operational_health": health,
    }


def read_operational_health(
    config: SamplingRuntime,
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    """Read the next scheduled coverage window without provider or database writes."""
    moment = now or datetime.now(UTC)
    if moment.tzinfo is None:
        raise ValueError("clock must be timezone aware")
    moment = moment.astimezone(UTC)
    plan = BaselinePlan.model_validate_json(config.plan_path.read_text())
    days = [
        (moment + timedelta(days=offset + 1)).date()
        for offset in range(config.future_days_to_schedule)
    ]
    return {
        "state": "health",
        "operational_health": BaselineRepository.inspect_operational_health(
            config.database_path,
            plan,
            generated_at_utc=moment,
            forecast_days=days,
        ),
    }


def run_controlled_pilot(
    config: SamplingRuntime,
    *,
    approval_phrase: str,
    backup_directory: Path,
    now: datetime | None = None,
) -> dict[str, object]:
    """Run an operator-gated one-POST pilot after a consistent DB backup."""
    if approval_phrase != "AUTHORIZE_C4_ONE_POST_PILOT":
        raise ValueError("controlled pilot approval phrase mismatch")
    gates = config.gates()
    if not (gates.enabled and gates.scheduler_enabled and gates.provider_enabled):
        raise ValueError("controlled pilot requires all three runtime gates")
    plan = BaselinePlan.model_validate_json(config.plan_path.read_text())
    if (
        plan.max_provider_calls_per_cycle != 1
        or plan.max_provider_calls_per_day != 1
        or plan.max_slots_per_cycle != 1
        or plan.max_attempts != 1
        or plan.provider_timeout_s > 10.0
    ):
        raise ValueError("controlled pilot plan is not bounded to one POST/slot/attempt")
    if not config.database_path.is_file():
        raise ValueError("controlled pilot requires an existing C4 database to back up")
    backup_directory.mkdir(parents=True, exist_ok=True)
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    backup_path = backup_directory / (
        f"c4-baseline-before-pilot-{moment.strftime('%Y%m%dT%H%M%SZ')}.sqlite3"
    )
    if backup_path.exists():
        raise ValueError("controlled pilot backup already exists")
    if backup_path.resolve() == config.database_path.resolve():
        raise ValueError("controlled pilot backup must be separate from the source database")
    source_uri = f"file:{config.database_path.resolve()}?mode=ro"
    with sqlite3.connect(source_uri, uri=True) as source, sqlite3.connect(backup_path) as target:
        source.execute("PRAGMA query_only=ON")
        source.backup(target)
    with sqlite3.connect(backup_path) as backup:
        if backup.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise ValueError("controlled pilot backup failed integrity check")
        if backup.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("controlled pilot backup failed foreign-key check")
    backup_sha256 = hashlib.sha256(backup_path.read_bytes()).hexdigest()
    counts_before = _database_counts(backup_path)
    try:
        outcome = run_once(config, now=moment, max_provider_posts=1)
    except Exception as error:  # noqa: BLE001 - preserve a durable pilot failure audit
        attempted_posts = max(
            0,
            _provider_call_count(config.database_path) - _provider_call_count(backup_path),
        )
        outcome = {
            "state": "failed",
            "provider_calls": attempted_posts,
            "scheduled_slots": 0,
            "processed_slots": 0,
            "failure_type": type(error).__name__,
            "failure_reason": str(error)[:500],
        }
    provider_calls = outcome["provider_calls"]
    if not isinstance(provider_calls, int) or provider_calls > 1:
        raise RuntimeError("controlled pilot exceeded one provider POST")
    result = {
        **outcome,
        "pilot": "operator_gated_one_post",
        "backup_path": str(backup_path),
        "backup_sha256": backup_sha256,
        "backup_integrity_check": "ok",
        "backup_row_counts": counts_before,
        "rollback": f"stop sampler; restore {backup_path} while no writer is running",
    }
    audit_path = backup_path.with_suffix(".audit.json")
    with audit_path.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, sort_keys=True)
        handle.write("\n")
    result["audit_path"] = str(audit_path)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Forge C4 bounded one-shot sampler")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--check-config", action="store_true")
    parser.add_argument("--health", action="store_true")
    parser.add_argument("--controlled-pilot", action="store_true")
    parser.add_argument("--approval-phrase", default="")
    parser.add_argument("--backup-directory", type=Path)
    args = parser.parse_args()
    config = SamplingRuntime.model_validate_json(args.config.read_text())
    if args.check_config:
        print(json.dumps({"state": "validated", "process_enabled": config.process_enabled,
                          "scheduler_enabled": config.scheduler_enabled,
                          "provider_enabled": config.provider_enabled}, sort_keys=True))
        return
    if args.health:
        print(json.dumps(read_operational_health(config), sort_keys=True))
        return
    if args.controlled_pilot:
        if args.backup_directory is None:
            parser.error("--controlled-pilot requires --backup-directory")
        outcome = run_controlled_pilot(
            config,
            approval_phrase=args.approval_phrase,
            backup_directory=args.backup_directory,
        )
    else:
        outcome = run_once(config)
    print(json.dumps(outcome, sort_keys=True))
    if outcome.get("state") == "failed":
        raise SystemExit(1)


def _provider_call_count(path: Path) -> int:
    if not path.is_file():
        return 0
    with sqlite3.connect(path) as db:
        row = db.execute(
            "SELECT COUNT(*) FROM baseline_activity_v1 WHERE action='provider_call'"
        ).fetchone()
    return int(row[0])


def _database_counts(path: Path) -> dict[str, int]:
    with sqlite3.connect(path) as db:
        return {
            table: int(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in (
                "baseline_plan_v1",
                "baseline_slot_v1",
                "baseline_provider_response_v1",
                "baseline_activity_v1",
            )
        }


if __name__ == "__main__":
    main()
