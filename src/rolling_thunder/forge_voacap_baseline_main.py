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

    def predict(self, request: dict[str, Any] | Any, *, timeout_s: float) -> ProviderResult:
        """Exclude C4 metadata that the existing provider API does not accept."""
        body = {key: request[key] for key in (
            "tx_grid", "rx_grid", "year", "month", "bands_m",
            "power_watts", "mode", "timezone", "ssn",
        )}
        self.client._timeout_s = timeout_s
        try:
            version = self.client._json_request("GET", "/version", None)
            if str(version.get("version", "")) != self.service_version:
                raise ProviderFailure("provider_version_mismatch", retryable=False)
            if self._max_posts is not None and self._posts >= self._max_posts:
                raise ProviderFailure("pilot_post_limit_exhausted", retryable=False)
            self._posts += 1
            response = self.client._json_request("POST", "/api/v1/summary", body)
        except ProviderFailure:
            raise
        except Exception as exc:
            raise ProviderFailure("loopback_voacap_unavailable", retryable=True) from exc
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
    if environment.captured_at_utc > moment or environment.observed_at_utc > moment:
        raise ValueError("environment is future-dated")
    if moment - environment.captured_at_utc > timedelta(hours=24):
        raise ValueError("SSN snapshot older than 24 hours: cannot schedule")
    repo = BaselineRepository(config.database_path)
    slots = 0
    for offset in range(config.future_days_to_schedule):
        day = (moment + timedelta(days=offset + 1)).date()
        slots += repo.schedule_day(plan, day, environment, scheduled_at_utc=moment)
    provider = LocalVoacapProvider(
        config.provider_base_url, service_version=plan.service_version,
        model_version=plan.model_version, max_posts=max_provider_posts,
    )
    class FixedClock:
        def now(self) -> datetime:
            return moment
    outcome = BaselineService(repo, provider, FixedClock()).run_cycle(plan, gates)
    return {"state": outcome["state"], "provider_calls": outcome["provider_calls"],
            "scheduled_slots": slots, "processed_slots": outcome["slots"]}


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
    source_uri = f"file:{config.database_path.resolve()}?mode=ro"
    with sqlite3.connect(source_uri, uri=True) as source, sqlite3.connect(backup_path) as target:
        source.execute("PRAGMA query_only=ON")
        source.backup(target)
    with sqlite3.connect(backup_path) as backup:
        if backup.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise ValueError("controlled pilot backup failed integrity check")
        if backup.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("controlled pilot backup failed foreign-key check")
    outcome = run_once(config, now=moment, max_provider_posts=1)
    provider_calls = outcome["provider_calls"]
    if not isinstance(provider_calls, int) or provider_calls > 1:
        raise RuntimeError("controlled pilot exceeded one provider POST")
    return {
        **outcome,
        "pilot": "operator_gated_one_post",
        "backup_path": str(backup_path),
        "backup_sha256": hashlib.sha256(backup_path.read_bytes()).hexdigest(),
        "rollback": f"stop sampler; restore {backup_path} while no writer is running",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Forge C4 bounded one-shot sampler")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--check-config", action="store_true")
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


if __name__ == "__main__":
    main()
