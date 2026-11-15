"""Run fixed hardware-disabled ARM64 Tk lifecycle scenarios under private Xvfb.

This is an isolated Forge test harness, NOT a release installer or a launcher
for ``run_dashboard``. No host package, device, database or network access.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import secrets
import signal
import stat
import subprocess
import time
from pathlib import Path
from typing import Any

MODES = ("normal", "runtime-error", "peripheral-error", "delayed-cleanup", "stalled-worker")
XVFB_SHA256 = "2011271eabcc2eb460e99995c5ef26e46633e87d04f570e305b62f178f7b452c"
XVFB_EXECUTABLE_SHA256 = "0081b27338b510ec5e2068a93c6db31480872de9bb082f347f3747ef1648e794"
DISPLAY_NO = 95
WORKSPACES_PARENT = Path("/home/rt-remote/workspaces")


class TkLifecycleError(ValueError):
    """The private display, fixed guest probe or lifecycle check was unsafe."""


def _sha256(path: Path) -> str:
    """Hash a regular, non-symlinked file before using it for a sandbox test."""
    if not path.is_file() or path.is_symlink():
        raise TkLifecycleError("missing or symlinked test program")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def _private_workspace(path: Path) -> None:
    """Refuse writeable public, special or privileged staging directories."""
    if (
        not path.is_absolute()
        or path.is_symlink()
        or not path.is_dir()
        or path.stat().st_uid != os.geteuid()
        or stat.S_IMODE(path.stat().st_mode) != 0o700
        or not path.resolve().is_relative_to(WORKSPACES_PARENT.resolve())
    ):
        raise TkLifecycleError("private Forge test workspace required")


def _load_sandbox() -> Any:
    """Reuse STAB-07G's fixed QEMU and private-root verifier."""
    source = Path(__file__).with_name("rolling-thunder-arm64-sandbox.py")
    spec = importlib.util.spec_from_file_location("rt_stab07h_isolated_runner", source)
    if spec is None or spec.loader is None:
        raise TkLifecycleError("existing ARM64 sandbox module unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def guest_command(root: Path, display: Path, mode: str) -> list[str]:
    """Construct a tightly scoped read-only ARM64 Tk guest command."""
    if mode not in MODES:
        raise TkLifecycleError("unsupported deterministic lifecycle mode")
    _private_workspace(display.parent)
    if display.name != "display":
        raise TkLifecycleError("unexpected Xvfb scratch path")
    _private_workspace(display)
    _private_workspace(display.parent / "scratch")
    previous = _load_sandbox()
    base = previous.command(root, "native-smoke")
    probe = root / "runtime/tk-lifecycle.py"
    expected = Path(__file__).with_name("rolling-thunder-arm64-tk-lifecycle.py")
    if _sha256(probe) != _sha256(expected):
        raise TkLifecycleError("guest lifecycle probe differs from reviewed source")
    if "--tmpfs" not in base or base[-3:] != ["-I", "-B", "/work/native-smoke.py"]:
        raise TkLifecycleError("unexpected STAB-07G sandbox command layout")
    idx = base.index("--tmpfs")
    base[idx : idx + 2] = [
        "--bind",
        str(display),
        "/tmp",
        "--bind",
        str(display.parent / "scratch"),
        "/test",
    ]
    marker = base.index("--chdir")
    base[marker:marker] = [
        "--setenv",
        "DISPLAY",
        f":{DISPLAY_NO}",
        "--setenv",
        "XAUTHORITY",
        "/tmp/Xauthority",
    ]
    base[-1] = "/work/tk-lifecycle.py"
    base += ["--mode", mode, "--scratch", "/test"]
    return base


def xvfb_command(display: Path) -> list[str]:
    """Start an isolated X-only UNIX socket, never TCP or host X11 access."""
    _private_workspace(display.parent)
    _private_workspace(display)
    server = display.parent / "tools/usr/bin/Xvfb"
    # The extracted binary is linked to the host's standard read-only libs.
    if not server.is_file() or server.is_symlink() or _sha256(server) != XVFB_EXECUTABLE_SHA256:
        raise TkLifecycleError("unverified private Xvfb executable")
    return [
        "/usr/bin/bwrap",
        "--unshare-user",
        "--unshare-net",
        "--unshare-pid",
        "--die-with-parent",
        "--ro-bind",
        "/usr",
        "/usr",
        "--ro-bind",
        "/bin",
        "/bin",
        "--ro-bind",
        "/lib",
        "/lib",
        "--ro-bind",
        "/lib64",
        "/lib64",
        "--ro-bind",
        "/etc",
        "/etc",
        "--ro-bind",
        str(display.parent / "tools"),
        "/opt",
        "--dir",
        "/var",
        "--dir",
        "/var/lib",
        "--tmpfs",
        "/var/lib/xkb",
        "--bind",
        str(display),
        "/tmp",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--clearenv",
        "--setenv",
        "PATH",
        "/usr/bin:/bin",
        "--",
        "/opt/usr/bin/Xvfb",
        f":{DISPLAY_NO}",
        "-auth",
        "/tmp/Xauthority",
        "-nolisten",
        "tcp",
        "-extension",
        "GLX",
        "-screen",
        "0",
        "1280x720x24",
    ]


def validate_report(record: dict[str, Any], mode: str) -> bool:
    """Never convert UI/cleanup evidence into release or RF approval."""
    if mode not in MODES:
        return False
    expected_errors = (
        ["application runtime"]
        if mode == "runtime-error"
        else ["peripheral_one"]
        if mode == "peripheral-error"
        else []
    )
    return (
        record.get("mode") == mode
        and record.get("readiness_fresh") is True
        and record.get("stale_heartbeat_rejected") is True
        and record.get("sigterm_received") is True
        and record.get("close_started") is True
        and record.get("close_finished") is True
        and record.get("close_worker_count") == 1
        and record.get("ordered_fake_steps") == ["runtime", "peripheral_one", "peripheral_two"]
        and record.get("cleanup_errors") == expected_errors
        and record.get("post_shutdown_operator_commands") == []
        and record.get("native_arm64_display") == f":{DISPLAY_NO}"
        and record.get("actual_tk_loop_entered") is True
        and record.get("no_real_dashboard_startup") is True
        and record.get("radio_or_ptt_tested") is False
        and record.get("production_ready") is False
        and record.get("loaded_python_bytes_independently_proven") is False
    )


def run(root: Path, display: Path, mode: str) -> dict[str, Any]:
    """Start/stop private display and bounded real Tk test, always clean up."""
    guest = guest_command(root, display, mode)
    server = xvfb_command(display)
    # Executable provenance is checked against the pinned Ubuntu Xvfb .deb
    # extracted into this workspace; no root apt install is performed.
    archive = next(iter(sorted((display.parent / "downloads").glob("xvfb_*.deb"))), None)
    if archive is None or _sha256(archive) != XVFB_SHA256:
        raise TkLifecycleError("unverified private Xvfb Debian archive")
    socket_path = display / ".X11-unix" / f"X{DISPLAY_NO}"
    if socket_path.exists():
        raise TkLifecycleError("refusing to reuse an existing test X server")
    auth = display / "Xauthority"
    if auth.exists():
        raise TkLifecycleError("refusing to reuse an existing Xauthority")
    with subprocess.Popen(
        ["/usr/bin/xauth", "-f", str(auth), "add", f":{DISPLAY_NO}", ".", secrets.token_hex(16)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    ) as authorization:
        authorization.communicate(timeout=5)
        if authorization.returncode != 0:
            raise TkLifecycleError("private Xauthority initialization failed")
    auth.chmod(0o600)
    server_proc: subprocess.Popen[bytes] | None = None
    try:
        server_proc = subprocess.Popen(
            server,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        deadline = time.monotonic() + 6.0
        while time.monotonic() < deadline:
            if socket_path.exists() and server_proc.poll() is None:
                break
            if server_proc.poll() is not None:
                raise TkLifecycleError("isolated Xvfb terminated before readiness")
            time.sleep(0.05)
        else:
            raise TkLifecycleError("isolated Xvfb socket was not ready")
        result = subprocess.run(guest, capture_output=True, text=True, timeout=150, check=False)
        if result.returncode != 0:
            raise TkLifecycleError("guest lifecycle reported incomplete or failure")
        lines = [
            line.removeprefix("RT_ARM64_LIFECYCLE ")
            for line in result.stdout.splitlines()
            if line.startswith("RT_ARM64_LIFECYCLE ")
        ]
        if len(lines) != 1:
            raise TkLifecycleError("guest lifecycle evidence absent or ambiguous")
        record = json.loads(lines[0])
        if not isinstance(record, dict) or not validate_report(record, mode):
            raise TkLifecycleError("guest lifecycle evidence did not meet offline acceptance")
        return record
    except subprocess.TimeoutExpired as exc:
        raise TkLifecycleError("lifecycle test exceeded bounded timeout") from exc
    finally:
        if server_proc is not None and server_proc.poll() is None:
            try:
                os.killpg(server_proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                server_proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(server_proc.pid, signal.SIGKILL)
                server_proc.wait(timeout=3)
        # Xvfb sometimes leaves a socket inode and .X95-lock after exit.
        # Remove only artifacts created under this private workspace by the
        # process we launched, after the process group has terminated.
        if server_proc is not None and server_proc.poll() is not None:
            for residue in (
                socket_path,
                display / f".X{DISPLAY_NO}-lock",
            ):
                if residue.is_symlink():
                    continue
                try:
                    info = residue.lstat()
                except FileNotFoundError:
                    continue
                if info.st_uid == os.geteuid() and (
                    stat.S_ISSOCK(info.st_mode) or stat.S_ISREG(info.st_mode)
                ):
                    residue.unlink()
        auth.unlink(missing_ok=True)


def main() -> int:
    """A test success does not attest production readiness."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sandbox", required=True, type=Path)
    parser.add_argument("--display", required=True, type=Path)
    parser.add_argument("--mode", required=True, choices=MODES)
    args = parser.parse_args()
    try:
        record = run(args.sandbox, args.display, args.mode)
        print(json.dumps(record, sort_keys=True))
        return 0
    except (OSError, ValueError) as exc:
        parser.exit(75, f"ARM64 TK LIFECYCLE REFUSED: {type(exc).__name__}: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
