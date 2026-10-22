"""Offline-only acceptance for the C4 bounded baseline sampler."""

from __future__ import annotations

import inspect
import sqlite3
import threading
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError

from rolling_thunder.forge_ft8_attempt_correlation import DOCUMENTED_SYNTHETIC_ATTEMPTS
from rolling_thunder.forge_ft8_historical_replay import AA4NP_ATTEMPT_UUID
from rolling_thunder.forge_voacap_baseline import (
    BASELINE_SCHEMA_VERSION,
    REFERENCE_POWER_WATTS,
    SCHEDULE_HOURS_UTC,
    SUPPORTED_BANDS,
    BaselineConfig,
    BaselinePlan,
    BaselineProvider,
    BaselineRepository,
    BaselineService,
    EnvironmentSnapshot,
    ProviderFailure,
    ProviderResult,
    TargetGrid,
)

PLAN_ID = UUID("10000000-0000-4000-8000-000000000001")
NOW = datetime(2026, 10, 10, 12, tzinfo=UTC)
DAY = date(2026, 10, 11)


class FakeClock:
    def __init__(self, now: datetime = NOW) -> None:
        self.value = now

    def now(self) -> datetime:
        return self.value


class FakeProvider(BaselineProvider):
    def __init__(self, outcomes: list[object] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.outcomes = outcomes or []

    def predict(self, request: dict[str, Any], *, timeout_s: float) -> ProviderResult:
        self.calls.append(dict(request))
        if self.outcomes:
            outcome = self.outcomes.pop(0)
            if isinstance(outcome, BaseException):
                raise outcome
            assert isinstance(outcome, ProviderResult)
            return outcome
        band = request["bands_m"][0]
        return _result(band)


def _result(band: int = 40, *, service: str = "svc-1", model: str = "model-1") -> ProviderResult:
    return ProviderResult(
        service_version=service,
        model_version=model,
        response_json={
            "analysis": {
                "best_band_by_hour": [
                    {"hour_utc": hour, "band_m": band, "reliability": 0.5, "snr_db": 12.0}
                    for hour in SCHEDULE_HOURS_UTC
                ]
            }
        },
    )


def _plan(**changes: Any) -> BaselinePlan:
    values: dict[str, Any] = {
        "plan_id": PLAN_ID,
        "plan_version": "plan-1",
        "created_at_utc": NOW,
        "origin_grid": "EM79xm",
        "origin_uncertainty": "six-character Maidenhead cell center assumption",
        "target_inventory_version": "regions-1",
        "targets": (
            TargetGrid(region_id="florida", grid="EL98", uncertainty="grid4 cell center; coarse"),
        ),
        "model_version": "model-1",
        "service_version": "svc-1",
        "ssn_source": "offline-fixture",
        "ssn_source_version": "ssn-1",
        "ssn_value_semantics": "monthly_smoothed_predicted_sunspot_number",
        "ssn_source_schema": "fixture-schema-v1",
        "ssn_revision_policy": "append-only fixture captures",
        "max_provider_calls_per_cycle": 8,
        "max_provider_calls_per_day": 16,
        "max_slots_per_cycle": 64,
    }
    values.update(changes)
    return BaselinePlan.model_validate(values)


def _environment() -> EnvironmentSnapshot:
    return EnvironmentSnapshot(
        ssn=132.5,
        value_semantics="monthly_smoothed_predicted_sunspot_number",
        target_month="2026-10",
        source="offline-fixture",
        source_url="https://example.invalid/predicted.json",
        source_version="ssn-1",
        source_schema="fixture-schema-v1",
        source_revision_policy="append-only fixture captures",
        source_record_id="2026-10:predicted_ssn",
        captured_at_utc=NOW,
        raw_sha256="a" * 64,
        snapshot_canonical_sha256="b" * 64,
    )


def _setup(tmp_path: Path, **plan_changes: Any) -> tuple[BaselineRepository, BaselinePlan]:
    repository = BaselineRepository(tmp_path / "baseline.sqlite")
    plan = _plan(**plan_changes)
    assert repository.schedule_day(plan, DAY, _environment(), scheduled_at_utc=NOW) == 28
    return repository, plan


def _counts(path: Path) -> dict[str, int]:
    with sqlite3.connect(path) as db:
        return dict(db.execute("SELECT status,COUNT(*) FROM baseline_slot_v1 GROUP BY status"))


def test_plan_identity_grid_precision_and_contract_are_frozen(tmp_path: Path) -> None:
    repository, plan = _setup(tmp_path)
    assert BASELINE_SCHEMA_VERSION == 1
    assert plan.origin_grid == "EM79xm"
    assert plan.targets[0].grid == "EL98"
    assert plan.targets[0].precision == 4
    assert plan.bands_m == SUPPORTED_BANDS
    assert plan.hours_utc == SCHEDULE_HOURS_UTC
    assert plan.reference_power_watts == REFERENCE_POWER_WATTS == 20
    assert plan.concurrency == 1
    assert repository.add_plan(plan) is False
    with pytest.raises(ValueError, match="changed immutable"):
        repository.add_plan(plan.model_copy(update={"plan_version": "changed"}))
    with pytest.raises(ValidationError, match="origin_grid"):
        _plan(origin_grid="EM79")
    with pytest.raises(ValidationError, match="supported-band"):
        _plan(bands_m=(80,))


def test_monthly_request_deduplicates_four_hour_slots_and_rollover_boundaries(tmp_path: Path) -> None:
    repository, plan = _setup(tmp_path)
    provider = FakeProvider()
    service = BaselineService(repository, provider, FakeClock())
    result = service.run_cycle(
        plan, BaselineConfig(enabled=True, scheduler_enabled=True, provider_enabled=True)
    )
    assert result == {"state": "complete", "slots": 28, "provider_calls": 7}
    assert len(provider.calls) == 7
    assert all("hour" not in request for request in provider.calls)
    assert {request["month"] for request in provider.calls} == {10}
    assert _counts(repository.path) == {"ready": 28}
    with sqlite3.connect(repository.path) as db:
        rows = db.execute(
            "SELECT DISTINCT substr(forecast_for_utc,12,2),timing_class FROM baseline_slot_v1 ORDER BY 1"
        ).fetchall()
    assert rows == [("00", "pre_choice"), ("06", "pre_choice"), ("12", "pre_choice"), ("18", "pre_choice")]


def test_disabled_gates_and_unsupported_band_skip_without_provider(tmp_path: Path) -> None:
    repository, plan = _setup(tmp_path)
    provider = FakeProvider()
    service = BaselineService(repository, provider, FakeClock())
    assert service.run_cycle(plan, BaselineConfig())["state"] == "disabled"
    with sqlite3.connect(repository.path) as db:
        db.execute("UPDATE baseline_slot_v1 SET band_m=80 WHERE rowid=(SELECT MIN(rowid) FROM baseline_slot_v1)")
    result = service.run_cycle(plan, BaselineConfig(enabled=True, scheduler_enabled=True))
    assert result["provider_calls"] == 0
    assert not provider.calls
    counts = _counts(repository.path)
    assert counts["skipped"] == 28


@pytest.mark.parametrize(
    ("outcome", "expected_reason"),
    [
        (ProviderFailure("http_500", retryable=True), "http_500"),
        (ProviderFailure("http_429", retryable=True), "http_429"),
        (TimeoutError("timeout"), "provider_error:TimeoutError"),
        (_result(service="wrong"), "provider_version_mismatch"),
        (ProviderResult(service_version="svc-1", model_version="model-1", response_json={}), "malformed_response"),
        (ProviderResult(
            service_version="svc-1",
            model_version="model-1",
            response_json={"analysis": {"best_band_by_hour": []}},
        ), "requested_hour_band_missing"),
        (ProviderResult(
            service_version="svc-1",
            model_version="model-1",
            response_json={
                "analysis": {"best_band_by_hour": [{"hour_utc": 0, "band_m": 10}]}
            },
        ), "malformed_requested_hour_band"),
    ],
)
def test_provider_failures_are_bounded_and_explicit(
    tmp_path: Path, outcome: object, expected_reason: str
) -> None:
    repository, plan = _setup(tmp_path, max_provider_calls_per_cycle=1)
    provider = FakeProvider([outcome])
    BaselineService(repository, provider, FakeClock()).run_cycle(
        plan, BaselineConfig(enabled=True, scheduler_enabled=True, provider_enabled=True)
    )
    with sqlite3.connect(repository.path) as db:
        row = db.execute(
            "SELECT status,reason,attempt_count FROM baseline_slot_v1 ORDER BY forecast_for_utc,band_m LIMIT 1"
        ).fetchone()
        calls = db.execute(
            "SELECT COUNT(*) FROM baseline_activity_v1 WHERE action='provider_call'"
        ).fetchone()[0]
        cached = db.execute("SELECT COUNT(*) FROM baseline_provider_response_v1").fetchone()[0]
    if expected_reason == "requested_hour_band_missing":
        assert row[0] == "unavailable"
    else:
        assert row[0] in {"retry", "failed"}
    assert row[1] == expected_reason
    assert row[2] == 1
    assert calls == 1
    assert cached == 0


def test_missing_ssn_and_oversized_response_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="ssn"):
        EnvironmentSnapshot.model_validate(
            {**_environment().model_dump(), "ssn": None}
        )
    repository, plan = _setup(tmp_path, max_provider_calls_per_cycle=1, response_size_limit_bytes=1024)
    huge = _result().model_copy(
        update={"response_json": {"analysis": {"best_band_by_hour": [], "padding": "x" * 2000}}}
    )
    BaselineService(repository, FakeProvider([huge]), FakeClock()).run_cycle(
        plan, BaselineConfig(enabled=True, scheduler_enabled=True, provider_enabled=True)
    )
    with sqlite3.connect(repository.path) as db:
        assert db.execute("SELECT reason FROM baseline_slot_v1 WHERE status='failed'").fetchone()[0] == "response_oversized"


