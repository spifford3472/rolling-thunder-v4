"""Exercise the real dashboard composition with disposable mock hardware only.

Requires a user/PID/network-isolated ARM64 QEMU/Xvfb sandbox and a private
writable /test. The actual dashboard never receives real radio or DB paths.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import time
import tkinter as tk
from pathlib import Path

from rolling_thunder import ui_main
from rolling_thunder.config import ApplicationConfig
from rolling_thunder.ui_readiness import has_fresh_heartbeat, heartbeat_path


def main() -> int:
    """Run the actual UI entry point with strictly scoped mock composition."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", required=True, choices=("normal", "startup-failure", "navigation"))
    mode = parser.parse_args().mode
    root_dir = Path("/test")
    if os.environ.get("DISPLAY") != ":95" or not root_dir.is_dir():
        raise RuntimeError("private test Xvfb and scratch required")
    if any(Path("/dev").glob("ttyUSB*")) or any(Path("/dev").glob("ttyACM*")):
        raise RuntimeError("radio device visible in test namespace")
    for key in os.environ:
        if key.startswith("ROLLING_THUNDER_"):
            raise RuntimeError("station credential environment is forbidden")
    runtime_dir = root_dir / "runtime-marker"
    runtime_dir.mkdir(mode=0o700, exist_ok=True)
    os.chmod(runtime_dir, 0o700)
    os.environ["XDG_RUNTIME_DIR"] = str(runtime_dir)
    database_path = root_dir / "scratch-dashboard.sqlite3"
    if database_path.exists():
        raise RuntimeError("refusing to reuse test SQLite database")
    cfg = ApplicationConfig.model_validate(
        {
            "operator": {"callsign": "KI5VNB", "home_grid": "EM79xm"},
            "hardware": {"mock": True, "radio_mode": "mock", "gps_mode": "mock"},
            "speech": {"enabled": False},
            "tron": {"enabled": False},
            "physical_controls": {"enabled": False},
            "forge": {"enabled": False},
            "home_platform": {"enabled": False},
            "network_keepalive": {"enabled": False},
            "ft8": {"enabled": False},
            "pota_spots": {"enabled": False},
            "pota_map": {"enabled": False},
            "map": {"enabled": False},
            "radar": {"enabled": False},
            "dmr": {"enabled": False},
            "antenna_reference": {"enabled": False},
            "meshcore_passive": {"enabled": False},
            "storage": {"database_path": str(database_path)},
        }
    )
    if (
        not cfg.hardware.mock
        or cfg.hardware.effective_radio_mode.value != "mock"
        or cfg.hardware.effective_gps_mode.value != "mock"
    ):
        raise RuntimeError("mock-only configuration rejected")
    ui_main.load_config = lambda _path: cfg
    # No real credentials, even accidentally inherited.
    from rolling_thunder.application_secrets import ApplicationSecrets

    ui_main.load_application_secrets = lambda: ApplicationSecrets()

    # Injection happens AFTER the actual radio polling start, but BEFORE
    # unrelated workers. ApplicationRuntime.start must roll itself back.
    rollback: dict[str, object] = {}
    if mode == "startup-failure":
        original_factory = ui_main.ApplicationRuntime.from_config

        def failing_runtime(*args: object, **kwargs: object) -> object:
            runtime = original_factory(*args, **kwargs)

            def inject_failure() -> None:
                raise RuntimeError("test-only startup failure after mock-radio start")

            runtime._start_remaining_services = inject_failure
            rollback["instance"] = runtime
            return runtime

        ui_main.ApplicationRuntime.from_config = failing_runtime

    original_tk = tk.Tk
    # Instrument the existing controller, not a second navigation path. This
    # records actual root key-binding dispatch in the private Tk event loop.
    original_select_shortcut = ui_main.ContextNavigationController.select_shortcut
    navigation_events: list[str] = []

    def observed_shortcut(controller: object, shortcut: str) -> bool:
        changed = original_select_shortcut(controller, shortcut)
        if changed:
            navigation_events.append(controller.state.selected.value)
        return changed

    if mode == "navigation":
        ui_main.ContextNavigationController.select_shortcut = observed_shortcut

    state = {
        "mode": mode,
        "root_created": False,
        "tk_ready": False,
        "sent_sigterm": False,
        "before_close_active": True,
        "after_close": False,
    }

    def private_tk(*args: object, **kwargs: object) -> tk.Tk:
        root = original_tk(*args, **kwargs)
        state["root_created"] = True

        def check_ready() -> None:
            path = heartbeat_path()
            state["tk_ready"] = bool(
                path and has_fresh_heartbeat(path, expected_pid=os.getpid(), now=time.time())
            )
            if state["tk_ready"]:
                if mode == "navigation":
                    # Exercise real keyboard bindings after the dashboard has
                    # installed them; reject missing events before SIGTERM.
                    root.focus_force()
                    for delay, keysym in ((150, "2"), (300, "b"), (450, "1")):
                        root.after(delay, lambda key=keysym: root.event_generate(
                            "<KeyPress>", keysym=key, when="tail"
                        ))
                    def finish_navigation() -> None:
                        state["navigation_events"] = list(navigation_events)
                        state["navigation_responsive"] = navigation_events == [
                            "dx", "browse", "pota"
                        ]
                        state["sent_sigterm"] = True
                        os.kill(os.getpid(), signal.SIGTERM)
                    root.after(850, finish_navigation)
                else:
                    state["sent_sigterm"] = True
                    os.kill(os.getpid(), signal.SIGTERM)
            else:
                root.after(300, check_ready)

        root.after(2000, check_ready)
        root.after(10000, lambda: root.destroy())
        return root

    tk.Tk = private_tk
    started = time.monotonic()
    try:
        result = ui_main.run_dashboard(root_dir / "no-config-read.yaml")
    finally:
        tk.Tk = original_tk
        if mode == "navigation":
            ui_main.ContextNavigationController.select_shortcut = original_select_shortcut
    state["after_close"] = True
    if mode == "startup-failure":
        runtime = rollback.get("instance")
        state["rollback_disconnected"] = bool(
            runtime is not None
            and runtime.radio.get_state().connection_state.value == "disconnected"
            and not runtime._started
        )
    state["return_code"] = result
    state["elapsed_s"] = round(time.monotonic() - started, 2)
    state["database_exists"] = database_path.exists()
    state["only_loopback"] = set(
        Path("/proc/net/dev").read_text().split(":")[0].splitlines()[-1].strip().split()
    ) == {"lo"}
    state["production_ready"] = False
    state["physical_radio_tested"] = False
    print("RT_DASHBOARD_PROBE " + json.dumps(state, sort_keys=True), flush=True)
    if mode == "startup-failure":
        return (
            0
            if (
                result == 3
                and state["rollback_disconnected"]
                and not state["root_created"]
                and state["only_loopback"]
            )
            else 75
        )
    if (
        result != 0
        or not state["tk_ready"]
        or not state["sent_sigterm"]
        or not state["database_exists"]
        or (mode == "navigation" and state.get("navigation_responsive") is not True)
    ):
        return 75
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
