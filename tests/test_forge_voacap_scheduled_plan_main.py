"""Dry-run-first contract for reviewed C6 successor-plan artifacts."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from rolling_thunder.forge_solar_ssn import SmoothedSsnSnapshot
from rolling_thunder.forge_voacap_baseline import BaselinePlan
from rolling_thunder.forge_voacap_scheduled_plan_main import (
    ScheduledCaptureManifest,
    build_artifacts,
)


def _snapshot() -> SmoothedSsnSnapshot:
    raw = b'[{"time-tag":"2026-10","predicted_ssn":87.9}]'
    return SmoothedSsnSnapshot(
        value=87.9,
        value_semantics="monthly_smoothed_predicted_sunspot_number",
        target_month="2026-10",
        source_id="noaa-swpc-predicted-solar-cycle",
        source_url="https://example.invalid/predicted.json",
        source_version="published-schema-v1",
        source_schema="published-schema-v1",
        source_revision_policy="mutable current feed; append-only captures",
        source_record_id="2026-10:predicted_ssn",
        captured_at_utc=datetime(2026, 10, 22, 0, tzinfo=UTC),
        raw_sha256=hashlib.sha256(raw).hexdigest(),
        raw_payload=raw,
    )


def _manifest() -> ScheduledCaptureManifest:
    return ScheduledCaptureManifest.model_validate(
        {
            "contract": "c6-scheduled-capture-manifest-v1",
            "plan_id": "80000000-0000-4000-8000-000000000001",
            "parent_plan_id": "70000000-0000-4000-8000-000000000001",
            "plan_version": "c6-global15-capture-2026-10-v1",
            "created_at_utc": "2026-10-22T00:05:00Z",
            "origin_uncertainty": "fixed home grid6",
            "target_inventory_version": "global15-selected-2026-10-v2",
            "targets": [
                {"region_id": f"site-{index:02d}", "grid": f"EN{index:02d}",
                 "uncertainty": "reviewed representative grid4 cell"}
                for index in range(15)
            ],
            "model_version": "model-sha256-abc",
            "service_version": "0.3.0",
            "forecast_target_month": "2026-10",
        }
    )


def _parent_plan() -> BaselinePlan:
    manifest = _manifest()
    return BaselinePlan(
        plan_id=manifest.parent_plan_id,
        plan_version="legacy-parent-v1",
        created_at_utc=datetime(2026, 10, 21, 0, tzinfo=UTC),
        origin_grid="EM79xm",
        origin_uncertainty="fixed home grid6",
        target_inventory_version="global15-selected-2026-10-v1",
        targets=manifest.targets,
        model_version="old-model",
        service_version="0.3.0",
        ssn_source="noaa-swpc-predicted-solar-cycle",
        ssn_source_version="published-schema-v1",
        ssn_value_semantics="monthly_smoothed_predicted_sunspot_number",
        ssn_source_schema="published-schema-v1",
        ssn_revision_policy="mutable current feed; append-only captures",
    )


def test_builder_freezes_successor_inventory_and_exact_request_economics() -> None:
    plan, environment, audit = build_artifacts(_manifest(), _snapshot(), _parent_plan())
    assert plan.parent_plan_id == UUID("70000000-0000-4000-8000-000000000001")
    assert len(plan.targets) == 15
    assert plan.bands_m == (80, 40, 20, 17, 15, 12, 10)
    assert plan.provider_timeout_s == audit["provider_timeout_s"] == 60.0
    assert plan.max_attempts == audit["max_attempts_per_request"] == 1
    assert audit["posts_per_run"] == 105
    assert audit["posts_per_utc_day"] == 420
    assert audit["monthly_cache_suppresses_runs"] is False
    assert environment.target_month == "2026-10"


def test_builder_rejects_drift_from_parent_site_identities() -> None:
    parent = _parent_plan()
    manifest_data = _manifest().model_dump(mode="json")
    manifest_data["targets"][-1]["grid"] = "FN31"
    changed = ScheduledCaptureManifest.model_validate(manifest_data)
    with pytest.raises(ValueError, match="exactly match"):
        build_artifacts(changed, _snapshot(), parent)


def test_manifest_requires_fifteen_unique_site_ids() -> None:
    data = _manifest().model_dump(mode="json")
    data["targets"][-1] = data["targets"][0]
    with pytest.raises(ValueError, match="15 unique"):
        ScheduledCaptureManifest.model_validate(data)


def test_cli_defaults_to_read_only_dry_run(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    snapshot = tmp_path / "snapshot.json"
    parent_plan = tmp_path / "parent-plan.json"
    plan_output = tmp_path / "must-not-exist-plan.json"
    manifest.write_text(_manifest().model_dump_json())
    snapshot.write_text(_snapshot().model_dump_json())
    parent_plan.write_text(_parent_plan().model_dump_json())
    result = subprocess.run(
        [sys.executable, "-m", "rolling_thunder.forge_voacap_scheduled_plan_main",
         "--manifest", str(manifest), "--ssn-snapshot", str(snapshot),
         "--parent-plan", str(parent_plan), "--plan-output", str(plan_output)],
        check=True, capture_output=True, text=True,
    )
    output = json.loads(result.stdout)
    assert output["state"] == "dry_run"
    assert output["database_changed"] is False
    assert not plan_output.exists()
