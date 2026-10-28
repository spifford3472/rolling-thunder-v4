"""Same response bytes can be freshly issued by multiple provider versions."""

import sqlite3
from datetime import timedelta
from uuid import uuid4

import pytest
from test_forge_voacap_scheduled_capture import NOW, FakeProvider, _environment, _plan

from rolling_thunder.forge_voacap_scheduled_capture import (
    ScheduledCaptureRepository,
    ScheduledCaptureService,
)


def test_identical_response_body_across_versions_keeps_per_request_provenance(tmp_path):
    path = tmp_path / "capture.sqlite"
    repo = ScheduledCaptureRepository(path)
    old = _plan()
    first = ScheduledCaptureService(repo, FakeProvider()).run_cycle(old, _environment(), NOW)
    assert first["request_status_counts"] == {"ready": 105}
    with sqlite3.connect(path) as db:
        before = db.execute(
            "SELECT * FROM baseline_capture_response_v1 ORDER BY response_sha256"
        ).fetchall()

    class NewVersion(FakeProvider):
        def predict(self, *args, **kwargs):
            return (
                super()
                .predict(*args, **kwargs)
                .model_copy(update={"service_version": "voacap-service-0.3.1"})
            )

    new = _plan(plan_id=uuid4(), service_version="voacap-service-0.3.1")
    second = ScheduledCaptureService(repo, NewVersion()).run_cycle(
        new, _environment(), NOW + timedelta(hours=6)
    )
    assert second["provider_calls_this_invocation"] == 105
    assert second["request_status_counts"] == {"ready": 105}
    with sqlite3.connect(path) as db:
        assert (
            db.execute(
                "SELECT * FROM baseline_capture_response_v1 ORDER BY response_sha256"
            ).fetchall()
            == before
        )
        assert db.execute(
            "SELECT DISTINCT provider_version FROM baseline_capture_request_v1 WHERE run_id=?",
            (second["run_id"],),
        ).fetchall() == [("voacap-service-0.3.1",)]
        assert db.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        assert not db.execute("PRAGMA foreign_key_check").fetchall()


@pytest.mark.parametrize("missing", ["snr_db", "reliability"])
def test_missing_snr_or_reliability_leaves_both_values_null_and_continues(tmp_path, missing):
    from copy import deepcopy

    path = tmp_path / (missing + ".sqlite")

    class PartialProvider(FakeProvider):
        def predict(self, *args, **kwargs):
            result = super().predict(*args, **kwargs)
            if len(self.calls) == 1:
                response = deepcopy(result.response_json)
                response["analysis"]["best_band_by_hour"][0][missing] = None
                return result.model_copy(update={"response_json": response})
            return result

    repo = ScheduledCaptureRepository(path)
    result = ScheduledCaptureService(repo, PartialProvider()).run_cycle(
        _plan(), _environment(), NOW
    )
    assert result["provider_calls_this_invocation"] == 105
    assert result["request_status_counts"] == {"ready": 104, "unavailable": 1}
    with sqlite3.connect(path) as db:
        assert db.execute(
            "SELECT reliability,snr_db FROM baseline_capture_cell_v1 WHERE status='unavailable'"
        ).fetchall() == [(None, None)]
        assert db.execute(
            "SELECT COUNT(*) FROM baseline_capture_cell_v1 WHERE status='ready'"
        ).fetchone() == (419,)


def test_same_hash_with_different_stored_bytes_is_still_rejected(tmp_path):
    path = tmp_path / "conflict.sqlite"
    repo = ScheduledCaptureRepository(path)
    ScheduledCaptureService(repo, FakeProvider()).run_cycle(_plan(), _environment(), NOW)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE baseline_capture_response_v1 SET response_json='{}'")
    plan = _plan(plan_id=uuid4())
    result = ScheduledCaptureService(repo, FakeProvider()).run_cycle(
        plan, _environment(), NOW + timedelta(hours=6)
    )
    assert result["request_status_counts"] == {"failed": 105}
