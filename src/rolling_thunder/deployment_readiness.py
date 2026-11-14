"""Bounded read-only deployment verification; never uses CAT/PTT or hardware APIs."""

from __future__ import annotations

import argparse
import pwd
import subprocess
import sys
import time
from pathlib import Path

from rolling_thunder.ui_readiness import HEARTBEAT_NAME, has_fresh_heartbeat

SERVICE_NAME = "rolling-thunder.service"


def read_system_service(name: str = SERVICE_NAME) -> dict[str, str]:
    """Read the system manager explicitly; user service status is irrelevant."""
    output = subprocess.run(
        [
            "/usr/bin/systemctl",
            "show",
            name,
            "--no-pager",
            "-p",
            "ActiveState",
            "-p",
            "MainPID",
            "-p",
            "ControlGroup",
            "-p",
            "User",
        ],
        text=True,
        capture_output=True,
        check=True,
        timeout=3,
    ).stdout
    return dict(line.split("=", 1) for line in output.splitlines() if "=" in line)


def unique_dashboard_pid(proc_root: Path, *, uid: int, expected_pid: int) -> bool:
    """Refuse an unmanaged or duplicate same-user dashboard process."""
    matching: set[int] = set()
    for directory in proc_root.iterdir():
        if not directory.name.isdigit():
            continue
        try:
            if directory.stat().st_uid != uid:
                continue
            argv = directory.joinpath("cmdline").read_bytes().split(b"\0")
            if any(
                arg == b"rolling-thunder-ui" or arg.endswith(b"/rolling-thunder-ui") for arg in argv
            ):
                matching.add(int(directory.name))
        except (OSError, ValueError):
            continue  # Process can exit during read; identity is rechecked below.
    return matching == {expected_pid}


def ready_once(*, expected_uid: int, marker: Path, proc_root: Path = Path("/proc")) -> bool:
    """Require live service ownership and one recent Tk-thread heartbeat."""
    try:
        service = read_system_service()
        if service.get("ActiveState") != "active" or service.get("User") != "geoff":
            return False
        pid = int(service.get("MainPID", "0"))
        if pid <= 1 or service.get("ControlGroup") != "/system.slice/rolling-thunder.service":
            return False
        directory = proc_root / str(pid)
        if (
            directory.joinpath("cgroup").read_text(encoding="utf-8").strip()
            != "0::/system.slice/rolling-thunder.service"
        ):
            return False
        command_line = directory.joinpath("cmdline").read_bytes().replace(b"\0", b" ")
        if b"rolling-thunder-ui" not in command_line:
            return False
        if not unique_dashboard_pid(proc_root, uid=expected_uid, expected_pid=pid):
            return False
        return has_fresh_heartbeat(
            marker, expected_pid=pid, now=time.time(), expected_uid=expected_uid
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        return False


def main() -> int:
    """Return zero only after supervised, responsive Tk identity is verified."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=210.0)
    args = parser.parse_args()
    if not 1 <= args.timeout <= 300:
        parser.error("timeout must be between 1 and 300 seconds")
    identity = pwd.getpwnam("geoff")
    marker = Path(f"/run/user/{identity.pw_uid}") / HEARTBEAT_NAME
    deadline = time.monotonic() + args.timeout
    while True:
        if ready_once(expected_uid=identity.pw_uid, marker=marker):
            print("supervised_dashboard_responsive=yes")
            print("radio_ptt_state=not_independently_verified")
            return 0
        if time.monotonic() >= deadline:
            print(
                "ERROR: supervised dashboard did not become responsive within deadline",
                file=sys.stderr,
            )
            return 1
        time.sleep(min(1, max(0, deadline - time.monotonic())))


if __name__ == "__main__":
    raise SystemExit(main())