def test_storage_cap_skips_without_provider_call(tmp_path: Path) -> None:
    repository, plan = _setup(tmp_path, storage_limit_bytes=1_000_000)
    with sqlite3.connect(repository.path) as db:
        db.execute("CREATE TABLE padding(value BLOB NOT NULL)")
        db.execute("INSERT INTO padding(value) VALUES (zeroblob(1100000))")
    provider = FakeProvider()
    BaselineService(repository, provider, FakeClock()).run_cycle(
        plan, BaselineConfig(enabled=True, scheduler_enabled=True, provider_enabled=True)
    )
    assert not provider.calls
    with sqlite3.connect(repository.path) as db:
        assert db.execute("SELECT DISTINCT reason FROM baseline_slot_v1").fetchall() == [
            ("storage_budget_exhausted",)
        ]


def test_call_cap_retry_lease_restart_backlog_and_outage(tmp_path: Path) -> None:
    repository, plan = _setup(
        tmp_path,
        max_provider_calls_per_cycle=2,
        max_attempts=2,
        lease_seconds=10,
        backlog_limit_days=0,
    )
    clock = FakeClock(NOW)
    provider = FakeProvider([ProviderFailure("outage", retryable=True)] * 2)
    result = BaselineService(repository, provider, clock).run_cycle(
        plan, BaselineConfig(enabled=True, scheduler_enabled=True, provider_enabled=True)
    )
    assert result["provider_calls"] == 2
    assert len(provider.calls) == 2
    claim = repository.claim_one(plan, NOW)
    assert claim is not None
    clock.value = NOW + timedelta(seconds=11)
    recovered = repository.claim_one(plan, clock.value)
    assert recovered is not None
    assert recovered["slot_key"] == claim["slot_key"]
    clock.value = datetime(2026, 10, 12, tzinfo=UTC)
    repository.claim_one(plan, clock.value)
    assert _counts(repository.path).get("missed", 0) > 0


