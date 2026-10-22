import hashlib
import sqlite3
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import pytest

from rolling_thunder.forge_solar_ssn import SmoothedSsnSnapshot
from rolling_thunder.forge_voacap_baseline_main import (
    LocalVoacapProvider,
    SamplingRuntime,
    read_operational_health,
    run_controlled_pilot,
    run_once,
)


def _ssn_snapshot(
    captured_at_utc: datetime, *, source: str = "fixture", version: str = "fixture-v1"
) -> SmoothedSsnSnapshot:
    raw = b"offline predicted SSN fixture"
    return SmoothedSsnSnapshot(
        value=100,
        value_semantics="monthly_smoothed_predicted_sunspot_number",
        target_month="2026-10",
        source_id=source,
        source_url="https://example.invalid/predicted.json",
        source_version=version,
        source_schema="fixture-schema-v1",
        source_revision_policy="append-only fixture captures",
        source_record_id="2026-10:predicted_ssn",
        captured_at_utc=captured_at_utc,
        raw_sha256=hashlib.sha256(raw).hexdigest(),
        raw_payload=raw,
    )


def test_disabled_never_opens_database_or_provider(tmp_path: Path) -> None:
    config = SamplingRuntime(
        database_path=tmp_path / "never.db",
        plan_path=tmp_path / "not-present-plan.json",
        environment_path=tmp_path / "not-present-env.json",
        ssn_snapshot_path=tmp_path / "not-present-snapshot.json",
    )
    assert run_once(config) == {"state": "disabled", "provider_calls": 0, "scheduled_slots": 0}
    assert not config.database_path.exists()


