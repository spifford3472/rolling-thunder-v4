"""STAB-07I: the runtime alone drains preferences, after radio release."""

from __future__ import annotations

from pathlib import Path

import pytest

from rolling_thunder.application_runtime import ApplicationRuntime
from rolling_thunder.config import ApplicationConfig


def _mock_runtime(tmp_path: Path) -> ApplicationRuntime:
    """Construct only disposable SQLite and mock-radio test services."""
    config = ApplicationConfig.model_validate(
        {
            "operator": {"callsign": "KI5VNB", "home_grid": "EM79xm"},
            "hardware": {"mock": True},
            "storage": {"database_path": str(tmp_path / "prefs-test.sqlite3")},
            "pota_map": {"enabled": False},
        }
    )
    runtime = ApplicationRuntime.from_config(config)
    runtime.start()
    return runtime


def test_runtime_drains_once_before_owned_executor_stops_and_after_radio(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No second UI flush can inspect the preference queue after runtime.stop."""
    runtime = _mock_runtime(tmp_path)
    prefs = runtime.operator_preferences
    assert prefs is not None
    events: list[str] = []
    original_disconnect = runtime.radio.disconnect
    original_flush = prefs.flush
    original_stop = prefs.stop

    def disconnect() -> object:
        events.append("radio disconnect")
        return original_disconnect()

    def drain(timeout_s: float) -> bool:
        events.append("preferences drain")
        assert timeout_s == 3.0
        return original_flush(timeout_s)

    def stop() -> None:
        events.append("preferences stop")
        original_stop()

    monkeypatch.setattr(runtime.radio, "disconnect", disconnect)
    monkeypatch.setattr(prefs, "flush", drain)
    monkeypatch.setattr(prefs, "stop", stop)
    runtime.stop()
    assert events == ["radio disconnect", "preferences drain", "preferences stop"]


def test_preference_drain_failure_is_explicit_and_stop_still_occurs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed flush cannot be silently accepted as durable preferences."""
    runtime = _mock_runtime(tmp_path)
    prefs = runtime.operator_preferences
    assert prefs is not None
    events: list[str] = []
    original_stop = prefs.stop

    def failed_drain(_timeout_s: float) -> bool:
        events.append("drain failed")
        return False

    def stop() -> None:
        events.append("stop")
        original_stop()

    monkeypatch.setattr(prefs, "flush", failed_drain)
    monkeypatch.setattr(prefs, "stop", stop)
    with pytest.raises(ExceptionGroup, match="Rolling Thunder shutdown errors") as caught:
        runtime.stop()
    assert events == ["drain failed", "stop"]
    assert any(
        "queued operator preferences did not drain" in str(error)
        for error in caught.value.exceptions
    )


def test_ui_no_longer_attempts_second_flush_after_runtime_stop() -> None:
    """The entire shutdown ownership boundary is runtime, not the Tk UI."""
    source = (Path(__file__).resolve().parents[1] / "src/rolling_thunder/ui_main.py").read_text()
    assert '"operator preferences", drain_preferences' not in source
    assert "preference_service.flush(3.0)" not in source