def test_concurrency_guard_permits_only_one_cycle(tmp_path: Path) -> None:
    repository, plan = _setup(tmp_path, max_provider_calls_per_cycle=1)
    entered = threading.Event()
    release = threading.Event()

    class BlockingProvider(FakeProvider):
        def predict(self, request: dict[str, Any], *, timeout_s: float) -> ProviderResult:
            entered.set()
            release.wait(timeout=2)
            return super().predict(request, timeout_s=timeout_s)

    service = BaselineService(repository, BlockingProvider(), FakeClock())
    config = BaselineConfig(enabled=True, scheduler_enabled=True, provider_enabled=True)
    thread = threading.Thread(target=service.run_cycle, args=(plan, config))
    thread.start()
    assert entered.wait(timeout=1)
    assert service.run_cycle(plan, config)["state"] == "busy"
    release.set()
    thread.join(timeout=2)
    assert not thread.is_alive()


def test_durable_lease_enforces_single_concurrency_across_repository_instances(
    tmp_path: Path,
) -> None:
    repository, plan = _setup(tmp_path)
    first = repository.claim_one(plan, NOW)
    assert first is not None
    second_process_view = BaselineRepository(repository.path)
    assert second_process_view.claim_one(plan, NOW) is None


def test_late_and_backfill_timing_are_distinct(tmp_path: Path) -> None:
    late_repository = BaselineRepository(tmp_path / "late.sqlite")
    late_plan = _plan()
    late_repository.schedule_day(
        late_plan, DAY, _environment(), scheduled_at_utc=NOW
    )
    late_clock = FakeClock(datetime(2026, 10, 11, 1, tzinfo=UTC))
    BaselineService(late_repository, FakeProvider(), late_clock).run_cycle(
        late_plan,
        BaselineConfig(enabled=True, scheduler_enabled=True, provider_enabled=True),
    )

    backfill_repository = BaselineRepository(tmp_path / "backfill.sqlite")
    backfill_plan = _plan()
    backfill_repository.schedule_day(
        backfill_plan,
        DAY,
        _environment(),
        scheduled_at_utc=datetime(2026, 10, 11, 2, tzinfo=UTC),
    )
    backfill_clock = FakeClock(datetime(2026, 10, 11, 2, tzinfo=UTC))
    BaselineService(backfill_repository, FakeProvider(), backfill_clock).run_cycle(
        backfill_plan,
        BaselineConfig(enabled=True, scheduler_enabled=True, provider_enabled=True),
    )

    with sqlite3.connect(late_repository.path) as db:
        assert db.execute(
            "SELECT COUNT(*) FROM baseline_slot_v1 WHERE timing_class='late'"
        ).fetchone()[0] > 0
    with sqlite3.connect(backfill_repository.path) as db:
        assert db.execute(
            "SELECT COUNT(*) FROM baseline_slot_v1 WHERE timing_class='backfill'"
        ).fetchone()[0] > 0