def test_gate_dependencies_and_local_only(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        SamplingRuntime(
            scheduler_enabled=True, database_path=tmp_path / "db",
            plan_path=tmp_path / "plan", environment_path=tmp_path / "env",
            ssn_snapshot_path=tmp_path / "snapshot",
        ).gates()
    with pytest.raises(ValueError):
        LocalVoacapProvider("http://example.org:8787", service_version="a", model_version="b")


def test_disabled_provider_does_not_schedule_skipped_slots(tmp_path: Path) -> None:
    now = datetime(2026, 10, 11, 17, 0, tzinfo=UTC)
    config = SamplingRuntime(
        process_enabled=True, scheduler_enabled=True, provider_enabled=False,
        database_path=tmp_path / "c4.db",
        plan_path=tmp_path / "missing-plan.json",
        environment_path=tmp_path / "missing-env.json",
        ssn_snapshot_path=tmp_path / "missing-snapshot.json",
    )
    assert run_once(config, now=now) == {
        "state": "disabled", "provider_calls": 0, "scheduled_slots": 0,
    }
    assert not config.database_path.exists()


def test_read_operational_health_does_not_require_enabled_gates_or_provider(
    tmp_path: Path,
) -> None:
    from rolling_thunder.forge_voacap_baseline import (
        BaselinePlan,
        BaselineRepository,
        EnvironmentSnapshot,
        TargetGrid,
    )

    now = datetime(2026, 10, 11, 23, 30, tzinfo=timezone(-timedelta(hours=4)))
    tomorrow = (now.astimezone(UTC) + timedelta(days=1)).date()
    plan = BaselinePlan(
        plan_id=UUID("20000000-0000-4000-8000-000000000001"),
        plan_version="health-v1",
        created_at_utc=now,
        origin_grid="EM79xm",
        origin_uncertainty="fixed grid6",
        target_inventory_version="test-v1",
        targets=(TargetGrid(region_id="region", grid="EN80", uncertainty="grid4"),),
        model_version="model-1",
        service_version="0.3.0",
        ssn_source="fixture",
        ssn_source_version="fixture-v1",
        ssn_value_semantics="monthly_smoothed_predicted_sunspot_number",
        ssn_source_schema="fixture-schema-v1",
        ssn_revision_policy="append-only fixture captures",
    )
    snapshot = _ssn_snapshot(now)
    environment = EnvironmentSnapshot(
        ssn=snapshot.value,
        value_semantics="monthly_smoothed_predicted_sunspot_number",
        target_month="2026-10",
        source="fixture",
        source_url="https://example.invalid/predicted.json",
        source_version="fixture-v1",
        source_schema="fixture-schema-v1",
        source_revision_policy="append-only fixture captures",
        source_record_id="2026-10:predicted_ssn",
        captured_at_utc=now,
        raw_sha256=snapshot.raw_sha256,
        snapshot_canonical_sha256=snapshot.canonical_sha256,
    )
    database = tmp_path / "c4.sqlite"
    repository = BaselineRepository(database)
    repository.schedule_day(plan, tomorrow, environment, scheduled_at_utc=now)
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(plan.model_dump_json())
    config = SamplingRuntime(
        database_path=database,
        plan_path=plan_path,
        environment_path=tmp_path / "not-read-environment.json",
        ssn_snapshot_path=tmp_path / "not-read-snapshot.json",
    )
    before = database.read_bytes()
    result = read_operational_health(config, now=now)
    health = result["operational_health"]
    assert result["state"] == "health"
    assert isinstance(health, dict)
    assert health["coverage_state"] == "incomplete"
    assert health["pending_slots"] == 28
    assert health["forecast_days"] == ["2026-10-13"]
    assert database.read_bytes() == before


def test_reject_stale_ssn_without_creating_database(tmp_path: Path) -> None:
    config = SamplingRuntime(
        process_enabled=True, scheduler_enabled=True, provider_enabled=True,
        database_path=tmp_path / "c4.db",
        plan_path=tmp_path / "plan.json", environment_path=tmp_path / "env.json",
        ssn_snapshot_path=tmp_path / "snapshot.json",
    )
    config.plan_path.write_text("{}")
    with pytest.raises(ValueError):
        run_once(config)
    assert not config.database_path.exists()


def test_future_days_are_derived_from_utc_not_local_calendar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """23:30 Eastern is already the next UTC day; schedule the day after that."""
    from rolling_thunder.forge_voacap_baseline import (
        BaselinePlan,
        EnvironmentSnapshot,
        TargetGrid,
    )

    local_now = datetime(2026, 10, 11, 23, 30, tzinfo=timezone(-timedelta(hours=4)))
    plan = BaselinePlan(
        plan_id=UUID("10000000-0000-4000-8000-000000000001"),
        plan_version="utc-boundary-v1",
        created_at_utc=datetime(2026, 10, 11, tzinfo=UTC),
        origin_grid="EM79xm",
        origin_uncertainty="fixed grid6",
        target_inventory_version="test-v1",
        targets=(TargetGrid(region_id="region", grid="EN80", uncertainty="grid4"),),
        model_version="model-1",
        service_version="0.3.0",
        ssn_source="fixture",
        ssn_source_version="fixture-v1",
        ssn_value_semantics="monthly_smoothed_predicted_sunspot_number",
        ssn_source_schema="fixture-schema-v1",
        ssn_revision_policy="append-only fixture captures",
        max_provider_calls_per_cycle=1,
        max_slots_per_cycle=1,
    )
    snapshot = _ssn_snapshot(local_now.astimezone(UTC))
    environment = EnvironmentSnapshot(
        ssn=snapshot.value,
        value_semantics="monthly_smoothed_predicted_sunspot_number",
        target_month="2026-10",
        source="fixture",
        source_url="https://example.invalid/predicted.json",
        source_version="fixture-v1",
        source_schema="fixture-schema-v1",
        source_revision_policy="append-only fixture captures",
        source_record_id="2026-10:predicted_ssn",
        captured_at_utc=local_now.astimezone(UTC),
        raw_sha256=snapshot.raw_sha256,
        snapshot_canonical_sha256=snapshot.canonical_sha256,
    )
    plan_path = tmp_path / "plan.json"
    environment_path = tmp_path / "environment.json"
    snapshot_path = tmp_path / "snapshot.json"
    plan_path.write_text(plan.model_dump_json())
    environment_path.write_text(environment.model_dump_json())
    snapshot_path.write_text(snapshot.model_dump_json())
    config = SamplingRuntime(
        process_enabled=True, scheduler_enabled=True, provider_enabled=True,
        database_path=tmp_path / "c4.sqlite", plan_path=plan_path,
        environment_path=environment_path,
        ssn_snapshot_path=snapshot_path,
    )

    changed_snapshot = snapshot.model_copy(update={"value": 101.0})
    snapshot_path.write_text(changed_snapshot.model_dump_json())
    with pytest.raises(ValueError, match="does not match the verified SSN snapshot"):
        run_once(config, now=local_now)
    assert not config.database_path.exists()
    snapshot_path.write_text(snapshot.model_dump_json())

    class FailedPreflightProvider:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def verify_version(self, *, timeout_s: float) -> None:
            raise ProviderFailure("provider_version_mismatch", retryable=False)

    from rolling_thunder.forge_voacap_baseline import ProviderFailure

    monkeypatch.setattr(
        "rolling_thunder.forge_voacap_baseline_main.LocalVoacapProvider",
        FailedPreflightProvider,
    )
    with pytest.raises(ProviderFailure, match="provider_version_mismatch"):
        run_once(config, now=local_now)
    assert not config.database_path.exists()

    class NoCallProvider:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def predict(self, request: object, *, timeout_s: float) -> object:
            raise AssertionError("provider not needed to verify scheduled UTC day")

        def verify_version(self, *, timeout_s: float) -> None:
            return None

    monkeypatch.setattr("rolling_thunder.forge_voacap_baseline_main.LocalVoacapProvider", NoCallProvider)
    # Disable provider execution after scheduling while preserving the enabled entry path.
    monkeypatch.setattr(
        "rolling_thunder.forge_voacap_baseline.BaselineService.run_cycle",
        lambda *args, **kwargs: {"state": "complete", "slots": 0, "provider_calls": 0},
    )
    run_once(config, now=local_now)
    import sqlite3
    with sqlite3.connect(config.database_path) as db:
        days = db.execute(
            "SELECT DISTINCT substr(forecast_for_utc,1,10) FROM baseline_slot_v1"
        ).fetchall()
    assert days == [("2026-10-13",)]


def test_controlled_pilot_requires_phrase_bounds_and_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from rolling_thunder.forge_voacap_baseline import (
        BaselinePlan,
        BaselineRepository,
        EnvironmentSnapshot,
        TargetGrid,
    )

    now = datetime(2026, 10, 12, 12, tzinfo=UTC)
    plan = BaselinePlan(
        plan_id=UUID("30000000-0000-4000-8000-000000000001"),
        plan_version="pilot-v1", created_at_utc=now, origin_grid="EM79xm",
        origin_uncertainty="fixed grid6", target_inventory_version="reviewed-v1",
        targets=(TargetGrid(region_id="region", grid="EN80", uncertainty="grid4"),),
        model_version="model-1", service_version="0.3.0",
        ssn_source="reviewed", ssn_source_version="release-1",
        ssn_value_semantics="monthly_smoothed_predicted_sunspot_number",
        ssn_source_schema="fixture-schema-v1",
        ssn_revision_policy="append-only fixture captures",
        max_provider_calls_per_cycle=1, max_provider_calls_per_day=1,
        max_slots_per_cycle=1, max_attempts=1, provider_timeout_s=10,
    )
    snapshot = _ssn_snapshot(now, source="reviewed", version="release-1")
    environment = EnvironmentSnapshot(
        ssn=snapshot.value, value_semantics="monthly_smoothed_predicted_sunspot_number",
        target_month="2026-10", source="reviewed",
        source_url="https://example.invalid/predicted.json", source_version="release-1",
        source_schema="fixture-schema-v1",
        source_revision_policy="append-only fixture captures",
        source_record_id="2026-10:predicted_ssn", captured_at_utc=now,
        raw_sha256=snapshot.raw_sha256,
        snapshot_canonical_sha256=snapshot.canonical_sha256,
    )
    database = tmp_path / "c4.sqlite"
    BaselineRepository(database).add_plan(plan)
    plan_path = tmp_path / "plan.json"
    environment_path = tmp_path / "environment.json"
    snapshot_path = tmp_path / "snapshot.json"
    plan_path.write_text(plan.model_dump_json())
    environment_path.write_text(environment.model_dump_json())
    snapshot_path.write_text(snapshot.model_dump_json())
    config = SamplingRuntime(
        process_enabled=True, scheduler_enabled=True, provider_enabled=True,
        database_path=database, plan_path=plan_path, environment_path=environment_path,
        ssn_snapshot_path=snapshot_path,
    )
    with pytest.raises(ValueError, match="phrase"):
        run_controlled_pilot(
            config, approval_phrase="NO", backup_directory=tmp_path / "backups", now=now
        )
    monkeypatch.setattr(
        "rolling_thunder.forge_voacap_baseline_main.run_once",
        lambda *args, **kwargs: {
            "state": "complete", "provider_calls": 1, "scheduled_slots": 28,
            "processed_slots": 1,
        },
    )
    result = run_controlled_pilot(
        config, approval_phrase="AUTHORIZE_C4_ONE_POST_PILOT",
        backup_directory=tmp_path / "backups", now=now,
    )
    assert result["provider_calls"] == 1
    backup = Path(str(result["backup_path"]))
    assert backup.is_file()
    assert Path(str(result["audit_path"])).is_file()
    assert result["backup_row_counts"]["baseline_plan_v1"] == 1
    with sqlite3.connect(backup) as db:
        assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)


