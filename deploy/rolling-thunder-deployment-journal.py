"""Stand-alone, stdlib-only durable transaction ledger for the privileged wrapper.

Install only at a stable root-owned path after separate parked approval. This
file never invokes systemctl, Git, SQL migrations, or radio commands.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SHA = re.compile(r"[0-9a-f]{40}\Z")
PHASES = (
    "prepared",
    "stopping",
    "backing_up",
    "checkout",
    "installing",
    "migrating",
    "starting",
    "verifying",
    "rolling_back",
    "requires_review",
    "committed",
)
FORWARD = (
    "prepared",
    "stopping",
    "backing_up",
    "checkout",
    "installing",
    "migrating",
    "starting",
    "verifying",
    "committed",
)


class JournalError(Exception):
    """An unsafe, malformed, or unreconciled transaction was encountered."""


def _directory(path: Path) -> None:
    """Require an already-created, private, owner-controlled directory."""
    parent = path.parent
    info = parent.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid():
        raise JournalError("journal directory must be owned by the invoking identity")
    if info.st_mode & 0o077:
        raise JournalError("journal directory must be private (0700)")
    if parent.is_symlink():
        raise JournalError("symlink journal directory refused")


def read(path: Path) -> dict[str, Any] | None:
    """Reject unreadable, tampered, symlinked, or invalid journal as blocked."""
    _directory(path)
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid():
        raise JournalError("journal must be a regular owner-controlled file")
    if info.st_mode & 0o077 or info.st_size > 4096:
        raise JournalError("journal permission or size invalid")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise JournalError("journal unreadable or corrupted") from exc
    if not isinstance(document, dict) or document.get("version") != 1:
        raise JournalError("unsupported transaction record")
    if document.get("phase") not in PHASES:
        raise JournalError("unknown transaction phase")
    for name in ("previous_sha", "target_sha"):
        value = document.get(name)
        if not isinstance(value, str) or SHA.fullmatch(value) is None:
            raise JournalError("invalid transaction SHA")
    if not isinstance(document.get("backup_path"), str) or not document["backup_path"].startswith(
        "/"
    ):
        raise JournalError("invalid backup path")
    if not isinstance(document.get("transaction_id"), str) or not document["transaction_id"]:
        raise JournalError("invalid transaction identifier")
    return document


def _write(path: Path, record: dict[str, Any]) -> None:
    """Durably replace the record: fsync temporary file, rename, fsync parent."""
    _directory(path)
    # Fail closed if an existing path is unsafe, even before a replace.
    read(path)
    temp_path: Path | None = None
    try:
        fd, name = tempfile.mkstemp(prefix=".transaction-", suffix=".tmp", dir=path.parent)
        temp_path = Path(name)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(record, stream, sort_keys=True, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def begin(path: Path, previous: str, target: str, backup: str) -> None:
    """An incomplete transaction always blocks all subsequent deployments."""
    if SHA.fullmatch(previous) is None or SHA.fullmatch(target) is None:
        raise JournalError("invalid exact SHA")
    if not Path(backup).is_absolute():
        raise JournalError("backup must use an absolute path")
    current = read(path)
    if current is not None and current["phase"] != "committed":
        raise JournalError(
            f"unreconciled transaction {current['transaction_id']} phase={current['phase']}"
        )
    _write(
        path,
        {
            "version": 1,
            "transaction_id": os.urandom(16).hex(),
            "previous_sha": previous,
            "target_sha": target,
            "backup_path": backup,
            "phase": "prepared",
            "updated_utc": datetime.now(UTC).isoformat(),
        },
    )


def advance(path: Path, phase: str) -> None:
    """Record entry to a potentially destructive phase before it begins."""
    if phase not in PHASES or phase in ("prepared", "committed"):
        raise JournalError("invalid phase transition")
    current = read(path)
    if current is None or current["phase"] == "committed":
        raise JournalError("no active transaction")
    prior = current["phase"]
    if prior == "requires_review" or (prior == "rolling_back" and phase != "requires_review"):
        raise JournalError("transaction requires independent reconciliation")
    if phase not in ("rolling_back", "requires_review"):
        if prior not in FORWARD or phase not in FORWARD:
            raise JournalError("invalid forward transaction phase")
        if FORWARD.index(phase) != FORWARD.index(prior) + 1:
            raise JournalError("transaction phase cannot be skipped or reversed")
    current["phase"] = phase
    current["updated_utc"] = datetime.now(UTC).isoformat()
    _write(path, current)


def commit(path: Path) -> None:
    """Only a fully verified successful deployment may finish a transaction."""
    current = read(path)
    if current is None or current["phase"] != "verifying":
        raise JournalError("transaction not eligible for completion")
    current["phase"] = "committed"
    current["updated_utc"] = datetime.now(UTC).isoformat()
    _write(path, current)


def main() -> int:
    """Dispatch the read-only/atomic journal commands; never recover automatically."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("inspect", "begin", "phase", "commit"))
    parser.add_argument("path", type=Path)
    parser.add_argument("arguments", nargs="*")
    options = parser.parse_args()
    try:
        if options.operation == "inspect" and not options.arguments:
            record = read(options.path)
            print(json.dumps(record, sort_keys=True))
            return 0 if record is not None else 2
        if options.operation == "begin" and len(options.arguments) == 3:
            begin(options.path, *options.arguments)
        elif options.operation == "phase" and len(options.arguments) == 1:
            advance(options.path, options.arguments[0])
        elif options.operation == "commit" and not options.arguments:
            commit(options.path)
        else:
            parser.error("wrong argument count")
        return 0
    except (JournalError, OSError) as exc:
        print(f"TRANSACTION REFUSED: {exc}", file=sys.stderr)
        return 75


if __name__ == "__main__":
    raise SystemExit(main())
