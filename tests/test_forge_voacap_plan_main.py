from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from rolling_thunder.forge_solar_ssn import SmoothedSsnSnapshot
from rolling_thunder.forge_voacap_plan_main import InitialPlanManifest, build_artifacts


def _snapshot() -> SmoothedSsnSnapshot:
    return SmoothedSsnSnapshot(
        value=121.4,
        value_semantics="monthly_smoothed_observed_sunspot_number",
        source_id="reviewed-source",
        source_url="https://source.invalid/data",
        source_version="release-1",
        source_record_id="2026-03-final",
        observed_at_utc=datetime(2026, 3, 1, tzinfo=UTC),
        released_at_utc=datetime(2026, 10, 12, 10, tzinfo=UTC),
        captured_at_utc=datetime(2026, 10, 12, 11, tzinfo=UTC),
        raw_sha256="a" * 64,
    )


def _manifest() -> InitialPlanManifest:
    return InitialPlanManifest.model_validate({
        "contract": "c4-initial-plan-manifest-v1",
        "plan_id": "20000000-0000-4000-8000-000000000001",
        "plan_version": "regional-pilot-v1",
        "created_at_utc": "2026-10-12T12:00:00Z",
        "origin_uncertainty": "fixed six-character home-cell snapshot; not live vehicle position",
        "target_inventory_version": "owner-reviewed-regional-v1",
        "targets": [
            {"region_id": "reviewed-region", "grid": "EN80", "uncertainty": "grid4 cell"}
        ],
        "model_version": "model-1",
        "service_version": "0.3.0",
        "ssn_max_observation_age_days": 400,
    })


def test_plan_builder_fixes_origin_inventory_and_single_post_limits() -> None:
    plan, environment, audit = build_artifacts(_manifest(), _snapshot())
    assert plan.origin_grid == "EM79xm"
    assert plan.max_provider_calls_per_cycle == plan.max_provider_calls_per_day == 1
    assert plan.max_slots_per_cycle == plan.max_attempts == 1
    assert plan.provider_timeout_s == 10.0
    assert environment.source == "reviewed-source"
    assert audit["ssn_value_semantics"] == "monthly_smoothed_observed_sunspot_number"
    assert audit["ssn_max_observation_age_days"] == 400


def test_cli_defaults_dry_run_and_never_writes(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    snapshot = tmp_path / "snapshot.json"
    database = tmp_path / "must-not-exist.sqlite"
    plan_output = tmp_path / "must-not-exist-plan.json"
    manifest.write_text(_manifest().model_dump_json())
    snapshot.write_text(_snapshot().model_dump_json())
    result = subprocess.run(
        [sys.executable, "-m", "rolling_thunder.forge_voacap_plan_main",
         "--manifest", str(manifest), "--ssn-snapshot", str(snapshot),
         "--database", str(database), "--plan-output", str(plan_output)],
        check=True, capture_output=True, text=True,
    )
    assert json.loads(result.stdout)["state"] == "dry_run"
    assert not database.exists()
    assert not plan_output.exists()


def test_apply_creates_new_artifacts_and_registers_plan_explicitly(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    snapshot = tmp_path / "snapshot.json"
    database = tmp_path / "baseline.sqlite"
    plan_output = tmp_path / "plan.json"
    environment_output = tmp_path / "environment.json"
    manifest.write_text(_manifest().model_dump_json())
    snapshot.write_text(_snapshot().model_dump_json())
    subprocess.run(
        [sys.executable, "-m", "rolling_thunder.forge_voacap_plan_main",
         "--manifest", str(manifest), "--ssn-snapshot", str(snapshot),
         "--database", str(database), "--plan-output", str(plan_output),
         "--environment-output", str(environment_output), "--apply"],
        check=True, capture_output=True, text=True,
    )
    assert plan_output.exists() and environment_output.exists()
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT COUNT(*) FROM baseline_plan_v1").fetchone() == (1,)
