"""Offline acceptance for independently persisted C6 scheduled captures."""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError

from rolling_thunder.forge_voacap_baseline import (
    EnvironmentSnapshot,
    ProviderFailure,
    ProviderResult,
    TargetGrid,
)
from rolling_thunder.forge_voacap_scheduled_capture import (
    CAPTURE_BANDS_M,
    CAPTURE_HOURS_UTC,
    CAPTURE_REQUESTS_PER_RUN,
    CapturePlan,
    ScheduledCaptureRepository,
    ScheduledCaptureService,
)

NOW = datetime(2026, 10, 22, 0, 10, tzinfo=UTC)
PLAN_ID = UUID("80000000-0000-4000-8000-000000000001")
PARENT_PLAN_ID = UUID("70000000-0000-4000-8000-000000000001")


class FakeProvider:
    def __init__(self, *, fail_first: bool = False) -> None:
        self.calls: list[dict[str, Any]] = []
        self.fail_first = fail_first

    def predict(self, request: dict[str, Any], *, timeout_s: float) -> ProviderResult:
        assert timeout_s == 10
        self.calls.append(dict(request))
        if self.fail_first:
            self.fail_first = False
            raise ProviderFailure("provider_timeout", retryable=True)
        band = request["bands_m"][0]
        return ProviderResult(
            service_version="voacap-service-0.3.0",
            model_version="model-sha256-abc",
            response_json={
                "analysis": {
                    "best_band_by_hour": [
                        {"hour_utc": hour, "band_m": band,
                         "reliability": 0.5, "snr_db": 9.0}
                        for hour in CAPTURE_HOURS_UTC
                    ]
                }
            },
        )


def _plan(**changes: Any) -> CapturePlan:
    targets = tuple(
        TargetGrid(
            region_id=f"site-{index:02d}",
            grid=f"EN{index:02d}",
            uncertainty="reviewed representative grid4 cell",
        )
        for index in range(15)
    )
    values: dict[str, Any] = {
        "plan_id": PLAN_ID,
        "parent_plan_id": PARENT_PLAN_ID,
        "plan_version": "c6-global15-capture-2026-10-v1",
        "created_at_utc": NOW,
        "origin_grid": "EM79xm",
        "origin_uncertainty": "fixed home grid6",
        "target_inventory_version": "global15-selected-2026-10-v2",
        "targets": targets,
        "bands_m": CAPTURE_BANDS_M,
        "hours_utc": CAPTURE_HOURS_UTC,
        "reference_power_watts": 20,
        "model_version": "model-sha256-abc",
        "service_version": "voacap-service-0.3.0",
        "ssn_source": "NOAA SWPC predicted solar cycle",
        "ssn_source_version": "2026-10-snapshot-1",
        "ssn_value_semantics": "monthly_smoothed_predicted_sunspot_number",
        "ssn_source_schema": "predicted-solar-cycle-v1",
        "ssn_revision_policy": "append-only capture revisions",
    }
    values.update(changes)
    return CapturePlan.model_validate(values)


def _environment(month: str = "2026-10", captured: datetime = NOW) -> EnvironmentSnapshot:
    return EnvironmentSnapshot(
        ssn=87.9,
        value_semantics="monthly_smoothed_predicted_sunspot_number",
        target_month=month,
        source="NOAA SWPC predicted solar cycle",
        source_url="https://example.invalid/predicted-solar-cycle.json",
        source_version="2026-10-snapshot-1",
        source_schema="predicted-solar-cycle-v1",
        source_revision_policy="append-only capture revisions",
        source_record_id=f"{month}:predicted_ssn",
        captured_at_utc=captured,
        raw_sha256="a" * 64,
        snapshot_canonical_sha256="b" * 64,
    )


def test_capture_plan_freezes_exact_inventory_and_rejects_drift() -> None:
    plan = _plan()
    assert len(plan.targets) == 15
    assert plan.bands_m == (80, 40, 20, 17, 15, 12, 10)
    assert len(plan.targets) * len(plan.bands_m) == CAPTURE_REQUESTS_PER_RUN == 105
    with pytest.raises(ValidationError, match="reviewed 80/40"):
        _plan(bands_m=(40, 30, 20, 17, 15, 12, 10))
    targets = list(plan.targets)
    targets[-1] = targets[0]
    with pytest.raises(ValidationError, match="15 unique"):
        _plan(targets=tuple(targets))


