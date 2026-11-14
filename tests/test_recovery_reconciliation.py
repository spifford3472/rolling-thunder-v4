"""Controlled reconciliation remains separate from read-only inspection."""

from __future__ import annotations

import fcntl
import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

BASE = Path(__file__).resolve().parents[1] / "deploy"
OLD = "a" * 40
TARGET = "b" * 40


def _load(name: str, filename: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, BASE / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


journal = _load("stab06f_journal", "rolling-thunder-deployment-journal.py")
reconciler = _load("stab06f_reconcile", "rolling-thunder-reconcile.py")


def _setup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[dict[str, Any], dict[str, Path]]:
    private = tmp_path / "journal"
    private.mkdir(mode=0o700)
    record_path = private / "transaction.json"
    journal.begin(record_path, OLD, TARGET, str(tmp_path / "backup.db"))
    record = journal.read(record_path)
    report: dict[str, Any] = {
        "journal": record,
        "git_sha": TARGET,
        "database": {"integrity": "ok", "contact_count": 42},
        "backup": {"integrity": "ok", "contact_count": 41},
        "schema_compatible_with_backup": True,
        "contact_count_not_regressed": True,
        "backup_contact_records_preserved": True,
        "service": {
            "state": "single_expected_service_process",
            "responsiveness": "tk_heartbeat_fresh",
        },
        "radio_ptt_state": "not_independently_verified",
    }
    approv_dir = tmp_path / "approvals"
    approv_dir.mkdir(mode=0o700)
    approval_path = approv_dir / "approval.json"
    lock_path = tmp_path / "deploy.lock"
    lock_path.write_text("", encoding="utf-8")
    lock_path.chmod(0o600)
    receipt = {
        "decision": "attest_existing_running_release",
        "transaction_id": record["transaction_id"],
        "approval_id": "APPROVAL-001",
        "expected_sha": TARGET,
        "evidence_sha256": reconciler._evidence_hash(report),
        "running_sha_independently_verified": True,
        "running_sha_verification_method": "operator parked independent process verification",
        "expires_utc": (datetime.now(UTC) + timedelta(minutes=3)).isoformat(),
    }
    approval_path.write_text(json.dumps(receipt), encoding="utf-8")
    approval_path.chmod(0o600)
    real_load = reconciler._load

    def fake_loader(filename: str, name: str) -> Any:
        if filename == "rolling-thunder-recovery-inspect.py":
            return SimpleNamespace(inspect=lambda *_args, **_kwargs: report)
        return real_load(filename, name)

    monkeypatch.setattr(reconciler, "_load", fake_loader)
    return report, {
        "journal": record_path,
        "approval": approval_path,
        "lock": lock_path,
        "app": tmp_path / "app",
        "db": tmp_path / "station.db",
    }


def _attempt(paths: dict[str, Path]) -> dict[str, str]:
    return reconciler.reconcile(
        journal_path=paths["journal"],
        app=paths["app"],
        database=paths["db"],
        lock_path=paths["lock"],
        approval_path=paths["approval"],
        require_root=False,
    )


def test_explicit_approved_attestation_preserves_history_and_allows_next_begin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, paths = _setup(tmp_path, monkeypatch)
    result = _attempt(paths)
    assert result["state"] == "reconciled"
    record = journal.read(paths["journal"])
    assert record["reconciliation"]["approval_id"] == "APPROVAL-001"
    assert record["reconciliation"]["outcome"] == "reviewed_existing_running_version_no_restore"
    with pytest.raises(ValueError, match="journal changed since inspection"):
        _attempt(paths)
    journal.begin(paths["journal"], TARGET, OLD, str(tmp_path / "next-backup.db"))
    assert journal.read(paths["journal"])["phase"] == "prepared"


@pytest.mark.parametrize(
    "mutation",
    [
        "expired",
        "wrong_transaction",
        "wrong_sha",
        "wrong_digest",
        "missing_running_attestation",
        "unknown_ui",
        "database_corrupt",
        "incompatible_schema",
        "qso_regression",
        "duplicate_process",
        "root_receipt_symlink",
        "loose_receipt_permissions",
    ],
)
def test_mismatch_blocks_and_leaves_journal_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    report, paths = _setup(tmp_path, monkeypatch)
    receipt = json.loads(paths["approval"].read_text(encoding="utf-8"))
    if mutation == "expired":
        receipt["expires_utc"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    elif mutation == "wrong_transaction":
        receipt["transaction_id"] = "other"
    elif mutation == "wrong_sha":
        receipt["expected_sha"] = OLD
    elif mutation == "wrong_digest":
        receipt["evidence_sha256"] = "0" * 64
    elif mutation == "missing_running_attestation":
        receipt["running_sha_independently_verified"] = False
    elif mutation == "unknown_ui":
        report["service"]["responsiveness"] = "unverified"
    elif mutation == "database_corrupt":
        report["database"]["integrity"] = "unknown"
    elif mutation == "incompatible_schema":
        report["schema_compatible_with_backup"] = False
    elif mutation == "qso_regression":
        report["contact_count_not_regressed"] = False
    elif mutation == "duplicate_process":
        report["service"]["state"] = "duplicate"
    elif mutation == "root_receipt_symlink":
        paths["approval"].unlink()
        paths["approval"].symlink_to(tmp_path / "unknown-file")
    elif mutation == "loose_receipt_permissions":
        paths["approval"].chmod(0o644)
    if mutation not in ("root_receipt_symlink", "loose_receipt_permissions"):
        paths["approval"].write_text(json.dumps(receipt), encoding="utf-8")
    before = paths["journal"].read_bytes()
    with pytest.raises((ValueError, OSError)):
        _attempt(paths)
    assert paths["journal"].read_bytes() == before


def test_exclusive_lock_prevents_reconciliation_during_deployment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, paths = _setup(tmp_path, monkeypatch)
    with paths["lock"].open("r+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match="lock held"):
            _attempt(paths)
    assert journal.read(paths["journal"])["phase"] == "prepared"


def test_reconciliation_rejects_contact_row_replacement_even_at_same_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A new contact cannot compensate for a removed prior QSO."""
    report, paths = _setup(tmp_path, monkeypatch)
    report["backup_contact_records_preserved"] = False
    with pytest.raises(ValueError, match="original QSO rows"):
        _attempt(paths)
    assert journal.read(paths["journal"])["phase"] == "prepared"
