"""Forge-only, opt-in, bounded C4 prospective sampling cycle.

One-shot for systemd timers; no Pi, CAT, PTT, or QSO writes.
"""
from __future__ import annotations

import argparse
import json
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

    def __init__(self, url: str, *, service_version: str, model_version: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.username or parsed.password:
            raise ValueError("C4 adapter permits only loopback HTTP")
        self.client = VoacapSummaryClient(url)
        self.service_version = service_version
        self.model_version = model_version

    def predict(self, request: dict[str, Any] | Any, *, timeout_s: float) -> ProviderResult:
        """Exclude C4 metadata that the existing provider API does not accept."""
        body = {key: request[key] for key in (
            "tx_grid", "rx_grid", "year", "month", "bands_m",
            "power_watts", "mode", "timezone", "ssn",
        )}
        self.client._timeout_s = timeout_s
        try:
            version = self.client._json_request("GET", "/version", None)
            response = self.client._json_request("POST", "/api/v1/summary", body)
        except Exception as exc:
            raise ProviderFailure("loopback_voacap_unavailable", retryable=True) from exc
        if str(version.get("version", "")) != self.service_version:
            raise ProviderFailure("provider_version_mismatch", retryable=False)
        return ProviderResult(
            response_json=response, service_version=self.service_version,
            model_version=self.model_version,
        )


def run_once(config: SamplingRuntime, *, now: datetime | None = None) -> dict[str, object]:
    gates = config.gates()
    if not gates.enabled or not gates.scheduler_enabled or not gates.provider_enabled:
        return {"state": "disabled", "provider_calls": 0, "scheduled_slots": 0}
    moment = now or datetime.now(UTC)
    if moment.tzinfo is None:
        raise ValueError("clock must be timezone aware")
    plan = BaselinePlan.model_validate_json(config.plan_path.read_text())
    environment = EnvironmentSnapshot.model_validate_json(config.environment_path.read_text())
    if environment.captured_at_utc > moment or environment.observed_at_utc > moment:
        raise ValueError("environment is future-dated")
    if moment - environment.captured_at_utc > timedelta(hours=24):
        raise ValueError("SSN snapshot older than 24 hours: cannot schedule")
    repo = BaselineRepository(config.database_path)
    slots = 0
    for offset in range(config.future_days_to_schedule):
        day = (moment + timedelta(days=offset)).date()
        slots += repo.schedule_day(plan, day, environment, scheduled_at_utc=moment)
    provider = LocalVoacapProvider(
        config.provider_base_url, service_version=plan.service_version,
        model_version=plan.model_version,
    )
    class FixedClock:
        def now(self) -> datetime:
            return moment
    outcome = BaselineService(repo, provider, FixedClock()).run_cycle(plan, gates)
    return {"state": outcome["state"], "provider_calls": outcome["provider_calls"],
            "scheduled_slots": slots, "processed_slots": outcome["slots"]}


def main() -> None:
    parser = argparse.ArgumentParser(description="Forge C4 bounded one-shot sampler")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--check-config", action="store_true")
    args = parser.parse_args()
    config = SamplingRuntime.model_validate_json(args.config.read_text())
    if args.check_config:
        print(json.dumps({"state": "validated", "process_enabled": config.process_enabled,
                          "scheduler_enabled": config.scheduler_enabled,
                          "provider_enabled": config.provider_enabled}, sort_keys=True))
        return
    print(json.dumps(run_once(config), sort_keys=True))


if __name__ == "__main__":
    main()
