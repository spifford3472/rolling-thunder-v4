"""Minimal Tk-loop heartbeat for supervised, receive-neutral UI readiness checks.

This heartbeat only proves that Tk callbacks continue to execute. It is not a
radio, CAT, PTT, GPS, logging, or hardware health signal.
"""

from __future__ import annotations

import json
import logging
import os
import re
import stat
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

_LOG = logging.getLogger(__name__)
HEARTBEAT_NAME = "rolling-thunder-ui-readiness.json"
_BOOT_ID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z"
)
_RELEASE_SHA = re.compile(r"[0-9a-f]{40}\Z")


def process_start_ticks(pid: int, *, proc_root: Path = Path("/proc")) -> int:
    """Read Linux process start ticks, handling spaces in the process name."""
    raw = (proc_root / str(pid) / "stat").read_bytes()
    closing = raw.rfind(b") ")
    if closing < 0:
        raise ValueError("malformed process stat")
    fields = raw[closing + 2 :].split()
    if len(fields) < 20:
        raise ValueError("incomplete process stat")
    return int(fields[19])


def boot_id(*, proc_root: Path = Path("/proc")) -> str:
    """Return the current kernel boot identity or refuse malformed data."""
    value = (proc_root / "sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
    if not _BOOT_ID.fullmatch(value):
        raise ValueError("malformed kernel boot identity")
    return value


def process_release_sha(pid: int, *, proc_root: Path = Path("/proc")) -> str | None:
    """Derive a release SHA only when the live process cwd is SHA-named."""
    try:
        release = (proc_root / str(pid) / "cwd").resolve(strict=True).name
    except OSError:
        return None
    return release if _RELEASE_SHA.fullmatch(release) else None


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


def publish_heartbeat(
    path: Path,
    *,
    pid: int,
    now: float,
    process_boot_id: str | None = None,
    start_ticks: int | None = None,
    release_sha: str | None = None,
) -> None:
    """Atomically publish one loop tick without writing into a shared directory."""
    identity = process_boot_id if process_boot_id is not None else boot_id()
    ticks = start_ticks if start_ticks is not None else process_start_ticks(pid)
    release = release_sha
    if release is None:
        release = os.environ.get("ROLLING_THUNDER_RELEASE_SHA")
    if release is None and _RELEASE_SHA.fullmatch(Path.cwd().name):
        release = Path.cwd().name
    if not _BOOT_ID.fullmatch(identity) or ticks <= 0:
        raise ValueError("invalid process identity for readiness heartbeat")
    if release is not None and not _RELEASE_SHA.fullmatch(release):
        raise ValueError("invalid release SHA for readiness heartbeat")
    payload = json.dumps(
        {
            "pid": pid,
            "time": now,
            "boot_id": identity,
            "start_ticks": ticks,
            "release_sha": release,
        },
        separators=(",", ":"),
    ) + "\n"
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
        except (OSError, ValueError) as exc:
            _LOG.warning("UI readiness heartbeat write failed: %s", exc)
        finally:
            root.after(1000, tick)

    root.after(0, tick)


def has_fresh_heartbeat(
    path: Path,
    *,
    expected_pid: int,
    now: float,
    max_age: float = 5.0,
    expected_uid: int | None = None,
    expected_boot_id: str | None = None,
    expected_start_ticks: int | None = None,
    expected_release_sha: str | None = None,
) -> bool:
    """Reject stale or process-mismatched Tk-loop readiness records."""
    try:
        owner_uid = os.getuid() if expected_uid is None else expected_uid
        parent = path.parent.lstat()
        if (
            not stat.S_ISDIR(parent.st_mode)
            or parent.st_uid != owner_uid
            or parent.st_mode & 0o077
            or path.parent.is_symlink()
        ):
            return False
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            metadata = os.fstat(fd)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != owner_uid
                or metadata.st_mode & 0o077
                or metadata.st_size > 256
            ):
                return False
            raw = os.read(fd, 257)
        finally:
            os.close(fd)
        if len(raw) > 256:
            return False
        document = json.loads(raw.decode("utf-8"))
        pid, timestamp = document["pid"], document["time"]
        identity, ticks, release = (
            document["boot_id"],
            document["start_ticks"],
            document["release_sha"],
        )
        if (
            type(pid) is not int
            or type(timestamp) not in (float, int)
            or not isinstance(identity, str)
            or not _BOOT_ID.fullmatch(identity)
            or type(ticks) is not int
            or ticks <= 0
            or (
                release is not None
                and (not isinstance(release, str) or not _RELEASE_SHA.fullmatch(release))
            )
        ):
            return False
        age = now - timestamp
        return (
            pid == expected_pid
            and 0 <= age <= max_age
            and (expected_boot_id is None or identity == expected_boot_id)
            and (expected_start_ticks is None or ticks == expected_start_ticks)
            and (expected_release_sha is None or release == expected_release_sha)
        )
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return False
