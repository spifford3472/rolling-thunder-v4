"""Separate approval-gated attestation of an already-running safe release.

This tool never invokes a service, Git write, radio, backup restore, or schema
migration. It only records reviewed evidence in the durable transaction journal.
Intended for a separate owner-approved stable privileged installation, NOT use
from an ordinary development checkout or during a drive.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
import stat
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _load(filename: str, name: str) -> Any:
    source = Path(__file__).with_name(filename)
    spec = importlib.util.spec_from_file_location(name, source)
    if spec is None or spec.loader is None:
        raise ValueError("stable support module unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _approval(path: Path) -> dict[str, Any]:
    """Read a private, externally approved one-time receipt, without following links."""
    parent = path.parent.lstat()
    if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.geteuid() or parent.st_mode & 0o077:
        raise ValueError("approval directory not private or owner-controlled")
    if path.parent.is_symlink():
        raise ValueError("approval directory symlink")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or info.st_mode & 0o077
            or info.st_size > 4096
        ):
            raise ValueError("approval must be a private regular owner-controlled file")
        with os.fdopen(fd, "r", encoding="utf-8", closefd=False) as stream:
            receipt = json.load(stream)
    finally:
        os.close(fd)
    if not isinstance(receipt, dict):
        raise TypeError("approval payload invalid")
    if receipt.get("decision") != "attest_existing_running_release":
        raise ValueError("approval does not authorize reviewed attestation")
    try:
        expires = datetime.fromisoformat(receipt["expires_utc"])
        if expires.tzinfo is None or not datetime.now(UTC) < expires.astimezone(UTC):
            raise ValueError("approval expired or missing timezone")
    except (KeyError, TypeError) as exc:
        raise ValueError("invalid approval expiration") from exc
    return receipt


def _evidence_hash(report: dict[str, Any]) -> str:
    """Bind explicit approval to exact independently collected report values."""
    return hashlib.sha256(
        json.dumps(report, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def reconcile(
    *,
    journal_path: Path,
    app: Path,
    database: Path,
    lock_path: Path,
    approval_path: Path,
    proc: Path = Path("/proc"),
    require_root: bool = True,
) -> dict[str, str]:
    """Only attest a preexisting, responsive, schema-compatible release.

    The owner must independently approve this exact report. Even success here
    does not authorize transmission or prove physical PTT receive state.
    """
    if require_root and os.geteuid() != 0:
        raise ValueError("reconciliation requires approved privileged execution")
    reader = _load("rolling-thunder-deployment-journal.py", "rt_reconcile_journal")
    inspector = _load("rolling-thunder-recovery-inspect.py", "rt_reconcile_inspector")
    parent = lock_path.parent.lstat()
    if (
        lock_path.is_symlink()
        or lock_path.parent.is_symlink()
        or not stat.S_ISDIR(parent.st_mode)
        or parent.st_uid != os.geteuid()
        or parent.st_mode & 0o022
    ):
        raise ValueError("unsafe deployment lock directory or path")
    lock_fd = os.open(lock_path, os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        info = os.fstat(lock_fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise ValueError("unsafe deployment lock ownership or permissions")
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("deployment transaction lock held") from exc
        report = inspector.inspect(journal_path, app, database, proc=proc)
        record = report.get("journal")
        if not isinstance(record, dict) or "journal_error" in report:
            raise ValueError("unreadable or missing journal")
        # Re-read the canonical journal under the same lock. A stale inspector
        # report must never attest a newer or already reconciled transaction.
        canonical = reader.read(journal_path)
        if canonical != record:
            raise ValueError("journal changed since inspection")
        if record["phase"] in ("committed", "reconciled"):
            raise ValueError("no unreconciled transaction")
        if (
            report["database"].get("integrity") != "ok"
            or report.get("schema_compatible_with_backup") is not True
        ):
            raise ValueError("SQLite current/backup integrity or schema mismatch")
        if report.get("contact_count_not_regressed") is not True:
            raise ValueError("QSO count not verified preserved")
        if report.get("backup_contact_records_preserved") is not True:
            raise ValueError("original QSO rows were not all verified preserved")
        if report["service"].get("state") != "single_expected_service_process":
            raise ValueError("running process not independently verified")
        if report["service"].get("responsiveness") != "tk_heartbeat_fresh":
            raise ValueError("UI readiness unknown, possibly legacy release")
        sha = report.get("git_sha")
        if sha not in (record["previous_sha"], record["target_sha"]):
            raise ValueError("unexpected installed checkout SHA")
        receipt = _approval(approval_path)
        digest = _evidence_hash(report)
        if (
            receipt.get("running_sha_independently_verified") is not True
            or not isinstance(receipt.get("running_sha_verification_method"), str)
            or len(receipt["running_sha_verification_method"]) < 12
        ):
            raise ValueError("independent running-code identity attestation required")
        if (
            receipt.get("transaction_id") != record["transaction_id"]
            or receipt.get("evidence_sha256") != digest
            or receipt.get("expected_sha") != sha
        ):
            raise ValueError("approval does not bind current transaction and evidence")
        reader.attest_reconciled(
            journal_path,
            transaction_id=record["transaction_id"],
            approval_id=receipt["approval_id"],
            evidence_hash=digest,
            verified_sha=sha,
        )
        return {
            "state": "reconciled",
            "transaction_id": record["transaction_id"],
            "approval_id": receipt["approval_id"],
            "sha": sha,
        }
    finally:
        os.close(lock_fd)


def main() -> int:
    """Execute only on explicitly approved, parked privileged recovery path."""
    parser = argparse.ArgumentParser(description=__doc__)
    # No privileged path override switches. Tests inject fixture paths directly.
    parser.add_argument("--approval", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = reconcile(
            journal_path=Path("/var/lib/rolling-thunder-deploy/transaction.json"),
            app=Path("/home/geoff/projects/rolling-thunder-v4"),
            database=Path("/home/geoff/projects/rolling-thunder-v4/config/data/rolling-thunder.db"),
            lock_path=Path("/run/rolling-thunder-deploy.lock"),
            approval_path=args.approval,
        )
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"RECONCILIATION REFUSED: {exc}", file=sys.stderr)
        return 75


if __name__ == "__main__":
    raise SystemExit(main())
