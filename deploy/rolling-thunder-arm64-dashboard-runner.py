"""Run real dashboard composition only with mock radio/GPS in isolated ARM64.

No production deploy, no host X11 display, no network namespace, no radio USB.
This uses STAB-07H's private Xvfb command and STAB-07G's QEMU sandbox.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import secrets
import signal
import subprocess
import time
from pathlib import Path
from typing import Any


class DashboardProbeError(ValueError):
    """The full mock dashboard did not meet bounded safe acceptance."""


def _module(name: str, path: Path) -> Any:
    """Import the local reviewed runner, never from Python's global path."""
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise DashboardProbeError("missing pinned local runner")
    item = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(item)
    return item


MODES = (
    "normal",
    "startup-failure",
    "cleanup-failure",
    "missing-heartbeat",
    "blocked-worker",
    "navigation",
)


def make_guest(root: Path, display: Path, *, mode: str = "normal") -> list[str]:
    """Replace STAB-07H's mock-only guest with the reviewed real mock dashboard."""
    if mode not in MODES:
        raise DashboardProbeError("unsupported full-dashboard fake-hardware test mode")
    tk_runner = _module(
        "rt_stab07i_tk_runner", Path(__file__).with_name("rolling-thunder-arm64-tk-runner.py")
    )
    cmd = tk_runner.guest_command(root, display, "normal")
    expected = Path(__file__).with_name("rolling-thunder-arm64-dashboard-probe.py")
    guest = root / "runtime/dashboard-probe.py"
    if guest.is_symlink() or not guest.is_file():
        raise DashboardProbeError("missing private dashboard probe")
    if (
        hashlib.sha256(expected.read_bytes()).digest()
        != hashlib.sha256(guest.read_bytes()).digest()
    ):
        raise DashboardProbeError("guest dashboard probe differs from reviewed code")
    if cmd[-5:] != ["/work/tk-lifecycle.py", "--mode", "normal", "--scratch", "/test"]:
        raise DashboardProbeError("unexpected base guest command")
    source = Path(__file__).resolve().parents[1] / "src/rolling_thunder"
    repository = Path(__file__).resolve().parents[1]
    if (
        source.is_symlink()
        or not source.is_dir()
        or not source.resolve().is_relative_to(repository.resolve())
    ):
        raise DashboardProbeError("reviewed application source tree is unavailable")
    source_mount = root / "runtime/rolling_thunder"
    if source_mount.is_symlink():
        raise DashboardProbeError("application source mount point is unsafe")
    source_mount.mkdir(mode=0o700, exist_ok=True)
    if source_mount.stat().st_mode & 0o077:
        raise DashboardProbeError("application source mount point is not private")
    marker = cmd.index("--proc")
    cmd[marker:marker] = ["--ro-bind", str(source), "/work/rolling_thunder"]
    cmd[-5:] = ["/work/dashboard-probe.py", "--mode", mode]
    if "--unshare-net" not in cmd or "--dev" not in cmd or "--clearenv" not in cmd:
        raise DashboardProbeError("network or hardware namespace isolation missing")
    return cmd


