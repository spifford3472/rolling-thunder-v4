"""Isolated STAB-07 startup rollback regressions; never use a physical radio."""

from __future__ import annotations

from pathlib import Path

import pytest

from rolling_thunder.application_runtime import ApplicationRuntime
from rolling_thunder.config import ApplicationConfig
from rolling_thunder.domain import RadioConnectionState


def test_unexpected_service_start_exception_releases_mock_radio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-whitelisted worker exception must not strand a connected radio."""
    config = ApplicationConfig.model_validate(
        {
            "operator": {"callsign": "KI5VNB", "home_grid": "EM79xm"},
            "hardware": {"mock": True, "radio_mode": "mock", "gps_mode": "mock"},
            "storage": {"database_path": str(tmp_path / "startup.sqlite3")},
            "speech": {"enabled": False},
            "tron": {"enabled": False},
            "forge": {"enabled": False},
            "ft8": {"enabled": False},
            "pota_map": {"enabled": False},
        }
    )
    runtime = ApplicationRuntime.from_config(config)

    def fail_after_radio_connect() -> None:
        assert runtime.radio.get_state().connection_state is RadioConnectionState.CONNECTED
        raise LookupError("synthetic unexpected worker initialization failure")

    monkeypatch.setattr(runtime, "_start_remaining_services", fail_after_radio_connect)
    with pytest.raises(LookupError, match="synthetic unexpected"):
        runtime.start()
    assert runtime.radio.get_state().connection_state is RadioConnectionState.DISCONNECTED
    assert runtime._started is False


def test_startup_preserves_original_failure_when_rollback_reports_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A reported cleanup failure cannot erase the original startup cause."""
    config = ApplicationConfig.model_validate(
        {
            "operator": {"callsign": "KI5VNB", "home_grid": "EM79xm"},
            "hardware": {"mock": True},
            "storage": {"database_path": str(tmp_path / "rollback.sqlite3")},
            "pota_map": {"enabled": False},
        }
    )
    runtime = ApplicationRuntime.from_config(config)

    def fail_start() -> None:
        raise LookupError("initial synthetic failure")

    def fail_cleanup() -> None:
        raise RuntimeError("synthetic non-radio cleanup error")

    monkeypatch.setattr(runtime, "_start_remaining_services", fail_start)
    monkeypatch.setattr(runtime.pota_enrichment, "stop", fail_cleanup)
    with pytest.raises(LookupError, match="initial synthetic failure"):
        runtime.start()
    assert runtime.radio.get_state().connection_state is RadioConnectionState.DISCONNECTED
    assert "startup cleanup error" in capsys.readouterr().out


def test_polling_start_failure_after_connect_releases_mock_radio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Radio polling itself can fail after opening the mock radio."""
    config = ApplicationConfig.model_validate(
        {
            "operator": {"callsign": "KI5VNB", "home_grid": "EM79xm"},
            "hardware": {"mock": True},
            "storage": {"database_path": str(tmp_path / "polling.sqlite3")},
            "pota_map": {"enabled": False},
        }
    )
    runtime = ApplicationRuntime.from_config(config)
    original_start = runtime.polling.start

    def connect_then_fail() -> object:
        state = original_start()
        assert state.connection_state is RadioConnectionState.CONNECTED
        raise LookupError("synthetic polling failure after connect")

    monkeypatch.setattr(runtime.polling, "start", connect_then_fail)
    with pytest.raises(LookupError, match="synthetic polling failure"):
        runtime.start()
    assert runtime.radio.get_state().connection_state is RadioConnectionState.DISCONNECTED
    assert runtime._started is False
    assert runtime.polling.is_running is False
