"""Inspect the real process identity verifier with disposable /proc fixtures."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "deploy/rolling-thunder-recovery-inspect.py"
SPEC = importlib.util.spec_from_file_location("rt_stab06f_process_inspector", SOURCE)
assert SPEC and SPEC.loader
inspector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(inspector)


def _fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    proc = tmp_path / "proc"
    proc.mkdir()
    child = proc / "1234"
    child.mkdir()
    (child / "cmdline").write_bytes(b"/usr/bin/python3\0/home/geoff/venv/bin/rolling-thunder-ui\0")
    (child / "cgroup").write_text("0::/system.slice/rolling-thunder.service\n", encoding="utf-8")
    monkeypatch.setattr(
        inspector.pwd, "getpwnam", lambda _user: SimpleNamespace(pw_uid=os.getuid())
    )
    monkeypatch.setattr(
        inspector,
        "_run",
        lambda *_args: (
            "ActiveState=active\nMainPID=1234\nControlGroup=/system.slice/rolling-thunder.service\nUser=geoff"
        ),
    )
    return proc


def test_expected_single_service_process_but_no_heartbeat_is_unverified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    proc = _fixture(tmp_path, monkeypatch)
    report = inspector._service_evidence(proc=proc, expected_user="geoff")
    assert report["state"] == "single_expected_service_process"
    assert report["responsiveness"] == "unverified"


def test_mismatched_cgroup_refuses_healthy_process_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    proc = _fixture(tmp_path, monkeypatch)
    (proc / "1234/cgroup").write_text("0::/user.slice/other\n", encoding="utf-8")
    assert inspector._service_evidence(proc=proc, expected_user="geoff")["state"] == "unverified"


def test_duplicate_dashboard_refuses_singleton_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    proc = _fixture(tmp_path, monkeypatch)
    second = proc / "2345"
    second.mkdir()
    (second / "cmdline").write_bytes(b"/home/geoff/venv/bin/rolling-thunder-ui\0")
    assert inspector._service_evidence(proc=proc, expected_user="geoff")["state"] == "unverified"


def test_wrong_main_pid_refuses_claim(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    proc = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(
        inspector,
        "_run",
        lambda *_args: (
            "ActiveState=active\nMainPID=9999\nControlGroup=/system.slice/rolling-thunder.service\nUser=geoff"
        ),
    )
    assert inspector._service_evidence(proc=proc, expected_user="geoff")["state"] == "unverified"
