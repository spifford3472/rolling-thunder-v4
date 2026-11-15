"""Run a real ARM64 Tk loop with production shutdown helpers and inert fakes.

This executable intentionally does NOT call run_dashboard(), start radio services,
operate a serial/CAT interface, or access a real QSO database. Used only inside
STAB-07H's separate unprivileged, no-network Xvfb/QEMU test sandbox.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import time
import tkinter as tk
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Any

from rolling_thunder.ui_main import (
    _request_close_once,
    _run_orderly_shutdown,
    _sigterm_close_handler,
)
from rolling_thunder.ui_readiness import (
    has_fresh_heartbeat,
    heartbeat_path,
    start_ui_heartbeat,
)

MODES = ("normal", "runtime-error", "peripheral-error", "delayed-cleanup", "stalled-worker")


def run(mode: str, *, scratch: Path) -> dict[str, Any]:
    """Exercise Tk heartbeat, SIGTERM handoff, one close, and ordered cleanup."""
    if mode not in MODES:
        raise ValueError("unsupported deterministic mock shutdown case")
    if scratch.is_symlink() or not scratch.is_dir() or scratch.stat().st_mode & 0o077:
        raise ValueError("private scratch directory required")
    if any(Path("/dev").glob("ttyUSB*")) or any(Path("/dev").glob("ttyACM*")):
        raise ValueError("radio device unexpectedly present")
    if os.environ.get("DISPLAY") != ":95":
        raise ValueError("only the dedicated test display may be used")

    # The isolated real Tk interpreter and actual production scheduling helpers
    # are exercised; fake resources have no radio, database, or device methods.
    root = tk.Tk()
    root.withdraw()
    window_count = len(root.winfo_children())
    requested = Event()
    started = Event()
    finished = Event()
    guard = Lock()
    steps: list[str] = []
    errors: list[str] = []
    readiness: list[bool] = []
    late_commands: list[str] = []
    worker_count: list[int] = []
    previous_handler = signal.signal(signal.SIGTERM, _sigterm_close_handler(requested))
    private_runtime = scratch / "runtime-uid"
    private_runtime.mkdir(mode=0o700, exist_ok=True)
    private_runtime.chmod(0o700)
    marker = heartbeat_path(str(private_runtime))
    if marker is None:
        raise RuntimeError("private heartbeat path unavailable")

    def fake_runtime_stop() -> None:
        steps.append("runtime")
        if mode == "runtime-error":
            raise RuntimeError("simulated runtime cleanup failure")

    def fake_cleanup_one() -> None:
        steps.append("peripheral_one")
        if mode == "delayed-cleanup":
            time.sleep(0.15)
        if mode == "stalled-worker":
            # Intentionally outlives the Tk-bound fail-safe. A daemon worker
            # must never produce a false completed/safe verdict.
            Event().wait(timeout=60.0)
        if mode == "peripheral-error":
            raise RuntimeError("simulated peripheral cleanup failure")

    def fake_cleanup_two() -> None:
        steps.append("peripheral_two")

    def close_worker() -> None:
        try:
            _run_orderly_shutdown(
                fake_runtime_stop,
                (("peripheral_one", fake_cleanup_one), ("peripheral_two", fake_cleanup_two)),
                errors,
            )
        finally:
            finished.set()

    def try_operator_command() -> None:
        # Models the already-existing operator command inhibition boundary.
        if not started.is_set():
            late_commands.append("accepted")

    def initiate_close() -> None:
        def launch() -> None:
            worker_count.append(1)
            Thread(target=close_worker, name="rt-arm64-fake-cleanup", daemon=True).start()
            root.after(5, try_operator_command)
            root.after(25, finish_close)

        _request_close_once(started, guard, launch)

    def finish_close() -> None:
        if not finished.is_set():
            root.after(25, finish_close)
            return
        root.destroy()

    def dispatch_sigterm() -> None:
        if requested.is_set():
            initiate_close()
            initiate_close()  # adversarial overlapping close request
        if not finished.is_set():
            root.after(25, dispatch_sigterm)

    def check_ready() -> None:
        readiness.append(has_fresh_heartbeat(marker, expected_pid=os.getpid(), now=time.time()))
        if not readiness[-1]:
            # The heartbeat is an actual Tk callback; refusal is the correct
            # behavior if the event loop did not publish readiness.
            raise RuntimeError("fresh Tk heartbeat was not observed")
        os.kill(os.getpid(), signal.SIGTERM)

    start_ui_heartbeat(root, path=marker)
    root.after(350, check_ready)
    root.after(25, dispatch_sigterm)
    # A strictly bounded independent hung-test fail safe: Tk events must
    # complete; this alone is not proof of physical radio shutdown.
    root.after(8000, root.destroy)
    try:
        root.mainloop()
    finally:
        signal.signal(signal.SIGTERM, previous_handler)
    result = {
        "mode": mode,
        "actual_tk_loop_entered": True,
        "native_arm64_display": os.environ.get("DISPLAY"),
        "no_real_dashboard_startup": True,
        "radio_or_ptt_tested": False,
        "test_widget_count": window_count,
        "readiness_fresh": readiness == [True],
        "stale_heartbeat_rejected": not has_fresh_heartbeat(
            marker, expected_pid=os.getpid(), now=time.time() + 12.0
        ),
        "sigterm_received": requested.is_set(),
        "close_started": started.is_set(),
        "close_finished": finished.is_set(),
        "close_worker_count": len(worker_count),
        "ordered_fake_steps": steps,
        "cleanup_errors": [error.split(":", 1)[0] for error in errors],
        "post_shutdown_operator_commands": late_commands,
        "production_ready": False,
        "loaded_python_bytes_independently_proven": False,
    }
    return result


def main() -> int:
    """Emit only test evidence; refuse failed/incomplete lifecycle execution."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", required=True, choices=MODES)
    parser.add_argument("--scratch", required=True, type=Path)
    args = parser.parse_args()
    result = run(args.mode, scratch=args.scratch)
    print("RT_ARM64_LIFECYCLE " + json.dumps(result, sort_keys=True), flush=True)
    expected_errors = []
    if args.mode == "runtime-error":
        expected_errors = ["application runtime"]
    if args.mode == "peripheral-error":
        expected_errors = ["peripheral_one"]
    if (
        result["readiness_fresh"]
        and result["stale_heartbeat_rejected"]
        and result["sigterm_received"]
        and result["close_started"]
        and result["close_finished"]
        and result["close_worker_count"] == 1
        and result["ordered_fake_steps"] == ["runtime", "peripheral_one", "peripheral_two"]
        and result["cleanup_errors"] == expected_errors
        and not result["post_shutdown_operator_commands"]
    ):
        return 0
    return 75


if __name__ == "__main__":
    raise SystemExit(main())
