from datetime import UTC, datetime
from pathlib import Path

import pytest

from rolling_thunder.forge_voacap_baseline_main import (
    LocalVoacapProvider,
    SamplingRuntime,
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
