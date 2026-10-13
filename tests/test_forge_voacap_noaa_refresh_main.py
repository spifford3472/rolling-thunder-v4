from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from rolling_thunder.forge_voacap_noaa_refresh_main import _atomic_publish, build_environment
from rolling_thunder.forge_voacap_plan_main import build_artifacts
from tests.test_forge_voacap_plan_main import _manifest, _snapshot


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
