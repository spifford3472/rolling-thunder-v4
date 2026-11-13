#!/usr/bin/env python3
"""Read-only bounded USB topology and host-health observer for Rolling Thunder."""

import datetime
import json
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
import subprocess
import time


def run(*args: str) -> str:
    """Run a bounded read-only command without accessing device endpoints."""
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=3, check=False)
        return result.stdout.strip()[:12000] if result.returncode == 0 else "unavailable"
    except (OSError, subprocess.TimeoutExpired):
        return "unavailable"


def snapshot() -> dict[str, object]:
    """Collect topology, serial identities, and Pi health without opening devices."""
    serial = Path("/dev/serial/by-id")
    links = {p.name: str(p.resolve()) for p in serial.iterdir()} if serial.exists() else {}
    return {
        "usb_tree": run("lsusb", "-t"),
        "serial": links,
        "throttled": run("vcgencmd", "get_throttled"),
        "temperature": run("vcgencmd", "measure_temp"),
        "loadavg": Path("/proc/loadavg").read_text().strip(),
        "memory": {
            line.split(":", 1)[0]: line.split(":", 1)[1].strip()
            for line in Path("/proc/meminfo").read_text().splitlines()
            if line.startswith(("MemAvailable:", "SwapFree:"))
        },
    }


def configure_logger(out: Path) -> logging.Logger:
    """Configure bounded local JSONL rotation when the observer starts."""
    out.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("rt-usb-observer")
    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(out / "usb-events.jsonl", maxBytes=10_000_000, backupCount=5)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    return logger


def record(logger: logging.Logger, kind: str, data: dict[str, object]) -> None:
    """Write one UTC-stamped structured record."""
    logger.info(
        json.dumps(
            {"time_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(), "event": kind, **data},
            sort_keys=True,
        )
    )


def main() -> None:
    """Log topology changes immediately and periodic heartbeat snapshots."""
    logger = configure_logger(Path.home() / ".local/state/rolling-thunder-diagnostics")
    previous: dict[str, object] | None = None
    heartbeat = 0.0
    record(logger, "observer_started", {"pid": os.getpid()})
    while True:
        try:
            current = snapshot()
            now = time.monotonic()
            if previous is None or (current["usb_tree"], current["serial"]) != (
                previous["usb_tree"], previous["serial"]
            ):
                record(logger, "usb_topology_change", current)
            elif now - heartbeat >= 60:
                record(logger, "heartbeat", current)
            if now - heartbeat >= 60:
                heartbeat = now
            previous = current
        except Exception as exc:
            record(logger, "observer_error", {"error_type": type(exc).__name__, "message": str(exc)[:200]})
        time.sleep(5)


if __name__ == "__main__":
    main()
