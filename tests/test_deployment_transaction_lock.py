"""Hardware-free transaction locking tests; never invoke the installed wrapper."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

LOCK_TOOL = Path(__file__).resolve().parents[1] / "deploy/rolling-thunder-deploy-lock"


def _call(lock: Path, *command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(LOCK_TOOL), str(lock), "--", *command],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_lock_survives_exec_and_refuses_overlapping_transaction(tmp_path: Path) -> None:
    """Concurrent deploy attempt must never reach its mutation command."""
    lock = tmp_path / "deployment.lock"
    started = tmp_path / "started"
    release = tmp_path / "release"
    worker = (
        "from pathlib import Path; import sys,time; "
        "Path(sys.argv[1]).touch(); "
        "deadline=time.monotonic()+5; "
        "exec('while not Path(sys.argv[2]).exists() and time.monotonic()<deadline: time.sleep(.01)')"
    )
    first = subprocess.Popen(
        [
            "bash",
            str(LOCK_TOOL),
            str(lock),
            "--",
            sys.executable,
            "-c",
            worker,
            str(started),
            str(release),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        import time

        deadline = time.monotonic() + 3
        while not started.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert started.exists(), "first transaction failed to start"
        marker = tmp_path / "second-mutated"
        second = _call(
            lock,
            sys.executable,
            "-c",
            "import pathlib,sys; pathlib.Path(sys.argv[1]).touch()",
            str(marker),
        )
        assert second.returncode == 75
        assert "already in progress" in second.stderr
        assert not marker.exists()
    finally:
        release.touch()
        first.communicate(timeout=6)
    assert first.returncode == 0
    third = _call(lock, sys.executable, "-c", "print('NEXT_TRANSACTION')")
    assert third.returncode == 0
    assert "NEXT_TRANSACTION" in third.stdout


def test_symlink_lock_refused_without_touching_target(tmp_path: Path) -> None:
    target = tmp_path / "preserve"
    target.write_text("keep", encoding="utf-8")
    lock = tmp_path / "lock"
    lock.symlink_to(target)
    result = _call(lock, sys.executable, "-c", "print('must not run')")
    assert result.returncode == 73
    assert target.read_text(encoding="utf-8") == "keep"
    assert "must not run" not in result.stdout


def test_missing_lock_parent_refused(tmp_path: Path) -> None:
    result = _call(tmp_path / "missing" / "lock", sys.executable, "-c", "print('bad')")
    assert result.returncode == 73
    assert "bad" not in result.stdout


def test_child_failure_propagates(tmp_path: Path) -> None:
    result = _call(tmp_path / "lock", sys.executable, "-c", "import sys; sys.exit(47)")
    assert result.returncode == 47
