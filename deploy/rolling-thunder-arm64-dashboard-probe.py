"""Exercise real dashboard composition with disposable fake hardware only.

This guest runs only inside the reviewed unprivileged ARM64 QEMU/Xvfb sandbox.
It has no station devices, external network, live database, or credentials.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sqlite3
import sys
import time
import tkinter as tk
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Thread
from uuid import UUID

# The runner mounts the checked-out application package read-only at /work.
sys.path.insert(0, "/work")

from rolling_thunder import ui_main, ui_readiness
from rolling_thunder.application_secrets import ApplicationSecrets
from rolling_thunder.config import ApplicationConfig
from rolling_thunder.contact_repository import ContactRepository
from rolling_thunder.domain import Contact
from rolling_thunder.mock_gps import MockGPSReceiver
from rolling_thunder.mock_radio import MockRadio
from rolling_thunder.physical_controls import ControlAction
from rolling_thunder.status_monitor import (
    FixedStatusProbe,
    ProbeResult,
    StatusMonitorService,
    StatusState,
)
from rolling_thunder.threading_scheduler import ThreadingPollScheduler


def _fixture_contact() -> Contact:
    """Create a deterministic synthetic record; never import station log data."""
    return Contact(
        contact_id=UUID("00000000-0000-0000-0000-000000000007"),
        callsign="K1TEST",
        frequency_hz=14_074_000,
        mode="usb",
        started_at=datetime(2026, 11, 14, 20, 0, tzinfo=UTC),
        rst_sent="59",
        rst_received="59",
        grid="FN31",
        my_grid="EM79xm",
        source="browse",
        tx_power_watts=5,
        synchronization_state="failed",
        notes="STAB-07I disposable fixture",
    )


def _offline_status_monitor() -> StatusMonitorService:
    """Use the real monitor lifecycle with no network or device probes."""
    unavailable = FixedStatusProbe(
        ProbeResult(StatusState.UNAVAILABLE, "disabled by offline harness")
    )
    return StatusMonitorService(
        unavailable,
        unavailable,
        unavailable,
        ThreadingPollScheduler(),
    )


def _database_evidence(database_path: Path, fixture: Contact) -> dict[str, object]:
    """Check SQLite integrity and back up a disposable DB without restoring it."""
    if not database_path.is_file() or database_path.is_symlink():
        return {"database_exists": False, "sqlite_integrity": "missing"}
    with sqlite3.connect(f"file:{database_path}?mode=ro", uri=True) as source:
        integrity = source.execute("PRAGMA integrity_check").fetchone()
        quick = source.execute("PRAGMA quick_check").fetchone()
        row = ContactRepository(database_path).get(fixture.contact_id)
        if row != fixture:
            raise RuntimeError("synthetic QSO was not preserved after dashboard shutdown")
        backup_path = database_path.parent / "dashboard-backup.sqlite3"
        if backup_path.exists():
            raise RuntimeError("refusing to overwrite a previous disposable backup")
        with sqlite3.connect(backup_path) as destination:
            source.backup(destination)
    with sqlite3.connect(f"file:{backup_path}?mode=ro", uri=True) as backup:
        backup_integrity = backup.execute("PRAGMA integrity_check").fetchone()
        backup_row = ContactRepository(backup_path).get(fixture.contact_id)
    return {
        "database_exists": True,
        "sqlite_integrity": integrity[0] if integrity else "missing",
        "sqlite_quick_check": quick[0] if quick else "missing",
        "fixture_preserved": row == fixture,
        "backup_integrity": backup_integrity[0] if backup_integrity else "missing",
        "backup_fixture_preserved": backup_row == fixture,
        "automatic_restore_performed": False,
    }


def main() -> int:
    """Run the real dashboard entry point under fixed safe adapters."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        required=True,
        choices=(
            "normal",
            "startup-failure",
            "cleanup-failure",
            "missing-heartbeat",
            "blocked-worker",
        ),
    )
    mode = parser.parse_args().mode
    scratch = Path("/test")
    if os.environ.get("DISPLAY") != ":95" or not scratch.is_dir():
        raise RuntimeError("private Xvfb display and disposable scratch are required")
    if (
        any(Path("/dev").glob("ttyUSB*"))
        or any(Path("/dev").glob("ttyACM*"))
        or Path("/dev/snd").exists()
    ):
        raise RuntimeError("radio or sound device visible in test namespace")
    if any(key.startswith("ROLLING_THUNDER_") for key in os.environ):
        raise RuntimeError("station credential environment is forbidden")
    if not Path(ui_main.__file__).resolve().is_relative_to(Path("/work/rolling_thunder")):
        raise RuntimeError("dashboard did not import from the reviewed source mount")

    runtime_dir = scratch / "runtime-marker"
    runtime_dir.mkdir(mode=0o700, exist_ok=True)
    os.chmod(runtime_dir, 0o700)
    os.environ["XDG_RUNTIME_DIR"] = str(runtime_dir)
    database_path = scratch / "scratch-dashboard.sqlite3"
    if database_path.exists():
        raise RuntimeError("refusing to reuse a disposable dashboard database")

    config = ApplicationConfig.model_validate(
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
        not config.hardware.mock
        or config.hardware.effective_radio_mode.value != "mock"
        or config.hardware.effective_gps_mode.value != "mock"
        or config.ft8.enabled
        or config.ft8.transmit.enabled
        or config.physical_controls.enabled
        or config.forge.enabled
        or config.home_platform.enabled
        or config.network_keepalive.enabled
        or config.dmr.enabled
        or config.meshcore_passive.enabled
        or config.speech.enabled
        or config.tron.enabled
    ):
        raise RuntimeError("strict fake-hardware/offline configuration rejected")

    state: dict[str, object] = {
        "mode": mode,
        "root_created": False,
        "tk_ready": False,
        "sent_sigterm": False,
        "after_close": False,
        "refresh_callbacks": 0,
        "close_request_count": 0,
        "close_worker_count": 0,
        "mutation_attempted": False,
        "mutation_accepted": False,
        "pending_callsign_after_mutation": "",
    }
    original_tk = tk.Tk
    original_factory = ui_main.ApplicationRuntime.from_config
    original_status_factory = ui_main.build_status_monitor
    original_secrets = ui_main.load_application_secrets
    original_config = ui_main.load_config
    original_builder = ui_main.build_dashboard_state
    original_commands = ui_main.OperatorCommandController
    original_thread = ui_main.Thread
    original_request = ui_main._request_close_once
    original_start_heartbeat = ui_readiness.start_ui_heartbeat
    original_panel_stop = ui_main.MeshcoreOhgoPanelWorker.stop

    def runtime_factory(*args: object, **kwargs: object) -> object:
        runtime = original_factory(*args, **kwargs)
        state["runtime"] = runtime
        return runtime

    def command_factory(*args: object, **kwargs: object) -> object:
        commands = original_commands(*args, **kwargs)
        state["commands"] = commands
        state["capture"] = args[0]
        return commands

    def tracked_thread(*args: object, **kwargs: object) -> Thread:
        if kwargs.get("name") == "rt-orderly-close":
            state["close_worker_count"] = int(state["close_worker_count"]) + 1
        return original_thread(*args, **kwargs)

    def tracked_request(started: object, guard: object, launch: object) -> bool:
        accepted = original_request(started, guard, launch)
        state["close_request_count"] = int(state["close_request_count"]) + 1
        if accepted:
            # Attempt a real operator mutation immediately after the close guard
            # accepts shutdown; the command controller must reject it.
            record_blocked_mutation()
        return accepted

    def tracked_dashboard_state(*args: object, **kwargs: object) -> object:
        state["refresh_callbacks"] = int(state["refresh_callbacks"]) + 1
        return original_builder(*args, **kwargs)

    def injected_panel_stop(worker: object) -> object:
        if mode == "blocked-worker":
            def bounded_refusal() -> None:
                time.sleep(4)
                print("RT_DASHBOARD_REFUSAL blocked_shutdown_worker", flush=True)
                os._exit(75)

            print("RT_TEST_BLOCKED_WORKER phase=cleanup_started", flush=True)
            Thread(
                target=bounded_refusal,
                daemon=True,
                name="stab07i-blocked-worker-watchdog",
            ).start()
            Event().wait()
        result = original_panel_stop(worker)
        if mode == "cleanup-failure":
            raise RuntimeError("test-only background worker cleanup failure")
        return result

    ui_main.ApplicationRuntime.from_config = runtime_factory
    ui_main.load_config = lambda _path: config
    ui_main.load_application_secrets = lambda: ApplicationSecrets()
    ui_main.build_status_monitor = lambda _config: _offline_status_monitor()
    ui_main.OperatorCommandController = command_factory
    ui_main.Thread = tracked_thread
    ui_main._request_close_once = tracked_request
    ui_main.build_dashboard_state = tracked_dashboard_state
    ui_main.MeshcoreOhgoPanelWorker.stop = injected_panel_stop
    if mode == "missing-heartbeat":
        ui_readiness.start_ui_heartbeat = lambda _root: None
        heartbeat = runtime_dir / ui_readiness.HEARTBEAT_NAME
        heartbeat.write_text(
            json.dumps({"pid": os.getpid(), "time": time.time() - 3600}) + "\n",
            encoding="utf-8",
        )
        os.chmod(heartbeat, 0o600)
    if mode == "startup-failure":
        def fail_remaining_services() -> None:
            raise RuntimeError("test-only startup failure after mock-radio start")

        def failing_runtime_factory(*args: object, **kwargs: object) -> object:
            runtime = original_factory(*args, **kwargs)
            state["runtime"] = runtime
            runtime._start_remaining_services = fail_remaining_services
            return runtime

        ui_main.ApplicationRuntime.from_config = failing_runtime_factory

    fixture = _fixture_contact()

    def record_blocked_mutation() -> None:
        commands = state.get("commands")
        capture = state.get("capture")
        if commands is None or capture is None:
            raise RuntimeError("operator command controller was not captured")
        state["mutation_attempted"] = True
        state["mutation_accepted"] = commands.execute(ControlAction.DISCARD)
        state["pending_callsign_after_mutation"] = capture.state.pending_callsign

    def private_tk(*args: object, **kwargs: object) -> tk.Tk:
        root = original_tk(*args, **kwargs)
        state["root_created"] = True
        runtime = state.get("runtime")
        state["mock_radio"] = isinstance(runtime.radio, MockRadio)
        state["mock_gps"] = isinstance(runtime.gps, MockGPSReceiver)
        state["runtime_started"] = bool(runtime._started)
        capture = state.get("capture")
        if capture is None:
            raise RuntimeError("operator command composition was not constructed")
        capture.preload_callsign("K1TEST")
        ContactRepository(database_path).add(fixture)

        def check_ready() -> None:
            path = ui_readiness.heartbeat_path()
            fresh = bool(
                path
                and ui_readiness.has_fresh_heartbeat(
                    path, expected_pid=os.getpid(), now=time.time()
                )
            )
            if mode == "missing-heartbeat":
                state["tk_ready"] = False
                state["readiness_refused"] = not fresh
                state["sent_sigterm"] = True
                os.kill(os.getpid(), signal.SIGTERM)
                return
            state["tk_ready"] = fresh
            if fresh and int(state["refresh_callbacks"]) >= 2:
                state["widget_count"] = len(root.winfo_children())
                state["sent_sigterm"] = True
                os.kill(os.getpid(), signal.SIGTERM)
                root.after(50, lambda: root.event_generate("<Escape>", when="tail"))
                root.after(150, lambda: root.event_generate("<Escape>", when="tail"))
                root.after(250, record_blocked_mutation)
            else:
                root.after(150, check_ready)

        root.after(1500 if mode == "cleanup-failure" else 2000, check_ready)
        return root

    tk.Tk = private_tk
    started = time.monotonic()
    try:
        result = ui_main.run_dashboard(scratch / "no-config-read.yaml")
    finally:
        tk.Tk = original_tk
        ui_main.ApplicationRuntime.from_config = original_factory
        ui_main.load_config = original_config
        ui_main.load_application_secrets = original_secrets
        ui_main.build_status_monitor = original_status_factory
        ui_main.build_dashboard_state = original_builder
        ui_main.OperatorCommandController = original_commands
        ui_main.Thread = original_thread
        ui_main._request_close_once = original_request
        ui_main.MeshcoreOhgoPanelWorker.stop = original_panel_stop
        ui_readiness.start_ui_heartbeat = original_start_heartbeat

    state["after_close"] = True
    state["return_code"] = result
    state["elapsed_s"] = round(time.monotonic() - started, 2)
    state["only_loopback"] = {
        line.split(":", 1)[0].strip()
        for line in Path("/proc/net/dev").read_text().splitlines()[2:]
    } == {"lo"}
    state["production_ready"] = False
    state["physical_radio_tested"] = False
    if mode in ("normal", "cleanup-failure"):
        state.update(_database_evidence(database_path, fixture))
        runtime = state["runtime"]
        state["runtime_closed"] = (
            not runtime._started
            and runtime.radio.get_state().connection_state.value == "disconnected"
        )
    elif mode == "startup-failure":
        runtime = state.get("runtime")
        state["runtime_closed"] = (
            runtime is not None
            and not runtime._started
            and runtime.radio.get_state().connection_state.value == "disconnected"
        )
    for private_key in ("runtime", "commands", "capture"):
        state.pop(private_key, None)
    print("RT_DASHBOARD_PROBE " + json.dumps(state, sort_keys=True), flush=True)

    if mode == "startup-failure":
        return (
            0
            if result == 3
            and state.get("runtime_closed") is True
            and state.get("root_created") is False
            and state["only_loopback"]
            else 75
        )
    if mode == "cleanup-failure":
        return 75
    if mode == "missing-heartbeat":
        return 75
    return (
        0
        if result == 0
        and state.get("tk_ready") is True
        and state.get("sent_sigterm") is True
        and state.get("runtime_closed") is True
        and state.get("mock_radio") is True
        and state.get("mock_gps") is True
        and int(state.get("refresh_callbacks", 0)) >= 2
        and int(state.get("widget_count", 0)) > 0
        and state.get("mutation_attempted") is True
        and state.get("mutation_accepted") is False
        and state.get("pending_callsign_after_mutation") == "K1TEST"
        and int(state.get("close_worker_count", 0)) == 1
        and int(state.get("close_request_count", 0)) >= 2
        and state.get("fixture_preserved") is True
        and state.get("backup_fixture_preserved") is True
        and state.get("sqlite_integrity") == "ok"
        and state.get("sqlite_quick_check") == "ok"
        and state.get("backup_integrity") == "ok"
        and state["only_loopback"]
        else 75
    )


if __name__ == "__main__":
    raise SystemExit(main())