def validate_result(report: dict[str, Any], output: str, *, mode: str = "normal") -> bool:
    """An application exit is not proof of safe physical RF or production launch."""
    if mode == "startup-failure":
        return (
            report.get("mode") == mode
            and report.get("return_code") == 3
            and report.get("root_created") is False
            and report.get("runtime_closed") is True
            and report.get("only_loopback") is True
            and report.get("production_ready") is False
            and report.get("physical_radio_tested") is False
            and "Rolling Thunder startup error" in output
        )
    if mode == "blocked-worker":
        return (
            report.get("mode") == mode
            and report.get("expected_refusal") is True
            and report.get("production_ready") is False
            and report.get("physical_radio_tested") is False
            and "RT_TEST_BLOCKED_WORKER phase=cleanup_started" in output
            and "RT_DASHBOARD_REFUSAL blocked_shutdown_worker" in output
            and "RT_SHUTDOWN phase=worker_start" in output
            and "RT_SHUTDOWN phase=worker_end" not in output
            and "RT_SHUTDOWN phase=destroy_root" not in output
        )
    if mode not in ("normal", "cleanup-failure", "missing-heartbeat", "navigation"):
        return False
    common = (
        report.get("mode") == mode
        and report.get("after_close") is True
        and report.get("root_created") is True
        and report.get("sent_sigterm") is True
        and report.get("only_loopback") is True
        and report.get("production_ready") is False
        and report.get("physical_radio_tested") is False
    )
    if mode == "missing-heartbeat":
        return (
            common
            and report.get("return_code") == 0
            and report.get("tk_ready") is False
            and report.get("readiness_refused") is True
            and "RT_SHUTDOWN phase=destroy_root" in output
        )
    needed_phases = (
        "RT_SHUTDOWN phase=close_requested",
        "RT_SHUTDOWN phase=worker_start",
        "RT_SHUTDOWN phase=cleanup_start",
        "RT_SHUTDOWN phase=worker_end",
        "RT_SHUTDOWN phase=destroy_root",
    )
    if mode == "cleanup-failure":
        return (
            common
            and report.get("return_code") == 4
            and report.get("runtime_closed") is True
            and report.get("sqlite_integrity") == "ok"
            and "Rolling Thunder shutdown error" in output
            and all(output.count(phase) == 1 for phase in needed_phases)
        )
    return (
        common
        and (mode != "navigation" or (
            report.get("navigation_responsive") is True
            and report.get("navigation_events") == ["dx", "browse", "pota"]
        ))
        and report.get("return_code") == 0
        and report.get("tk_ready") is True
        and report.get("runtime_started") is True
        and report.get("runtime_closed") is True
        and report.get("database_exists") is True
        and report.get("mock_radio") is True
        and report.get("mock_gps") is True
        and report.get("refresh_callbacks", 0) >= 2
        and report.get("widget_count", 0) > 0
        and report.get("mutation_attempted") is True
        and report.get("mutation_accepted") is False
        and report.get("pending_callsign_after_mutation") == "K1TEST"
        and report.get("close_worker_count") == 1
        and report.get("close_request_count", 0) >= 2
        and report.get("fixture_preserved") is True
        and report.get("backup_fixture_preserved") is True
        and report.get("sqlite_integrity") == "ok"
        and report.get("sqlite_quick_check") == "ok"
        and report.get("backup_integrity") == "ok"
        and all(output.count(phase) == 1 for phase in needed_phases)
        and "RT_RUNTIME_SHUTDOWN phase=step_end step='radio polling'" in output
        and "RT_RUNTIME_SHUTDOWN phase=step_start step='radio disconnect'" in output
        and "RT_RUNTIME_SHUTDOWN phase=step_end step='operator preferences drain'" in output
        and "RT_RUNTIME_SHUTDOWN phase=step_start step='operator preferences'" in output
        and output.index("RT_RUNTIME_SHUTDOWN phase=step_end step='radio polling'")
        < output.index("RT_RUNTIME_SHUTDOWN phase=step_start step='radio disconnect'")
        and output.index("RT_RUNTIME_SHUTDOWN phase=step_end step='operator preferences drain'")
        < output.index("RT_RUNTIME_SHUTDOWN phase=step_start step='operator preferences'")
        and "result=error" not in output
        and "Rolling Thunder shutdown error" not in output
    )