def test_plan_and_model_fork_append_and_legacy_copy_is_preserved(tmp_path: Path) -> None:
    path = tmp_path / "migration.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE legacy_history(id INTEGER PRIMARY KEY,payload TEXT NOT NULL)")
        db.execute("INSERT INTO legacy_history(payload) VALUES ('preserve-me')")
    repository = BaselineRepository(path)
    parent = _plan()
    child = _plan(
        plan_id=UUID("10000000-0000-4000-8000-000000000002"),
        parent_plan_id=PLAN_ID,
        plan_version="plan-2",
        model_version="model-2",
    )
    repository.add_plan(parent)
    repository.add_plan(child)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT payload FROM legacy_history").fetchone()[0] == "preserve-me"
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert db.execute("SELECT COUNT(*) FROM baseline_plan_v1").fetchone()[0] == 2


def test_old_c4_slot_schema_fails_closed_without_migration(tmp_path: Path) -> None:
    path = tmp_path / "old-c4.sqlite"
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE baseline_slot_v1(slot_key TEXT,ssn_observed_at_utc TEXT NOT NULL)"
        )
    before = path.read_bytes()
    with pytest.raises(ValueError, match="predates predicted-SSN provenance"):
        BaselineRepository(path)
    assert path.read_bytes() == before


