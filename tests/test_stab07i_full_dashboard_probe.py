"""Fail-closed acceptance for a full mock dashboard without actual radio startup."""

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
    }


def _output() -> str:
    return (
        "RT_SHUTDOWN phase=close_requested\n"
        "RT_SHUTDOWN phase=worker_start\n"
        "RT_SHUTDOWN phase=cleanup_start\n"
        "RT_SHUTDOWN phase=worker_end\n"
        "RT_SHUTDOWN phase=destroy_root"
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
    ),
)
def test_incomplete_duplicate_or_error_shutdown_refused(bad_output: str) -> None:
    assert not runner.validate_result(_report(), bad_output)


def test_reviewed_probe_is_never_a_general_dashboard_launcher() -> None:
    """Test program must disable real radio, speech, transmit, and networking."""
    contents = (DEPLOY / "rolling-thunder-arm64-dashboard-probe.py").read_text()
    assert "ui_main.run_dashboard" in contents
    assert '"radio_mode": "mock"' in contents
    assert '"gps_mode": "mock"' in contents
    assert '"enabled": False' in contents
    assert "XDG_RUNTIME_DIR" in contents
    assert "test Xvfb" in contents
    assert "os.kill" in contents
    assert "data/rolling-thunder.db" not in contents
    assert "rolling_thunder_deploy" not in contents


def test_mock_startup_failure_requires_radio_rollback_and_no_ui() -> None:
    report = _report()
    report.update(
        mode="startup-failure",
        return_code=3,
        root_created=False,
        tk_ready=False,
        sent_sigterm=False,
        rollback_disconnected=True,
    )
    assert runner.validate_result(
        report, "Rolling Thunder startup error: injected", mode="startup-failure"
    )
    assert not runner.validate_result(
        dict(report, rollback_disconnected=False),
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


def test_navigation_mode_requires_real_ordered_context_dispatch() -> None:
    """Tk heartbeat alone cannot certify keyboard/navigation responsiveness."""
    valid = _report()
    valid.update(mode="navigation", navigation_responsive=True,
                 navigation_events=["dx", "browse", "pota"])
    assert runner.validate_result(valid, _output(), mode="navigation")
    for bad in ([], ["dx", "pota"], ["dx", "browse", "dx"]):
        assert not runner.validate_result(
            dict(valid, navigation_events=bad), _output(), mode="navigation"
        )
    assert not runner.validate_result(
        dict(valid, navigation_responsive=False), _output(), mode="navigation"
    )
