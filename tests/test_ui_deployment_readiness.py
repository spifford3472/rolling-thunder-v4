"""Deterministic UI heartbeat and supervised deployment-readiness regressions."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path

import pytest

from rolling_thunder import deployment_readiness, ui_readiness


class FakeTkScheduler:
    """Collect Tk callbacks without a display or a running radio."""

    def __init__(self) -> None:
        self.pending: list[tuple[int, Callable[[], None]]] = []

    def after(self, delay_ms: int, callback: Callable[[], None]) -> str:
        self.pending.append((delay_ms, callback))
        return "scheduled"

    def run_next(self) -> None:
        _, callback = self.pending.pop(0)
        callback()


def _service(**changes: str) -> dict[str, str]:
    values = {
        "ActiveState": "active",
        "User": "geoff",
        "MainPID": "1234",
        "ControlGroup": "/system.slice/rolling-thunder.service",
    }
    values.update(changes)
    return values


def _proc(tmp_path: Path, *, pid: int = 1234) -> Path:
    root = tmp_path / "proc"
    process = root / str(pid)
    process.mkdir(parents=True)
    (process / "cgroup").write_text("0::/system.slice/rolling-thunder.service\n", encoding="utf-8")
    (process / "cmdline").write_bytes(b"/bin/python\0/home/geoff/.venv/bin/rolling-thunder-ui\0")
    (process / "stat").write_bytes(
        b"1234 (python with spaces) S " + b"0 " * 18 + b"987654 0\n"
    )
    boot = root / "sys/kernel/random/boot_id"
    boot.parent.mkdir(parents=True)
    boot.write_text("01234567-89ab-cdef-0123-456789abcdef\n", encoding="ascii")
    return root


def test_heartbeat_is_driven_by_tk_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A blocked UI callback queue cannot update the heartbeat in the background."""
    path = tmp_path / "ready.json"
    root = FakeTkScheduler()
    monkeypatch.setattr(ui_readiness.time, "time", lambda: 1000.0)
    ui_readiness.start_ui_heartbeat(root, path=path)
    assert root.pending[0][0] == 0
    assert not path.exists()
    root.run_next()
    assert ui_readiness.has_fresh_heartbeat(path, expected_pid=os.getpid(), now=1000.0)
    assert root.pending[0][0] == 1000
    assert not ui_readiness.has_fresh_heartbeat(path, expected_pid=os.getpid(), now=1006.0)