def run(root: Path, display: Path, *, mode: str = "normal") -> dict[str, Any]:
    """Execute one isolated app process with a newly created authenticated Xvfb."""
    tk_runner = _module(
        "rt_stab07i_tk_server", Path(__file__).with_name("rolling-thunder-arm64-tk-runner.py")
    )
    cmd = make_guest(root, display, mode=mode)
    server = tk_runner.xvfb_command(display)
    package = next(iter(sorted((display.parent / "downloads").glob("xvfb_*.deb"))), None)
    if package is None or tk_runner._sha256(package) != tk_runner.XVFB_SHA256:
        raise DashboardProbeError("unverified private Xvfb archive")
    socket = display / ".X11-unix" / "X95"
    auth = display / "Xauthority"
    if socket.exists() or auth.exists():
        raise DashboardProbeError("refusing to share or reuse a display")
    # Never reuse a database or readiness marker from a prior trial.
    scratch = display.parent / "scratch"
    if (scratch / "scratch-dashboard.sqlite3").exists():
        raise DashboardProbeError("refusing to overwrite disposable test DB")
    subprocess.run(
        ["/usr/bin/xauth", "-f", str(auth), "add", ":95", ".", secrets.token_hex(16)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
        timeout=5,
    )
    auth.chmod(0o600)
    process: subprocess.Popen[bytes] | None = None
    try:
        process = subprocess.Popen(
            server, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True
        )
        for _ in range(120):
            if socket.exists() and process.poll() is None:
                break
            if process.poll() is not None:
                raise DashboardProbeError("Xvfb exited before readiness")
            time.sleep(0.05)
        else:
            raise DashboardProbeError("Xvfb not ready")
        completed = subprocess.run(cmd, capture_output=True, text=True, timeout=150, check=False)
        markers = [
            line.split("RT_DASHBOARD_PROBE ", 1)[1]
            for line in completed.stdout.splitlines()
            if line.startswith("RT_DASHBOARD_PROBE ")
        ]
        expected_status = 0 if mode in ("normal", "startup-failure", "navigation") else 75
        combined_output = completed.stdout + "\n" + completed.stderr
        if mode == "blocked-worker":
            refusal_report = {
                "mode": mode,
                "expected_refusal": True,
                "production_ready": False,
                "physical_radio_tested": False,
            }
            if completed.returncode != 75 or markers or not validate_result(
                refusal_report, combined_output, mode=mode
            ):
                raise DashboardProbeError(
                    f"blocked worker did not fail closed (status={completed.returncode}; "
                    f"output={combined_output[-6000:]!r})"
                )
            return refusal_report
        if completed.returncode != expected_status or len(markers) != 1:
            evidence = (completed.stdout + "\n" + completed.stderr)[-6000:]
            raise DashboardProbeError(
                f"dashboard exited abnormally or omitted evidence "
                f"(status={completed.returncode}; expected={expected_status}; output={evidence!r})"
            )
        report = json.loads(markers[0])
        combined_output = completed.stdout + "\n" + completed.stderr
        if not isinstance(report, dict) or not validate_result(report, combined_output, mode=mode):
            evidence = combined_output[-6000:]
            raise DashboardProbeError(
                f"dashboard startup/shutdown evidence refused (mode={mode}; report={report!r}; "
                f"output={evidence!r})"
            )
        return report
    except subprocess.TimeoutExpired as exc:
        raise DashboardProbeError("dashboard lifecycle timed out") from exc
    finally:
        if process is not None and process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=3)
        auth.unlink(missing_ok=True)
        if process is not None and process.poll() is not None:
            for path in (socket, display / ".X95-lock"):
                if path.exists() and not path.is_symlink() and path.lstat().st_uid == os.geteuid():
                    path.unlink()


def main() -> int:
    """Only the fixed fake-radio full UI test is available."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sandbox", type=Path, required=True)
    parser.add_argument("--display", type=Path, required=True)
    parser.add_argument("--mode", choices=MODES, default="normal")
    arguments = parser.parse_args()
    try:
        print(
            json.dumps(
                run(arguments.sandbox, arguments.display, mode=arguments.mode), sort_keys=True
            )
        )
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        parser.exit(75, f"ARM64 FULL DASHBOARD REFUSED: {type(exc).__name__}: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
