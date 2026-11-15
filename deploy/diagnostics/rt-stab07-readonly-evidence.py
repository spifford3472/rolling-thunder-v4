"""Read-only, redacted evidence for installed privileged deployment artifacts.

Owner executes this separately while parked with normal interactive sudo.
Never copies privileged files, changes permissions, prints environment values,
invokes deployment, restarts services, or performs CAT/PTT operations.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any

WRAPPER = Path("/usr/local/sbin/rolling-thunder-deploy")
SNAPSHOT = Path("/home/geoff/rolling-thunder-review/installed-wrapper-20261114T035408Z.sh")
FT8_DROPIN = Path("/etc/systemd/system/rolling-thunder.service.d/60-ft8-period.conf")


def inspect_regular_file(path: Path, *, expected_uid: int | None = None) -> dict[str, Any]:
    """Refuse symbolic links; return only metadata and content SHA256."""
    output: dict[str, Any] = {"path": str(path), "state": "unverified"}
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or path.is_symlink():
            output["error"] = "unsafe_file_type"
            return output
        if expected_uid is not None and info.st_uid != expected_uid:
            output["error"] = "unexpected_owner"
            return output
        # Use O_NOFOLLOW with inode consistency to limit TOCTOU on trusted paths.
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            current = os.fstat(fd)
            if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
                output["error"] = "file_identity_changed"
                return output
            digest = hashlib.sha256()
            while chunk := os.read(fd, 65536):
                digest.update(chunk)
        finally:
            os.close(fd)
        output.update(
            {
                "state": "read_only_verified",
                "sha256": digest.hexdigest(),
                "size_bytes": info.st_size,
                "mode_octal": f"{stat.S_IMODE(info.st_mode):04o}",
                "owner_uid": info.st_uid,
            }
        )
    except (OSError, ValueError) as exc:
        output["error"] = type(exc).__name__
    return output


def redacted_directive_keys(path: Path) -> list[str]:
    """Expose only systemd directive names; never dump protected values."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        with os.fdopen(fd, "r", encoding="utf-8", closefd=False) as stream:
            keys: set[str] = set()
            for line in stream:
                stripped = line.strip()
                if not stripped or stripped.startswith(("#", ";", "[")):
                    continue
                if "=" in stripped:
                    key = stripped.split("=", 1)[0].strip()
                    if key.isidentifier():
                        keys.add(key)
            return sorted(keys)
    finally:
        os.close(fd)


def collect_evidence(
    *,
    wrapper: Path = WRAPPER,
    snapshot: Path = SNAPSHOT,
    dropin: Path = FT8_DROPIN,
    root_uid: int = 0,
) -> dict[str, Any]:
    """Keep all evidence read-only and report missing protected reads as NO GO."""
    installed = inspect_regular_file(wrapper, expected_uid=root_uid)
    captured = inspect_regular_file(snapshot)
    ft8 = inspect_regular_file(dropin, expected_uid=root_uid)
    report: dict[str, Any] = {
        "version": 1,
        "installed_wrapper": installed,
        "operator_snapshot": captured,
        "protected_ft8_dropin": ft8,
        "installed_wrapper_matches_snapshot": (
            installed.get("state") == "read_only_verified"
            and captured.get("state") == "read_only_verified"
            and installed.get("sha256") == captured.get("sha256")
        ),
        "disposition": "NO_GO_PENDING_OWNER_AND_PARKED_ACCEPTANCE",
    }
    if ft8.get("state") == "read_only_verified":
        try:
            report["protected_ft8_directive_names_only"] = redacted_directive_keys(dropin)
        except (OSError, UnicodeError):
            report["protected_ft8_directive_names_only"] = []
    return report


def main() -> int:
    """Print only non-secret proof; exit nonzero when protected data is unreadable."""
    report = collect_evidence()
    print(json.dumps(report, sort_keys=True))
    return (
        0
        if (
            report["installed_wrapper_matches_snapshot"]
            and report["protected_ft8_dropin"]["state"] == "read_only_verified"
        )
        else 2
    )


if __name__ == "__main__":
    raise SystemExit(main())
