"""Minimal Tk-loop heartbeat for supervised, receive-neutral UI readiness checks.

This heartbeat only proves that Tk callbacks continue to execute. It is not a
radio, CAT, PTT, GPS, logging, or hardware health signal.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

_LOG = logging.getLogger(__name__)
HEARTBEAT_NAME = "rolling-thunder-ui-readiness.json"


class TkScheduler(Protocol):
    """The tiny Tk scheduling contract used for hardware-free regression tests."""

    def after(self, delay_ms: int, callback: Callable[[], None]) -> object: ...


def heartbeat_path(runtime_dir: str | None = None) -> Path | None:
    """Resolve only a private user runtime directory, never a shared /tmp path."""
    directory = runtime_dir if runtime_dir is not None else os.environ.get("XDG_RUNTIME_DIR")
    if not directory:
        return None
    path = Path(directory)
    try:
        mode = path.stat().st_mode
        if not path.is_dir() or path.is_symlink() or path.stat().st_uid != os.getuid():
            return None
        if mode & 0o077:
            return None
    except OSError:
        return None
    return path / HEARTBEAT_NAME


def publish_heartbeat(path: Path, *, pid: int, now: float) -> None:
    """Atomically publish one loop tick without writing into a shared directory."""
    payload = json.dumps({"pid": pid, "time": now}, separators=(",", ":")) + "\n"
    fd, temp_name = tempfile.mkstemp(prefix=".rt-ui-heartbeat-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(payload)
        os.chmod(temp_name, 0o600)
        os.replace(temp_name, path)
    finally:
        try:
            Path(temp_name).unlink(missing_ok=True)
        except OSError:
            pass


def start_ui_heartbeat(root: TkScheduler, *, path: Path | None = None) -> None:
    """Schedule timestamps *on* Tk; a blocked event loop stops fresh updates."""
    resolved = heartbeat_path() if path is None else path
    if resolved is None:
        _LOG.warning("UI readiness unavailable: no private XDG_RUNTIME_DIR")
        return

    def tick() -> None:
        try:
            publish_heartbeat(resolved, pid=os.getpid(), now=time.time())
        except OSError as exc:
            _LOG.warning("UI readiness heartbeat write failed: %s", exc)
        root.after(1000, tick)

    root.after(0, tick)


def has_fresh_heartbeat(
    path: Path,
    *,
    expected_pid: int,
    now: float,
    max_age: float = 5.0,
    expected_uid: int | None = None,
) -> bool:
    """Reject stale, malformed, foreign-PID or future-dated heartbeat records."""
    try:
        metadata = path.lstat()
        if (
            not path.is_file()
            or path.is_symlink()
            or metadata.st_uid != (os.getuid() if expected_uid is None else expected_uid)
        ):
            return False
        if metadata.st_mode & 0o077 or metadata.st_size > 128:
            return False
        document = json.loads(path.read_text(encoding="utf-8"))
        pid, timestamp = document["pid"], document["time"]
        if type(pid) is not int or type(timestamp) not in (float, int):
            return False
        age = now - timestamp
        return pid == expected_pid and 0 <= age <= max_age
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return False