def test_diagnostics_are_read_only_deterministic_and_training_ineligible(tmp_path: Path) -> None:
    repository, plan = _setup(tmp_path)
    BaselineService(repository, FakeProvider(), FakeClock()).run_cycle(
        plan, BaselineConfig(enabled=True, scheduler_enabled=True, provider_enabled=True)
    )
    before = repository.path.read_bytes()
    first = repository.diagnostics(generated_at_utc=NOW)
    second = repository.diagnostics(generated_at_utc=NOW)
    assert first == second
    assert first["training_eligible"] is False
    assert {row["band_m"] for row in first["coverage"]} == set(SUPPORTED_BANDS)
    assert {row["hour_utc"] for row in first["coverage"]} == set(SCHEDULE_HOURS_UTC)
    assert repository.path.read_bytes() == before


def test_operational_health_classifies_provider_storage_and_cache_reuse(tmp_path: Path) -> None:
    repository, plan = _setup(tmp_path)
    BaselineService(repository, FakeProvider(), FakeClock()).run_cycle(
        plan, BaselineConfig(enabled=True, scheduler_enabled=True, provider_enabled=True)
    )
    before = repository.path.read_bytes()
    health = BaselineRepository.inspect_operational_health(
        repository.path,
        plan,
        generated_at_utc=NOW,
        forecast_days=(DAY,),
    )
    assert health["coverage_state"] == "complete"
    assert health["expected_slots"] == health["observed_slots"] == 28
    assert health["ready_provider_slots"] == 7
    assert health["ready_reused_slots"] == 21
    assert health["provider_calls_today"] == 7
    assert health["pending_slots"] == health["missing_slots"] == 0
    assert repository.path.read_bytes() == before


def test_operational_health_detects_incomplete_and_unavailable_coverage(tmp_path: Path) -> None:
    repository, plan = _setup(tmp_path, max_provider_calls_per_cycle=1)
    provider = FakeProvider(
        [ProviderFailure("requested_hour_band_missing", retryable=False)]
    )
    BaselineService(repository, provider, FakeClock()).run_cycle(
        plan, BaselineConfig(enabled=True, scheduler_enabled=True, provider_enabled=True)
    )
    health = BaselineRepository.inspect_operational_health(
        repository.path,
        plan,
        generated_at_utc=NOW,
        forecast_days=(DAY,),
    )
    assert health["coverage_state"] == "incomplete"
    assert health["unavailable_slots"] == 1
    assert health["pending_slots"] == 27
    assert health["provider_contacted_slots"] == 1


def test_operational_health_requires_existing_store_and_expected_day(tmp_path: Path) -> None:
    plan = _plan()
    with pytest.raises(ValueError, match="at least one forecast day"):
        BaselineRepository.inspect_operational_health(
            tmp_path / "missing.sqlite",
            plan,
            generated_at_utc=NOW,
            forecast_days=(),
        )
    with pytest.raises(ValueError, match="existing baseline database"):
        BaselineRepository.inspect_operational_health(
            tmp_path / "missing.sqlite",
            plan,
            generated_at_utc=NOW,
            forecast_days=(DAY,),
        )


def test_audit_identities_and_no_network_implementation_are_unchanged() -> None:
    assert str(AA4NP_ATTEMPT_UUID) == "938620bb-b4ff-40b2-9493-081b56bb038c"
    assert {str(item[0]) for item in DOCUMENTED_SYNTHETIC_ATTEMPTS} == {
        "9ad2f0c2-ed0e-4ba7-8b03-732d8aa8c339",
        "1d99bba6-0f38-4069-a706-77f9a90d4a8c",
    }
    source = inspect.getsource(__import__("rolling_thunder.forge_voacap_baseline", fromlist=["*"]))
    assert "urllib" not in source
    assert "httpx" not in source
    assert "socket" not in source


def test_forecast_queue_prefers_future_slots_over_expired_backlog(tmp_path: Path) -> None:
    """An old pending slot cannot crowd out a prospective future prediction."""
    repo = BaselineRepository(tmp_path / "future-priority.sqlite3")
    plan = _plan()
    repo.schedule_day(plan, date(2026, 10, 9), _environment(),
                      scheduled_at_utc=NOW - timedelta(days=2))
    repo.schedule_day(plan, DAY, _environment(), scheduled_at_utc=NOW)
    claim = repo.claim_one(plan, NOW)
    assert claim is not None
    assert str(claim["forecast_for_utc"]).startswith("2026-10-11")
