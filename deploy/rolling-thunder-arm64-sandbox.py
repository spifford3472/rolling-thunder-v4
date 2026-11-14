"""Run read-only ARM64 checks with QEMU inside an unprivileged networkless sandbox.

This is a narrow *test runner*, not a generic command-execution service or a
production installer. It mounts only private test paths and never attaches the
station, host home directories, privileged sockets or radio devices.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
from pathlib import Path
from typing import Any

SANDBOX_PARENT = Path("/home/rt-remote/workspaces")
QEMU_SHA256 = "e4f8d99e9ff69c3cefffab71cee358ce2af1ecba1282d04c3eeb44ef76f5a71e"
ACTIONS = {"native-smoke", "pip-check"}


class SandboxError(ValueError):
    """A sandbox input, mount boundary or emulation contract is unsafe."""


def command(root: Path, action: str, *, allowed_parent: Path = SANDBOX_PARENT) -> list[str]:
    """Construct an explicit read-only, no-network sandbox command."""
    if action not in ACTIONS:
        raise SandboxError("unsupported offline ARM64 verification action")
    if (
        not root.is_absolute()
        or not root.is_dir()
        or root.is_symlink()
        or root.resolve() == Path("/")
        or not root.is_relative_to(allowed_parent)
        or not root.resolve().is_relative_to(allowed_parent.resolve())
    ):
        raise SandboxError("unapproved sandbox root")
    details = root.lstat()
    if details.st_uid != os.geteuid() or stat.S_IMODE(details.st_mode) != 0o700:
        raise SandboxError("sandbox root must be private and caller-owned")
    sysroot = root / "sysroot"
    runtime = root / "runtime"
    for item in (sysroot, runtime):
        if not item.is_dir() or item.is_symlink() or not item.resolve().is_relative_to(root):
            raise SandboxError("sandbox required directory missing or unsafe")
    qemu = sysroot / "usr/bin/qemu-aarch64-static"
    python = sysroot / "usr/bin/python3.13"
    if not qemu.is_file() or qemu.is_symlink() or not python.is_file() or python.is_symlink():
        raise SandboxError("emulator or ARM64 interpreter missing")
    if hashlib.sha256(qemu.read_bytes()).hexdigest() != QEMU_SHA256:
        raise SandboxError("unexpected QEMU static executable hash")
    with python.open("rb") as source:
        header = source.read(20)
    if (
        len(header) < 20
        or header[:6] != b"\x7fELF\x02\x01"
        or int.from_bytes(header[18:20], "little") != 183
    ):
        raise SandboxError("test interpreter is not AArch64 ELF64")
    venv = runtime / "venv/bin/python3.13"
    if not venv.is_symlink() or os.readlink(venv) != "/usr/bin/python3.13":
        raise SandboxError("expected isolated Python virtual environment missing")
    if action == "native-smoke" and not (runtime / "native-smoke.py").is_file():
        raise SandboxError("smoke probe missing from private test environment")
    script = ["/work/native-smoke.py"] if action == "native-smoke" else ["-m", "pip", "check"]
    return [
        "/usr/bin/bwrap",
        "--unshare-user",
        "--unshare-pid",
        "--unshare-net",
        "--die-with-parent",
        "--ro-bind",
        str(sysroot),
        "/",
        "--ro-bind",
        str(runtime),
        "/work",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--tmpfs",
        "/tmp",
        "--clearenv",
        "--setenv",
        "PATH",
        "/usr/bin:/bin",
        "--setenv",
        "HOME",
        "/tmp",
        "--setenv",
        "PIP_NO_INDEX",
        "1",
        "--chdir",
        "/work",
        "--",
        "/usr/bin/qemu-aarch64-static",
        "-L",
        "/",
        "/work/venv/bin/python3.13",
        "-I",
        "-B",
        *script,
    ]


def run(root: Path, action: str, *, allowed_parent: Path = SANDBOX_PARENT) -> dict[str, Any]:
    """Execute only approved offline tests, returning no production verdict."""
    invocation = command(root, action, allowed_parent=allowed_parent)
    try:
        completed = subprocess.run(
            invocation,
            check=False,
            text=True,
            capture_output=True,
            timeout=180,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SandboxError("isolated ARM64 smoke timed out or could not start") from exc
    if completed.returncode != 0:
        raise SandboxError("isolated ARM64 test failed (see private test log)")
    if action == "native-smoke":
        report = json.loads(completed.stdout)
        if (
            report.get("machine") != "aarch64"
            or report.get("python") != "3.13.5"
            or report.get("interfaces") != ["lo"]
            or report.get("radio_or_audio_devices_visible") is not False
            or report.get("import_tests_passed") is not True
            or report.get("ui_started") is not False
            or report.get("production_ready") is not False
        ):
            raise SandboxError("guest probe did not establish isolated import-only acceptance")
        return report
    if "No broken requirements found." not in completed.stdout:
        raise SandboxError("pip did not establish dependency-closure success")
    return {"state": "offline_arm64_dependencies_consistent", "production_ready": False}


def main() -> int:
    """Never expose arbitrary process or filesystem operations."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sandbox", required=True, type=Path)
    parser.add_argument("--action", choices=sorted(ACTIONS), required=True)
    opts = parser.parse_args()
    try:
        report = run(opts.sandbox, opts.action)
        print(json.dumps(report, sort_keys=True))
        return 0
    except (OSError, SandboxError, ValueError) as exc:
        parser.exit(75, f"OFFLINE ARM64 CHECK REFUSED: {type(exc).__name__}: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
