import sqlite3
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import pytest

from rolling_thunder.forge_voacap_baseline_main import (
    LocalVoacapProvider,
    SamplingRuntime,
    run_controlled_pilot,
    run_once,
)


def test_disabled_never_opens_database_or_provider(tmp_path: Path) -> None:
    config = SamplingRuntime(
        database_path=tmp_path / "never.db",
        plan_path=tmp_path / "not-present-plan.json",
        environment_path=tmp_path / "not-present-env.json",
    )
    assert run_once(config) == {"state": "disabled", "provider_calls": 0, "scheduled_slots": 0}
    assert not config.database_path.exists()


def test_gate_dependencies_and_local_only(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        SamplingRuntime(
            scheduler_enabled=True, database_path=tmp_path / "db",
            plan_path=tmp_path / "plan", environment_path=tmp_path / "env",
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
    )
    assert run_once(config, now=now) == {
        "state": "disabled", "provider_calls": 0, "scheduled_slots": 0,
    }
    assert not config.database_path.exists()


def test_reject_stale_ssn_without_creating_database(tmp_path: Path) -> None:
    config = SamplingRuntime(
        process_enabled=True, scheduler_enabled=True, provider_enabled=True,
        database_path=tmp_path / "c4.db",
        plan_path=tmp_path / "plan.json", environment_path=tmp_path / "env.json",
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
        max_provider_calls_per_cycle=1,
        max_slots_per_cycle=1,
    )
    environment = EnvironmentSnapshot(
        ssn=100,
        source="fixture",
        source_version="fixture-v1",
        observed_at_utc=datetime(2026, 10, 1, tzinfo=UTC),
        captured_at_utc=local_now.astimezone(UTC),
    )
    plan_path = tmp_path / "plan.json"
    environment_path = tmp_path / "environment.json"
    plan_path.write_text(plan.model_dump_json())
    environment_path.write_text(environment.model_dump_json())
    config = SamplingRuntime(
        process_enabled=True, scheduler_enabled=True, provider_enabled=True,
        database_path=tmp_path / "c4.sqlite", plan_path=plan_path,
        environment_path=environment_path,
    )

    class NoCallProvider:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def predict(self, request: object, *, timeout_s: float) -> object:
            raise AssertionError("provider not needed to verify scheduled UTC day")

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
        max_provider_calls_per_cycle=1, max_provider_calls_per_day=1,
        max_slots_per_cycle=1, max_attempts=1, provider_timeout_s=10,
    )
    environment = EnvironmentSnapshot(
        ssn=100, source="reviewed", source_version="release-1",
        observed_at_utc=datetime(2026, 3, 1, tzinfo=UTC), captured_at_utc=now,
    )
    database = tmp_path / "c4.sqlite"
    BaselineRepository(database).add_plan(plan)
    plan_path = tmp_path / "plan.json"
    environment_path = tmp_path / "environment.json"
    plan_path.write_text(plan.model_dump_json())
    environment_path.write_text(environment.model_dump_json())
    config = SamplingRuntime(
        process_enabled=True, scheduler_enabled=True, provider_enabled=True,
        database_path=database, plan_path=plan_path, environment_path=environment_path,
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
    with sqlite3.connect(backup) as db:
        assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