def test_four_utc_runs_each_call_105_and_keep_independent_capture_evidence(
    tmp_path: Path,
) -> None:
    path = tmp_path / "capture.sqlite"
    repo = ScheduledCaptureRepository(path)
    provider = FakeProvider()
    service = ScheduledCaptureService(repo, provider)
    plan = _plan()
    env = _environment()

    results = []
    for hour in CAPTURE_HOURS_UTC:
        when = NOW.replace(hour=hour)
        result = service.run_cycle(plan, env, when)
        assert result["state"] == "complete"
        assert result["provider_calls_this_invocation"] == 105
        assert result["expected_provider_calls_this_run"] == 105
        assert result["cache_reuse"] == 0
        assert result["response_storage_deduplicated"] == 98
        results.append(result)
        replay = service.run_cycle(plan, env, when + timedelta(minutes=1))
        assert replay["provider_calls_this_invocation"] == 0
    assert len(provider.calls) == 4 * 105
    assert len({result["run_id"] for result in results}) == 4
    assert all(set(request["bands_m"]) <= set(CAPTURE_BANDS_M) for request in provider.calls)
    assert {request["month"] for request in provider.calls} == {10}

    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert db.execute("SELECT COUNT(*) FROM baseline_capture_run_v1").fetchone() == (4,)
        assert db.execute("SELECT COUNT(*) FROM baseline_capture_request_v1").fetchone() == (420,)
        assert db.execute("SELECT COUNT(*) FROM baseline_capture_cell_v1").fetchone() == (1680,)
        assert db.execute(
            "SELECT COUNT(DISTINCT scheduled_for_utc) FROM baseline_capture_run_v1"
        ).fetchone() == (4,)
        assert db.execute(
            "SELECT COUNT(*) FROM baseline_capture_request_v1 WHERE provider_called=1"
        ).fetchone() == (420,)

    backup = tmp_path / "capture-backup.sqlite"
    with sqlite3.connect(path) as source, sqlite3.connect(backup) as destination:
        source.backup(destination)
    with sqlite3.connect(backup) as copied:
        assert copied.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert copied.execute("PRAGMA foreign_key_check").fetchall() == []
    health = repo.health(path, plan, date(2026, 10, 22))
    backup_health = repo.health(backup, plan, date(2026, 10, 22))
    assert backup_health == health
    assert health["coverage_state"] == "complete"
    assert health["observed_runs"] == 4
    assert health["actual_provider_attempts"] == 420
    assert health["expected_target_hour_cells"] == 1680
    assert health["read_only"] is True


def test_utc_boundary_and_month_rollover_are_distinct_runs(tmp_path: Path) -> None:
    path = tmp_path / "capture.sqlite"
    repo = ScheduledCaptureRepository(path)
    provider = FakeProvider()
    service = ScheduledCaptureService(repo, provider)
    plan = _plan()
    oct = datetime(2026, 10, 31, 18, 10, tzinfo=UTC)
    nov = datetime(2026, 11, 1, 0, 10, tzinfo=UTC)
    service.run_cycle(plan, _environment("2026-10", oct), oct)
    service.run_cycle(plan, _environment("2026-11", oct), nov)
    assert len(provider.calls) == 210
    assert {call["month"] for call in provider.calls[:105]} == {10}
    assert {call["month"] for call in provider.calls[105:]} == {11}
    with sqlite3.connect(path) as db:
        rows = db.execute(
            "SELECT scheduled_for_utc,forecast_day_utc FROM baseline_capture_run_v1 ORDER BY scheduled_for_utc"
        ).fetchall()
    assert rows == [
        ("2026-10-31T18:10:00.000000Z", "2026-10-31"),
        ("2026-11-01T00:10:00.000000Z", "2026-11-01"),
    ]


def test_retryable_provider_failure_is_visible_and_retries_only_failed_request(
    tmp_path: Path,
) -> None:
    repo = ScheduledCaptureRepository(tmp_path / "capture.sqlite")
    provider = FakeProvider(fail_first=True)
    service = ScheduledCaptureService(repo, provider)
    plan = _plan()
    first = service.run_cycle(plan, _environment(), NOW)
    assert first["state"] == "incomplete"
    assert first["provider_calls_this_invocation"] == 105
    assert first["request_status_counts"]["retry"] == 1
    retried = service.run_cycle(plan, _environment(), NOW + timedelta(minutes=1))
    assert retried["state"] == "complete"
    assert retried["provider_calls_this_invocation"] == 1
    assert retried["provider_attempts"] == 106
    assert len(provider.calls) == 106


def test_missing_target_hour_is_explicit_and_not_reused_as_success(tmp_path: Path) -> None:
    class MissingHourProvider(FakeProvider):
        def predict(self, request: dict[str, Any], *, timeout_s: float) -> ProviderResult:
            result = super().predict(request, timeout_s=timeout_s)
            if request["bands_m"] == [80]:
                result.response_json["analysis"]["best_band_by_hour"].pop()
            return result

    repo = ScheduledCaptureRepository(tmp_path / "capture.sqlite")
    result = ScheduledCaptureService(repo, MissingHourProvider()).run_cycle(
        _plan(), _environment(), NOW
    )
    assert result["state"] == "complete_with_unavailable"
    assert result["request_status_counts"]["unavailable"] == 15
    assert result["cell_status_counts"]["unavailable"] == 15
    assert result["cache_reuse"] == 0


