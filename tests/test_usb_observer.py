"""Offline regression checks for the independent read-only USB observer."""

import importlib.util
import json
import subprocess
from pathlib import Path
from unittest.mock import Mock

MODULE = Path(__file__).resolve().parents[1] / "deploy/diagnostics/rt-usb-observer.py"


def load_observer():
    """Load observer without starting its infinite sampling loop."""
    spec = importlib.util.spec_from_file_location("rt_usb_observer", MODULE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_run_bounds_read_only_command(monkeypatch):
    """Only command output is returned, capped at 12k and 3s timeout."""
    observer = load_observer()
    called = Mock(return_value=subprocess.CompletedProcess(["lsusb", "-t"], 0, "x" * 20000, ""))
    monkeypatch.setattr(observer.subprocess, "run", called)
    assert observer.run("lsusb", "-t") == "x" * 12000
    called.assert_called_once_with(("lsusb", "-t"), capture_output=True, text=True, timeout=3, check=False)


def test_run_fails_closed(monkeypatch):
    """Missing commands, timeouts and failed exits do not crash collection."""
    observer = load_observer()
    monkeypatch.setattr(observer.subprocess, "run", Mock(side_effect=FileNotFoundError))
    assert observer.run("vcgencmd", "get_throttled") == "unavailable"
    monkeypatch.setattr(observer.subprocess, "run", Mock(side_effect=subprocess.TimeoutExpired("lsusb", 3)))
    assert observer.run("lsusb", "-t") == "unavailable"
    monkeypatch.setattr(
        observer.subprocess, "run", Mock(return_value=subprocess.CompletedProcess(["lsusb"], 1, "", "failure"))
    )
    assert observer.run("lsusb", "-t") == "unavailable"


def test_record_jsonl_and_rotation(tmp_path):
    """Records have UTC timestamps and bounded local file storage."""
    observer = load_observer()
    logger = observer.configure_logger(tmp_path)
    try:
        observer.record(logger, "usb_topology_change", {"usb_tree": "test", "serial": {}})
        for handler in logger.handlers:
            handler.flush()
        data = json.loads((tmp_path / "usb-events.jsonl").read_text().splitlines()[-1])
        assert data["event"] == "usb_topology_change"
        assert data["time_utc"].endswith("+00:00")
        assert logger.handlers[-1].maxBytes == 10_000_000
        assert logger.handlers[-1].backupCount == 5
    finally:
        for handler in list(logger.handlers):
            handler.close()
            logger.removeHandler(handler)
