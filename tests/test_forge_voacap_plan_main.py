from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from rolling_thunder.forge_solar_ssn import SmoothedSsnSnapshot
from rolling_thunder.forge_voacap_plan_main import InitialPlanManifest, build_artifacts


def _snapshot() -> SmoothedSsnSnapshot:
    raw = b'[{"time-tag":"2026-10","predicted_ssn":121.4}]'
    return SmoothedSsnSnapshot(
        value=121.4,
        value_semantics="monthly_smoothed_predicted_sunspot_number",
        target_month="2026-10",
        source_id="noaa-swpc-predicted-solar-cycle",
        source_url="https://services.swpc.noaa.gov/json/solar-cycle/predicted-solar-cycle.json",
        source_version="published-schema-v1",
        source_schema="published-schema-v1",
        source_revision_policy="mutable current feed; append-only captures",
        source_record_id="2026-10:predicted_ssn",
        source_released_at_utc=None,
        captured_at_utc=datetime(2026, 10, 12, 11, tzinfo=UTC),
        raw_sha256=hashlib.sha256(raw).hexdigest(),
        raw_payload=raw,
        source_http_headers={"etag": '"fixture"'},
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
        "forecast_target_month": "2026-10",
    })


def test_plan_builder_fixes_origin_inventory_and_single_post_limits() -> None:
    plan, environment, audit = build_artifacts(_manifest(), _snapshot())
    assert plan.origin_grid == "EM79xm"
    assert plan.max_provider_calls_per_cycle == plan.max_provider_calls_per_day == 1
    assert plan.max_slots_per_cycle == plan.max_attempts == 1
    assert plan.provider_timeout_s == 10.0
    assert environment.source == "noaa-swpc-predicted-solar-cycle"
    assert environment.target_month == "2026-10"
    assert audit["ssn_value_semantics"] == "monthly_smoothed_predicted_sunspot_number"
    assert audit["ssn_release_time_known"] is False


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