def test_outside_window_does_not_catch_up_or_contact_provider(tmp_path: Path) -> None:
    provider = FakeProvider()
    result = ScheduledCaptureService(
        ScheduledCaptureRepository(tmp_path / "capture.sqlite"), provider
    ).run_cycle(_plan(), _environment(), NOW + timedelta(hours=1))
    assert result["state"] == "outside_capture_window"
    assert result["provider_calls"] == 0
    assert provider.calls == []


def test_missing_capture_database_health_is_read_only_and_incomplete(tmp_path: Path) -> None:
    path = tmp_path / "absent.sqlite"
    health = ScheduledCaptureRepository.health(path, _plan(), date(2026, 10, 22))
    assert health["coverage_state"] == "incomplete"
    assert health["expected_provider_calls"] == 420
    assert health["expected_target_hour_cells"] == 1680
    assert health["reason"] == "capture_database_missing"
    assert health["read_only"] is True
    assert not path.exists()


def test_legacy_database_without_capture_schema_health_stays_read_only(tmp_path: Path) -> None:
    path = tmp_path / "legacy.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE historical_marker(value TEXT)")
        db.execute("INSERT INTO historical_marker VALUES ('preserve')")
    before = path.read_bytes()
    health = ScheduledCaptureRepository.health(path, _plan(), date(2026, 10, 22))
    assert health["coverage_state"] == "incomplete"
    assert health["reason"] == "capture_schema_missing"
    assert path.read_bytes() == before


def test_response_storage_cap_skips_unsent_requests_with_reason(tmp_path: Path) -> None:
    class LargeProvider(FakeProvider):
        def predict(self, request: dict[str, Any], *, timeout_s: float) -> ProviderResult:
            result = super().predict(request, timeout_s=timeout_s)
            result.response_json["fixture_padding"] = "x" * 300_000
            return result

    repository = ScheduledCaptureRepository(tmp_path / "capture.sqlite")
    provider = LargeProvider()
    result = ScheduledCaptureService(repository, provider).run_cycle(
        _plan(storage_limit_bytes=1_000_000), _environment(), NOW
    )
    assert result["state"] == "incomplete"
    assert 0 < result["provider_calls_this_invocation"] < CAPTURE_REQUESTS_PER_RUN
    assert result["request_status_counts"]["skipped"] > 0
    with sqlite3.connect(repository.path) as db:
        reasons = dict(
            db.execute(
                "SELECT reason,COUNT(*) FROM baseline_capture_request_v1 "
                "WHERE status='skipped' GROUP BY reason"
            ).fetchall()
        )
    assert reasons == {"storage_budget_exhausted": result["request_status_counts"]["skipped"]}


def test_due_retry_from_earlier_same_day_run_runs_after_fresh_boundary(
    tmp_path: Path,
) -> None:
    repo = ScheduledCaptureRepository(tmp_path / "capture.sqlite")
    provider = FakeProvider(fail_first=True)
    service = ScheduledCaptureService(repo, provider)
    plan = _plan()
    first = service.run_cycle(plan, _environment(), NOW)
    assert first["request_status_counts"]["retry"] == 1

    next_boundary = NOW + timedelta(hours=6)
    second = service.run_cycle(plan, _environment(captured=next_boundary), next_boundary)
    assert second["state"] == "complete"
    assert second["current_run_provider_calls"] == 105
    assert second["prior_run_retry_attempts"] == 1
    assert second["provider_calls_this_invocation"] == 106
    assert len(provider.calls) == 211
    assert second["prior_run_retries"][0]["state"] == "complete"
    health = repo.health(tmp_path / "capture.sqlite", plan, NOW.date())
    assert health["actual_provider_attempts"] == 211
    assert health["coverage_state"] == "incomplete"


def test_previous_utc_day_work_is_missed_without_provider_catchup(tmp_path: Path) -> None:
    path = tmp_path / "capture.sqlite"
    repo = ScheduledCaptureRepository(path)
    provider = FakeProvider()
    service = ScheduledCaptureService(repo, provider)
    plan = _plan()
    previous_boundary = NOW - timedelta(days=1, hours=6)
    previous_run_id, _, _ = repo.prepare_run(
        plan, _environment(captured=previous_boundary), previous_boundary,
        captured_at_utc=previous_boundary,
    )

    result = service.run_cycle(plan, _environment(), NOW)
    assert result["current_run_provider_calls"] == 105
    assert result["prior_run_retry_attempts"] == 0
    assert len(provider.calls) == 105
    with sqlite3.connect(path) as db:
        assert db.execute(
            "SELECT status,reason,attempts FROM baseline_capture_request_v1 WHERE run_id=? LIMIT 1",
            (previous_run_id,),
        ).fetchone() == ("missed", "utc_day_ended", 0)