def test_controlled_pilot_preserves_failure_audit_without_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reuse the bounded fixture setup above but force one ambiguous run failure."""
    from rolling_thunder.forge_voacap_baseline import (
        BaselinePlan,
        BaselineRepository,
        EnvironmentSnapshot,
        TargetGrid,
    )

    now = datetime(2026, 10, 12, 12, tzinfo=UTC)
    plan = BaselinePlan(
        plan_id=UUID("40000000-0000-4000-8000-000000000001"), plan_version="pilot-v1",
        created_at_utc=now, origin_grid="EM79xm", origin_uncertainty="fixed grid6",
        target_inventory_version="reviewed-v1",
        targets=(TargetGrid(region_id="region", grid="EN80", uncertainty="grid4"),),
        model_version="model-1", service_version="0.3.0", ssn_source="reviewed",
        ssn_source_version="release-1",
        ssn_value_semantics="monthly_smoothed_predicted_sunspot_number",
        ssn_source_schema="fixture-schema-v1",
        ssn_revision_policy="append-only fixture captures",
        max_provider_calls_per_cycle=1, max_provider_calls_per_day=1,
        max_slots_per_cycle=1, max_attempts=1, provider_timeout_s=10,
    )
    snapshot = _ssn_snapshot(now, source="reviewed", version="release-1")
    environment = EnvironmentSnapshot(
        ssn=snapshot.value, value_semantics="monthly_smoothed_predicted_sunspot_number",
        target_month="2026-10", source="reviewed",
        source_url="https://example.invalid/predicted.json", source_version="release-1",
        source_schema="fixture-schema-v1",
        source_revision_policy="append-only fixture captures",
        source_record_id="2026-10:predicted_ssn", captured_at_utc=now,
        raw_sha256=snapshot.raw_sha256,
        snapshot_canonical_sha256=snapshot.canonical_sha256,
    )
    database = tmp_path / "c4.sqlite"
    BaselineRepository(database).add_plan(plan)
    plan_path = tmp_path / "plan.json"
    environment_path = tmp_path / "environment.json"
    snapshot_path = tmp_path / "snapshot.json"
    plan_path.write_text(plan.model_dump_json())
    environment_path.write_text(environment.model_dump_json())
    snapshot_path.write_text(snapshot.model_dump_json())
    config = SamplingRuntime(
        process_enabled=True, scheduler_enabled=True, provider_enabled=True,
        database_path=database, plan_path=plan_path, environment_path=environment_path,
        ssn_snapshot_path=snapshot_path,
    )
    calls = 0

    def fail_once(*args: object, **kwargs: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        raise TimeoutError("ambiguous provider outcome")

    monkeypatch.setattr("rolling_thunder.forge_voacap_baseline_main.run_once", fail_once)
    result = run_controlled_pilot(
        config, approval_phrase="AUTHORIZE_C4_ONE_POST_PILOT",
        backup_directory=tmp_path / "backups", now=now,
    )
    assert calls == 1
    assert result["state"] == "failed"
    assert result["provider_calls"] == 0
    assert result["failure_type"] == "TimeoutError"
    assert Path(str(result["audit_path"])).is_file()
