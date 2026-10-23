"""Dry-run-first builder for immutable C6 four-times-daily capture plans."""
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
from rolling_thunder.forge_voacap_baseline import BaselinePlan, EnvironmentSnapshot, TargetGrid
from rolling_thunder.forge_voacap_scheduled_capture import (
    CAPTURE_BANDS_M,
    CAPTURE_HOURS_UTC,
    CAPTURE_REQUESTS_PER_RUN,
    CapturePlan,
)


class ScheduledCaptureManifest(DomainModel):
    """Owner-reviewed exact successor-plan inputs; no geography is inferred."""

    contract: Literal["c6-scheduled-capture-manifest-v1"]
    plan_id: UUID
    parent_plan_id: UUID
    plan_version: str = Field(min_length=1, max_length=80)
    created_at_utc: datetime
    origin_uncertainty: str = Field(min_length=1, max_length=160)
    target_inventory_version: str = Field(min_length=1, max_length=80)
    targets: tuple[TargetGrid, ...] = Field(min_length=15, max_length=15)
    model_version: str = Field(min_length=1, max_length=120)
    service_version: str = Field(min_length=1, max_length=120)
    forecast_target_month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")

    @model_validator(mode="after")
    def exact_inventory(self) -> ScheduledCaptureManifest:
        if len({target.region_id for target in self.targets}) != 15:
            raise ValueError("manifest must contain 15 unique reviewed site IDs")
        return self


def build_artifacts(
    manifest: ScheduledCaptureManifest,
    snapshot: SmoothedSsnSnapshot,
    parent_plan: BaselinePlan,
) -> tuple[CapturePlan, EnvironmentSnapshot, dict[str, object]]:
    if parent_plan.plan_id != manifest.parent_plan_id:
        raise ValueError("manifest parent_plan_id does not match the supplied immutable plan")
    target_identities = {(target.region_id, target.grid) for target in manifest.targets}
    parent_identities = {(target.region_id, target.grid) for target in parent_plan.targets}
    if target_identities != parent_identities:
        raise ValueError("successor target identities must exactly match the parent plan")
    snapshot.require_for_target(
        target_month=manifest.forecast_target_month,
        as_of_utc=manifest.created_at_utc,
        max_capture_age=timedelta(hours=24),
    )
    plan = CapturePlan(
        plan_id=manifest.plan_id,
        parent_plan_id=manifest.parent_plan_id,
        plan_version=manifest.plan_version,
        created_at_utc=manifest.created_at_utc,
        origin_grid="EM79xm",
        origin_uncertainty=manifest.origin_uncertainty,
        target_inventory_version=manifest.target_inventory_version,
        targets=manifest.targets,
        bands_m=CAPTURE_BANDS_M,
        hours_utc=CAPTURE_HOURS_UTC,
        model_version=manifest.model_version,
        service_version=manifest.service_version,
        ssn_source=snapshot.source_id,
        ssn_source_version=snapshot.source_version,
        ssn_value_semantics="monthly_smoothed_predicted_sunspot_number",
        ssn_source_schema=snapshot.source_schema,
        ssn_revision_policy=snapshot.source_revision_policy,
    )
    environment = EnvironmentSnapshot(
        ssn=snapshot.value,
        value_semantics="monthly_smoothed_predicted_sunspot_number",
        target_month=snapshot.target_month,
        source=snapshot.source_id,
        source_url=snapshot.source_url,
        source_version=snapshot.source_version,
        source_schema=snapshot.source_schema,
        source_revision_policy=snapshot.source_revision_policy,
        source_record_id=snapshot.source_record_id,
        source_released_at_utc=snapshot.source_released_at_utc,
        captured_at_utc=snapshot.captured_at_utc,
        raw_sha256=snapshot.raw_sha256,
        snapshot_canonical_sha256=snapshot.canonical_sha256,
    )
    audit: dict[str, object] = {
        "contract": "c6-scheduled-capture-plan-audit-v1",
        "dry_run_default": True,
        "plan_id": str(plan.plan_id),
        "parent_plan_id": str(plan.parent_plan_id),
        "plan_sha256": plan.canonical_sha256,
        "target_inventory_version": plan.target_inventory_version,
        "target_count": len(plan.targets),
        "bands_m": list(plan.bands_m),
        "target_hours_utc": list(plan.hours_utc),
        "posts_per_run": CAPTURE_REQUESTS_PER_RUN,
        "runs_per_utc_day": len(plan.hours_utc),
        "posts_per_utc_day": CAPTURE_REQUESTS_PER_RUN * len(plan.hours_utc),
        "monthly_cache_suppresses_runs": False,
        "provider_timeout_s": plan.provider_timeout_s,
        "max_attempts_per_request": plan.max_attempts,
        "capture_response_storage_limit_bytes": plan.storage_limit_bytes,
        "ssn_snapshot_sha256": snapshot.canonical_sha256,
        "ssn_target_month": snapshot.target_month,
        "ssn_release_time_known": snapshot.source_released_at_utc is not None,
    }
    return plan, environment, audit


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a reviewed C6 scheduled-capture plan")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--ssn-snapshot", required=True, type=Path)
    parser.add_argument("--parent-plan", required=True, type=Path)
    parser.add_argument("--plan-output", type=Path)
    parser.add_argument("--environment-output", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    manifest = ScheduledCaptureManifest.model_validate_json(args.manifest.read_text())
    snapshot = SmoothedSsnSnapshot.model_validate_json(args.ssn_snapshot.read_text())
    parent_plan = BaselinePlan.model_validate_json(args.parent_plan.read_text())
    plan, environment, audit = build_artifacts(manifest, snapshot, parent_plan)
    if not args.apply:
        print(json.dumps({**audit, "state": "dry_run", "database_changed": False}, sort_keys=True))
        return
    if args.plan_output is None or args.environment_output is None:
        parser.error("--apply requires --plan-output and --environment-output")
    if args.plan_output.resolve() == args.environment_output.resolve():
        parser.error("plan and environment outputs must be different paths")
    if args.plan_output.exists() or args.environment_output.exists():
        parser.error("plan/environment outputs must be new files")
    _write_new(args.plan_output, plan.model_dump_json(indent=2) + "\n")
    _write_new(args.environment_output, environment.model_dump_json(indent=2) + "\n")
    print(json.dumps({**audit, "state": "applied", "database_changed": False}, sort_keys=True))


def _write_new(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        handle.write(content)


if __name__ == "__main__":
    main()
