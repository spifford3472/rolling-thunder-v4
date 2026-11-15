"""Read-only audit of installed ARM64 wheel RECORD files against exact pins.

This tool reads an offline virtual environment from the host; it never imports
foreign extension modules or starts services. A passing audit is not runtime
provenance or production authorization.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import csv
import hashlib
import json
import re
from email.parser import Parser
from pathlib import Path
from typing import Any

from packaging.utils import canonicalize_name

_SHA256 = re.compile(r"[a-f0-9]{64}\Z")
_MAX_DIST_FILES = 40000
_MAX_SINGLE_FILE = 100 * 1024 * 1024


class RecordAuditError(ValueError):
    """The installed package inventory is incomplete or internally altered."""


def _hash_file(path: Path) -> tuple[str, int]:
    """Stream SHA256 and byte count with size and symlink refusal."""
    if path.is_symlink() or not path.is_file():
        raise RecordAuditError("untrusted installed file type")
    initial = path.stat()
    size = initial.st_size
    if size > _MAX_SINGLE_FILE:
        raise RecordAuditError("installed file exceeds audit limit")
    sha = hashlib.sha256()
    total = 0
    with path.open("rb") as stream:
        for fragment in iter(lambda: stream.read(65536), b""):
            total += len(fragment)
            if total > _MAX_SINGLE_FILE:
                raise RecordAuditError("installed file grew during audit")
            sha.update(fragment)
    after = path.stat()
    if total != size or (after.st_ino, after.st_size, after.st_mtime_ns) != (
        initial.st_ino,
        initial.st_size,
        initial.st_mtime_ns,
    ):
        raise RecordAuditError("installed file changed during read")
    return sha.hexdigest(), total


def _audit_record(root: Path, dist: Path) -> tuple[int, int]:
    """Validate every hash-bearing RECORD entry with no path escape."""
    record = dist / "RECORD"
    if record.is_symlink() or not record.is_file():
        raise RecordAuditError("missing trusted wheel RECORD")
    site = dist.parent
    rows = 0
    hashed = 0
    with record.open(newline="", encoding="utf-8") as stream:
        for name, digest, length in csv.reader(stream):
            rows += 1
            if rows > _MAX_DIST_FILES or not name:
                raise RecordAuditError("invalid or oversized wheel RECORD")
            literal = site / name
            if literal.is_symlink():
                raise RecordAuditError("symlinked installed wheel payload")
            path = literal.resolve(strict=False)
            if not path.is_relative_to(root.resolve()):
                raise RecordAuditError("wheel RECORD escaped offline venv")
            if path.is_symlink() or not path.is_file():
                raise RecordAuditError("missing installed RECORD path")
            if not digest:
                # RECORD cannot hash itself (self-referential hash).
                if path != record:
                    raise RecordAuditError("unhashed installed wheel payload")
                continue
            try:
                method, encoded = digest.split("=", 1)
                raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
            except (ValueError, binascii.Error) as exc:
                raise RecordAuditError("invalid wheel RECORD digest encoding") from exc
            if method != "sha256" or len(raw) != 32:
                raise RecordAuditError("unsupported installed wheel RECORD hash")
            actual_digest, actual_length = _hash_file(path)
            if actual_digest != raw.hex() or (length and int(length) != actual_length):
                raise RecordAuditError("installed RECORD content mismatch")
            hashed += 1
    return rows, hashed


def audit(venv: Path, lock_path: Path, *, app_name: str, app_version: str) -> dict[str, Any]:
    """Require the 26 pinned wheels plus one exact noneditable app distribution."""
    if venv.is_symlink() or not venv.is_dir():
        raise RecordAuditError("invalid offline virtual environment")
    site = venv / "lib/python3.13/site-packages"
    if not site.is_dir() or site.is_symlink():
        raise RecordAuditError("Python 3.13 installed site-packages missing")
    pins = json.loads(lock_path.read_text(encoding="utf-8"))["packages"]
    if not isinstance(pins, dict) or len(pins) != 26:
        raise RecordAuditError("expected 26 locked dependencies")
    expected = {name: info["version"] for name, info in pins.items()}
    expected[canonicalize_name(app_name)] = app_version
    found: dict[str, str] = {}
    total_rows = 0
    total_hashed = 0
    bootstrap = False
    for dist in sorted(site.glob("*.dist-info")):
        if dist.is_symlink():
            raise RecordAuditError("symlinked distribution metadata")
        metadata = dist / "METADATA"
        if not metadata.is_file() or metadata.is_symlink():
            raise RecordAuditError("missing distribution metadata")
        message = Parser().parsestr(metadata.read_text(encoding="utf-8"))
        name = canonicalize_name(message.get("Name", ""))
        version = message.get("Version", "")
        if name == "pip":
            bootstrap = True
            continue  # Debian pip bootstrap is an OS dependency, not app lock.
        if name in found or name not in expected or version != expected[name]:
            raise RecordAuditError("unexpected, duplicated or wrong-version package")
        found[name] = version
        rows, hashed = _audit_record(venv, dist)
        total_rows += rows
        total_hashed += hashed
    if found != expected or not bootstrap:
        raise RecordAuditError("missing installed dependency, application or Debian pip bootstrap")
    return {
        "status": "installed_wheel_record_hashes_verified",
        "dependencies_checked": len(pins),
        "app_version": app_version,
        "record_entries_checked": total_rows,
        "hashes_verified": total_hashed,
        "debian_pip_bootstrap_separately_managed": True,
        "production_ready": False,
        "loaded_python_bytes_independently_proven": False,
    }


def main() -> int:
    """Emit a scoped offline audit result, never a production-ready verdict."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--venv", type=Path, required=True)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--app-name", default="rolling-thunder")
    parser.add_argument("--app-version", default="4.4.1")
    options = parser.parse_args()
    try:
        report = audit(
            options.venv, options.lock, app_name=options.app_name, app_version=options.app_version
        )
        print(json.dumps(report, sort_keys=True))
        return 0
    except (OSError, KeyError, TypeError, RecordAuditError, ValueError) as exc:
        parser.exit(75, f"ARM64 RECORD AUDIT REFUSED: {type(exc).__name__}: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
