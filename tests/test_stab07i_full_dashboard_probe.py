"""Fail-closed acceptance for full mock dashboard lifecycle evidence."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

DEPLOY = Path(__file__).resolve().parents[1] / "deploy"
SPEC = importlib.util.spec_from_file_location(
    "rt_stab07i_dashboard_runner", DEPLOY / "rolling-thunder-arm64-dashboard-runner.py"
)
assert SPEC and SPEC.loader
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def _report() -> dict[str, object]:
    return {
        "mode": "normal",
        "return_code": 0,
        "root_created": True,
        "tk_ready": True,
        "sent_sigterm": True,
        "after_close": True,
        "database_exists": True,
        "only_loopback": True,
        "physical_radio_tested": False,
        "production_ready": False,
        "runtime_started": True,
        "runtime_closed": True,
        "mock_radio": True,
        "mock_gps": True,
        "refresh_callbacks": 2,
        "widget_count": 5,
        "mutation_attempted": True,
        "mutation_accepted": False,
        "pending_callsign_after_mutation": "K1TEST",
        "close_worker_count": 1,
        "close_request_count": 2,
        "fixture_preserved": True,
        "backup_fixture_preserved": True,
        "sqlite_integrity": "ok",
        "sqlite_quick_check": "ok",
        "backup_integrity": "ok",
    }


def _output() -> str:
    return (
        "RT_SHUTDOWN phase=close_requested\n"
        "RT_SHUTDOWN phase=worker_start\n"
        "RT_SHUTDOWN phase=cleanup_start\n"
        "RT_SHUTDOWN phase=worker_end\n"
        "RT_SHUTDOWN phase=destroy_root\n"
        "RT_RUNTIME_SHUTDOWN phase=step_end step='radio polling'\n"
        "RT_RUNTIME_SHUTDOWN phase=step_start step='radio disconnect'\n"
        "RT_RUNTIME_SHUTDOWN phase=step_end step='operator preferences drain'\n"
        "RT_RUNTIME_SHUTDOWN phase=step_start step='operator preferences'\n"
    )


def test_complete_mock_dashboard_event_evidence_is_accepted_offline() -> None:
    assert runner.validate_result(_report(), _output())


@pytest.mark.parametrize(
    "change",
    (
        {"return_code": 3},
        {"root_created": False},
        {"tk_ready": False},
        {"sent_sigterm": False},
        {"after_close": False},
        {"database_exists": False},
        {"only_loopback": False},
        {"physical_radio_tested": True},
        {"production_ready": True},
        {"runtime_started": False},
        {"runtime_closed": False},
        {"mock_radio": False},
        {"mock_gps": False},
        {"refresh_callbacks": 0},
        {"widget_count": 0},
        {"mutation_accepted": True},
        {"pending_callsign_after_mutation": ""},
        {"close_worker_count": 2},
        {"close_request_count": 1},
        {"fixture_preserved": False},
        {"backup_fixture_preserved": False},
        {"sqlite_integrity": "corrupt"},
    ),
)
def test_false_readiness_or_production_claim_rejected(change: dict[str, object]) -> None:
    report = _report()
    report.update(change)
    assert not runner.validate_result(report, _output())


@pytest.mark.parametrize(
    "bad_output",
    (
        "RT_SHUTDOWN phase=close_requested\nRT_SHUTDOWN phase=cleanup_start",
        _output() + "\nRT_SHUTDOWN phase=worker_end",
        _output() + "\nRT_SHUTDOWN phase=step_end result=error",
        _output() + "\nRolling Thunder shutdown error: queued preferences",
        _output().replace(
            "RT_RUNTIME_SHUTDOWN phase=step_end step='radio polling'\n"
            "RT_RUNTIME_SHUTDOWN phase=step_start step='radio disconnect'",
            "RT_RUNTIME_SHUTDOWN phase=step_start step='radio disconnect'\n"
            "RT_RUNTIME_SHUTDOWN phase=step_end step='radio polling'",
        ),
    ),
)
def test_incomplete_duplicate_error_or_misordered_shutdown_refused(
    bad_output: str,
) -> None:
    assert not runner.validate_result(_report(), bad_output)


def test_cleanup_exception_is_a_refused_shutdown_with_preserved_data() -> None:
    report = _report()
    report.update(mode="cleanup-failure", return_code=4)
    report.pop("tk_ready")
    output = _output() + "Rolling Thunder shutdown error: mock cleanup failure"
    assert runner.validate_result(report, output, mode="cleanup-failure")
    assert not runner.validate_result(dict(report, return_code=0), output, mode="cleanup-failure")


def test_stale_heartbeat_refuses_readiness_but_closes_cleanly() -> None:
    report = _report()
    report.update(
        mode="missing-heartbeat",
        tk_ready=False,
        readiness_refused=True,
    )
    assert runner.validate_result(
        report, "RT_SHUTDOWN phase=destroy_root", mode="missing-heartbeat"
    )
    assert not runner.validate_result(
        dict(report, readiness_refused=False),
        "RT_SHUTDOWN phase=destroy_root",
        mode="missing-heartbeat",
    )


def test_blocked_shutdown_worker_is_an_explicit_refusal() -> None:
    report = {
        "mode": "blocked-worker",
        "expected_refusal": True,
        "production_ready": False,
        "physical_radio_tested": False,
    }
    output = (
        "RT_SHUTDOWN phase=worker_start\n"
        "RT_SHUTDOWN phase=step_start step='OHGO panel'\n"
        "RT_TEST_BLOCKED_WORKER phase=cleanup_started\n"
        "RT_DASHBOARD_REFUSAL blocked_shutdown_worker"
    )
    assert runner.validate_result(report, output, mode="blocked-worker")
    assert not runner.validate_result(
        dict(report, expected_refusal=False), output, mode="blocked-worker"
    )
    assert not runner.validate_result(
        report, output + "\\nRT_SHUTDOWN phase=worker_end", mode="blocked-worker"
    )


def test_reviewed_probe_is_never_a_general_dashboard_launcher() -> None:
    """Test program must disable real radio, speech, transmit, and networking."""
    contents = (DEPLOY / "rolling-thunder-arm64-dashboard-probe.py").read_text()
    assert "ui_main.run_dashboard" in contents
    assert '"radio_mode": "mock"' in contents
    assert '"gps_mode": "mock"' in contents
    assert '"enabled": False' in contents
    assert "XDG_RUNTIME_DIR" in contents
    assert 'os.environ.get("DISPLAY") != ":95"' in contents
    assert "os.kill" in contents
    assert "data/rolling-thunder.db" not in contents
    assert "rolling_thunder_deploy" not in contents


def test_mock_startup_failure_requires_runtime_rollback_and_no_ui() -> None:
    report = _report()
    report.update(
        mode="startup-failure",
        return_code=3,
        root_created=False,
        tk_ready=False,
        sent_sigterm=False,
    )
    assert runner.validate_result(
        report, "Rolling Thunder startup error: injected", mode="startup-failure"
    )
    assert not runner.validate_result(
        dict(report, runtime_closed=False),
        "Rolling Thunder startup error: injected",
        mode="startup-failure",
    )
    assert not runner.validate_result(
        dict(report, production_ready=True),
        "Rolling Thunder startup error: injected",
        mode="startup-failure",
    )
    assert not runner.validate_result(report, "silently ignored error", mode="startup-failure")


def test_unsupported_test_mode_is_not_accepted() -> None:
    assert not runner.validate_result(_report(), _output(), mode="live-radio")
