"""Dry-run-first audited C4 plan and environment artifact creation."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from rolling_thunder.domain import DomainModel
from rolling_thunder.forge_solar_ssn import SmoothedSsnSnapshot
from rolling_thunder.forge_voacap_baseline import (
    BaselinePlan,
    BaselineRepository,
    EnvironmentSnapshot,
    TargetGrid,
)

FIXED_ORIGIN_GRID6 = "EM79xm"


class InitialPlanManifest(DomainModel):
    """Reviewed inputs only; target geography is never invented by the tool."""

    contract: Literal["c4-initial-plan-manifest-v1"]
    plan_id: UUID
    parent_plan_id: UUID | None = None
    plan_version: str = Field(min_length=1, max_length=80)
    created_at_utc: datetime
    origin_uncertainty: str = Field(min_length=1, max_length=160)
    target_inventory_version: str = Field(min_length=1, max_length=80)
    targets: tuple[TargetGrid, ...] = Field(min_length=1, max_length=8)
    model_version: str = Field(min_length=1, max_length=120)
    service_version: str = Field(min_length=1, max_length=120)
    ssn_max_observation_age_days: int = Field(ge=1, le=730)

    @model_validator(mode="after")
    def regional_inventory_is_explicit(self) -> InitialPlanManifest:
        if any(target.precision not in {4, 6} for target in self.targets):
            raise ValueError("targets must be explicit grid4 or grid6 cells")
        return self


def build_artifacts(
    manifest: InitialPlanManifest, snapshot: SmoothedSsnSnapshot
) -> tuple[BaselinePlan, EnvironmentSnapshot, dict[str, object]]:
    snapshot.require_fresh(
        as_of_utc=manifest.created_at_utc,
        max_capture_age=timedelta(hours=24),
        max_observation_age=timedelta(days=manifest.ssn_max_observation_age_days),
    )
    plan = BaselinePlan(
        plan_id=manifest.plan_id,
        parent_plan_id=manifest.parent_plan_id,
        plan_version=manifest.plan_version,
        created_at_utc=manifest.created_at_utc,
        origin_grid=FIXED_ORIGIN_GRID6,
        origin_uncertainty=manifest.origin_uncertainty,
        target_inventory_version=manifest.target_inventory_version,
        targets=manifest.targets,
        model_version=manifest.model_version,
        service_version=manifest.service_version,
        ssn_source=snapshot.source_id,
        ssn_source_version=snapshot.source_version,
        max_provider_calls_per_cycle=1,
        max_provider_calls_per_day=1,
        max_slots_per_cycle=1,
        provider_timeout_s=10.0,
        max_attempts=1,
    )
    environment = EnvironmentSnapshot(
        ssn=snapshot.value,
        source=snapshot.source_id,
        source_version=snapshot.source_version,
        observed_at_utc=snapshot.observed_at_utc,
        captured_at_utc=snapshot.captured_at_utc,
    )
    audit: dict[str, object] = {
        "contract": "c4-plan-creation-audit-v1",
        "dry_run_default": True,
        "origin_grid6": FIXED_ORIGIN_GRID6,
        "target_count": len(plan.targets),
        "plan_id": str(plan.plan_id),
        "parent_plan_id": None if plan.parent_plan_id is None else str(plan.parent_plan_id),
        "plan_sha256": plan.canonical_sha256,
        "ssn_snapshot_sha256": snapshot.canonical_sha256,
        "ssn_value_semantics": snapshot.value_semantics.value,
        "ssn_max_observation_age_days": manifest.ssn_max_observation_age_days,
        "provider_limits": {
            "posts_per_cycle": plan.max_provider_calls_per_cycle,
            "posts_per_day": plan.max_provider_calls_per_day,
            "timeout_s": plan.provider_timeout_s,
            "attempts": plan.max_attempts,
        },
    }
    return plan, environment, audit


def main() -> None:
    parser = argparse.ArgumentParser(description="Build an audited C4 plan (dry-run by default)")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--ssn-snapshot", required=True, type=Path)
    parser.add_argument("--plan-output", type=Path)
    parser.add_argument("--environment-output", type=Path)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    manifest = InitialPlanManifest.model_validate_json(args.manifest.read_text())
    snapshot = SmoothedSsnSnapshot.model_validate_json(args.ssn_snapshot.read_text())
    plan, environment, audit = build_artifacts(manifest, snapshot)
    if not args.apply:
        print(json.dumps({**audit, "state": "dry_run", "database_changed": False}, sort_keys=True))
        return
    if args.plan_output is None or args.environment_output is None:
        parser.error("--apply requires --plan-output and --environment-output")
    _write_new(args.plan_output, plan.model_dump_json(indent=2) + "\n")
    _write_new(args.environment_output, environment.model_dump_json(indent=2) + "\n")
    database_changed = False
    if args.database is not None:
        BaselineRepository(args.database).add_plan(plan)
        database_changed = True
    print(json.dumps({**audit, "state": "applied", "database_changed": database_changed}, sort_keys=True))


def _write_new(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        handle.write(content)


if __name__ == "__main__":
    main()