def test_heartbeat_path_requires_private_runtime_directory(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    assert ui_readiness.heartbeat_path(str(runtime)) == runtime / ui_readiness.HEARTBEAT_NAME
    runtime.chmod(0o777)
    assert ui_readiness.heartbeat_path(str(runtime)) is None


def test_release_sha_is_derived_only_from_sha_named_process_cwd(tmp_path: Path) -> None:
    root = tmp_path / "proc"
    process = root / "1234"
    process.mkdir(parents=True)
    releases = tmp_path / "releases"
    releases.mkdir()
    release_sha = "a" * 40
    release = releases / release_sha
    release.mkdir()
    (process / "cwd").symlink_to(release, target_is_directory=True)
    assert ui_readiness.process_release_sha(1234, proc_root=root) == release_sha
    (process / "cwd").unlink()
    mutable = tmp_path / "rolling-thunder-v4"
    mutable.mkdir()
    (process / "cwd").symlink_to(mutable, target_is_directory=True)
    assert ui_readiness.process_release_sha(1234, proc_root=root) is None


def test_heartbeat_rejects_foreign_pid_future_and_malformed(tmp_path: Path) -> None:
    path = tmp_path / "ready.json"
    ui_readiness.publish_heartbeat(
        path,
        pid=1234,
        now=100.0,
        process_boot_id="01234567-89ab-cdef-0123-456789abcdef",
        start_ticks=42,
        release_sha="a" * 40,
    )
    assert not ui_readiness.has_fresh_heartbeat(path, expected_pid=1235, now=101.0)
    assert not ui_readiness.has_fresh_heartbeat(path, expected_pid=1234, now=99.0)
    assert ui_readiness.has_fresh_heartbeat(path, expected_pid=1234, now=104.0)
    path.write_text(json.dumps({"pid": "1234", "time": 101.0}), encoding="utf-8")
    assert not ui_readiness.has_fresh_heartbeat(path, expected_pid=1234, now=102.0)


def test_heartbeat_rejects_symlinked_marker(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    target.write_text(
        json.dumps(
            {
                "pid": 1234,
                "time": 100.0,
                "boot_id": "01234567-89ab-cdef-0123-456789abcdef",
                "start_ticks": 42,
                "release_sha": None,
            }
        ),
        encoding="utf-8",
    )
    target.chmod(0o600)
    marker = tmp_path / "ready.json"
    marker.symlink_to(target)
    assert not ui_readiness.has_fresh_heartbeat(marker, expected_pid=1234, now=101.0)


def test_readiness_requires_supervised_pid_cgroup_command_and_tk_tick(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _proc(tmp_path)
    marker = tmp_path / "ready.json"
    monkeypatch.setattr(deployment_readiness, "read_system_service", _service)
    monkeypatch.setattr(deployment_readiness.time, "time", lambda: 1000.0)
    ui_readiness.publish_heartbeat(
        marker,
        pid=1234,
        now=999.0,
        process_boot_id="01234567-89ab-cdef-0123-456789abcdef",
        start_ticks=987654,
    )
    params = {"expected_uid": os.getuid(), "marker": marker, "proc_root": root}
    assert deployment_readiness.ready_once(**params)
    second = root / "4321"
    second.mkdir()
    (second / "cmdline").write_bytes(b"/usr/bin/python\0/opt/rolling-thunder-ui\0")
    assert not deployment_readiness.ready_once(**params), "duplicate dashboard must fail"
    (second / "cmdline").unlink()
    second.rmdir()
    for replacement in [
        _service(ActiveState="inactive"),
        _service(User="other"),
        _service(MainPID="0"),
        _service(ControlGroup="/wrong"),
        _service(MainPID="1235"),
    ]:
        monkeypatch.setattr(
            deployment_readiness, "read_system_service", lambda value=replacement: value
        )
        assert not deployment_readiness.ready_once(**params)
    monkeypatch.setattr(deployment_readiness, "read_system_service", _service)
    (root / "1234" / "cgroup").write_text("0::/user.slice/not-rolling-thunder\n", encoding="utf-8")
    assert not deployment_readiness.ready_once(**params)


@pytest.mark.parametrize(
    "field,value",
    [("start_ticks", 987653), ("boot_id", "fedcba98-7654-3210-fedc-ba9876543210")],
)
def test_readiness_rejects_reused_pid_or_different_boot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str, value: object
) -> None:
    root = _proc(tmp_path)
    marker = tmp_path / "ready.json"
    ui_readiness.publish_heartbeat(
        marker,
        pid=1234,
        now=999.0,
        process_boot_id="01234567-89ab-cdef-0123-456789abcdef",
        start_ticks=987654,
    )
    record = json.loads(marker.read_text(encoding="utf-8"))
    record[field] = value
    marker.write_text(json.dumps(record), encoding="utf-8")
    monkeypatch.setattr(deployment_readiness, "read_system_service", _service)
    monkeypatch.setattr(deployment_readiness.time, "time", lambda: 1000.0)
    params = {"expected_uid": os.getuid(), "marker": marker, "proc_root": root}
    assert not deployment_readiness.ready_once(**params)


def test_candidate_uses_bounded_app_readiness_not_systemctl_active() -> None:
    candidate = Path(__file__).resolve().parents[1] / "deploy/rolling-thunder-deploy.candidate"
    text = candidate.read_text(encoding="utf-8")
    assert "rolling_thunder.deployment_readiness --timeout 210" in text
    assert "sleep 3" not in text
