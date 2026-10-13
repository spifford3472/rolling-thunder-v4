from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import pytest

from rolling_thunder.forge_solar_ssn import SmoothedSsnSnapshot
from rolling_thunder.forge_voacap_noaa_refresh_main import _atomic_publish, build_environment
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
            {"region_id": "reviewed-region", "grid": "EN80", "uncertainty": "grid4 cell"},
        ],
        "model_version": "model-1",
        "service_version": "0.3.0",
        "forecast_target_month": "2026-10",
    })


def test_noaa_refresh_identity_and_paired_artifacts(monkeypatch: pytest.MonkeyPatch) -> None:
    import rolling_thunder.forge_voacap_noaa_refresh_main as module
    plan, _, _ = build_artifacts(_manifest(), _snapshot(), operational=True)
    class FakeAdapter:
        def __init__(self, **kwargs: object) -> None:
            pass
        def fetch(self, **kwargs: object):
            assert kwargs["target_month"] == "2026-10"
            return _snapshot()
    monkeypatch.setattr(module, "NoaaSwpcPredictedSsnAdapter", FakeAdapter)
    snapshot, env = build_environment(plan, now=datetime(2026, 10, 12, 12, tzinfo=UTC))
    assert json.loads(env)["snapshot_canonical_sha256"]
    assert json.loads(snapshot)["value"] == 121.4


def test_atomic_publish_replaces_content(tmp_path) -> None:
    p = tmp_path / "environment.json"
    p.write_text("old")
    _atomic_publish(p, "new")
    assert p.read_text() == "new"
