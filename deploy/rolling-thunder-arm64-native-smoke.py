"""Import-only ARM64 smoke probe in a hardware-free, networkless test sandbox.

Never invoke ``rolling_thunder.ui_main.main``: that would start a real UI and
may initialize radio/controller paths. This script tests import/link behavior
only and must never authorize a production release.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import json
import platform
import socket
import sqlite3
import subprocess
import sys
import tkinter
from pathlib import Path
from typing import Any

IMPORTS = (
    "ssl",
    "sqlite3",
    "_tkinter",
    "tkinter",
    "PIL._imaging",
    "yaml._yaml",
    "pydantic_core",
    "_cffi_backend",
    "vosk",
    "serial",
    "serial_asyncio_fast",
    "bleak",
    "dbus_fast",
    "websockets",
    "Crypto.Cipher.AES",
    "cayennelpp",
    "rolling_thunder",
)


class UnsafeImportSideEffect(RuntimeError):
    """An application import attempted prohibited startup I/O."""


def _refuse_io(*_args: Any, **_kwargs: Any) -> None:
    """Block I/O if importing the dashboard unexpectedly triggers startup."""
    raise UnsafeImportSideEffect("application import attempted a prohibited I/O operation")


def import_probe() -> dict[str, Any]:
    """Probe ARM64 native extensions without UI, hardware or I/O startup."""
    found: dict[str, dict[str, Any]] = {}
    for name in IMPORTS:
        try:
            module = importlib.import_module(name)
            found[name] = {"ok": True, "path": str(getattr(module, "__file__", "<built-in>"))}
        except Exception as exc:  # noqa: BLE001 - test harness records arbitrary import failures
            found[name] = {"ok": False, "error_type": type(exc).__name__}

    import serial

    original = (
        socket.socket.connect,
        sqlite3.connect,
        subprocess.Popen,
        tkinter.Tk,
        serial.Serial,
    )
    try:
        socket.socket.connect = _refuse_io
        sqlite3.connect = _refuse_io
        subprocess.Popen = _refuse_io
        tkinter.Tk = _refuse_io
        serial.Serial = _refuse_io
        try:
            importlib.import_module("rolling_thunder.ui_main")
            found["rolling_thunder.ui_main"] = {"ok": True}
        except Exception as exc:  # noqa: BLE001 - fail closed on any UI import side effect
            found["rolling_thunder.ui_main"] = {"ok": False, "error_type": type(exc).__name__}
    finally:
        (
            socket.socket.connect,
            sqlite3.connect,
            subprocess.Popen,
            tkinter.Tk,
            serial.Serial,
        ) = original

    device_dir = Path("/dev")
    hardware_visible = (
        any(device_dir.glob("ttyUSB*"))
        or any(device_dir.glob("ttyACM*"))
        or (device_dir / "snd").exists()
    )
    # Only loopback is expected in bwrap's private network namespace.
    net_lines = Path("/proc/net/dev").read_text(encoding="utf-8").splitlines()[2:]
    interfaces = sorted(line.split(":", 1)[0].strip() for line in net_lines if ":" in line)
    return {
        "python": platform.python_version(),
        "machine": platform.machine(),
        "python_isolated": sys.flags.isolated == 1,
        "no_bytecode_writes": sys.dont_write_bytecode,
        "interfaces": interfaces,
        "radio_or_audio_devices_visible": hardware_visible,
        "imports": found,
        "installed_app": importlib.metadata.version("rolling-thunder"),
        "import_tests_passed": all(entry["ok"] for entry in found.values()),
        "ui_started": False,
        "physical_radio_tested": False,
        "production_ready": False,
        "loaded_python_bytes_independently_proven": False,
    }


def main() -> int:
    """Return only an offline import-test result, not a deployment approval."""
    result = import_probe()
    print(json.dumps(result, sort_keys=True))
    return (
        0
        if (
            result["machine"] == "aarch64"
            and result["python"] == "3.13.5"
            and result["python_isolated"]
            and result["no_bytecode_writes"]
            and result["interfaces"] == ["lo"]
            and not result["radio_or_audio_devices_visible"]
            and result["import_tests_passed"]
        )
        else 75
    )


if __name__ == "__main__":
    raise SystemExit(main())
