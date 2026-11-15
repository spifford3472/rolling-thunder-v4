"""Hardware-free crash recovery journal tests on isolated private directories."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "deploy/rolling-thunder-deployment-journal.py"
SPEC = importlib.util.spec_from_file_location("rt_deployment_journal", SOURCE)
assert SPEC and SPEC.loader
journal = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(journal)
OLD = "a" * 40
NEW = "b" * 40


def _path(tmp_path: Path) -> Path:
    directory = tmp_path / "private"
    directory.mkdir(mode=0o700, parents=True)
    return directory / "transaction.json"


def _cli(path: Path, operation: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SOURCE), operation, str(path), *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=4,
    )


def test_crash_in_any_mutating_phase_blocks_new_transaction(tmp_path: Path) -> None:
    """Journal persists after a killed worker; no automatic code/data rollback."""
    for phase in [
        "prepared",
        "stopping",
        "backing_up",
        "checkout",
        "installing",
        "migrating",
        "starting",
        "verifying",
        "rolling_back",
    ]:
        path = _path(tmp_path / phase)
        assert _cli(path, "begin", OLD, NEW, "/backup/original.db").returncode == 0
        for current in (
            "stopping",
            "backing_up",
            "checkout",
            "installing",
            "migrating",
            "starting",
            "verifying",
        ):
            if current == phase or phase == "prepared":
                break
            assert _cli(path, "phase", current).returncode == 0
        if phase == "rolling_back":
            assert _cli(path, "phase", "rolling_back").returncode == 0
        elif phase != "prepared":
            assert _cli(path, "phase", phase).returncode == 0
        persisted = json.loads(path.read_text(encoding="utf-8"))
        assert persisted["phase"] == phase
        assert _cli(path, "begin", OLD, NEW, "/backup/another.db").returncode == 75
        assert json.loads(path.read_text(encoding="utf-8")) == persisted


def test_committed_record_is_retained_and_next_transaction_allowed(tmp_path: Path) -> None:
    path = _path(tmp_path)
    journal.begin(path, OLD, NEW, "/backup/pre.db")
    for phase in (
        "stopping",
        "backing_up",
        "checkout",
        "installing",
        "migrating",
        "starting",
        "verifying",
    ):
        journal.advance(path, phase)
    journal.commit(path)
    committed = journal.read(path)
    assert committed is not None and committed["phase"] == "committed"
    journal.begin(path, NEW, OLD, "/backup/next.db")
    assert journal.read(path)["phase"] == "prepared"


def test_bad_and_skipped_transitions_refused(tmp_path: Path) -> None:
    path = _path(tmp_path)
    journal.begin(path, OLD, NEW, "/backup/pre.db")
    with pytest.raises(journal.JournalError):
        journal.advance(path, "checkout")
    with pytest.raises(journal.JournalError):
        journal.commit(path)
    journal.advance(path, "rolling_back")
    with pytest.raises(journal.JournalError):
        journal.advance(path, "starting")
    with pytest.raises(journal.JournalError):
        journal.commit(path)


def test_corrupted_or_malicious_journal_blocks_deploy(tmp_path: Path) -> None:
    path = _path(tmp_path)
    path.write_text("{bad json", encoding="utf-8")
    assert _cli(path, "begin", OLD, NEW, "/backup/a.db").returncode == 75
    path.unlink()
    destination = tmp_path / "must-not-change"
    destination.write_text("preserve", encoding="utf-8")
    path.symlink_to(destination)
    assert _cli(path, "begin", OLD, NEW, "/backup/a.db").returncode == 75
    assert destination.read_text(encoding="utf-8") == "preserve"


def test_public_directory_refused_and_atomic_file_private(tmp_path: Path) -> None:
    path = _path(tmp_path)
    journal.begin(path, OLD, NEW, "/backup/pre.db")
    assert path.stat().st_mode & 0o777 == 0o600
    assert list(path.parent.glob(".transaction-*.tmp")) == []
    path.parent.chmod(0o777)
    assert _cli(path, "phase", "stopping").returncode == 75
    path.parent.chmod(0o700)
    assert journal.read(path)["phase"] == "prepared"


def test_no_resolve_or_force_clear_interface(tmp_path: Path) -> None:
    path = _path(tmp_path)
    journal.begin(path, OLD, NEW, "/backup/pre.db")
    assert _cli(path, "reconcile").returncode != 0
    assert _cli(path, "commit").returncode == 75
    assert journal.read(path)["phase"] == "prepared"


def test_reconciled_history_is_archived_before_new_transaction(tmp_path: Path) -> None:
    """A new deployment must not erase the prior approval and recovery record."""
    path = _path(tmp_path)
    journal.begin(path, OLD, NEW, "/backup/original.db")
    record = journal.read(path)
    journal.attest_reconciled(
        path, transaction_id=record["transaction_id"],
        approval_id="APPROVAL-RECOVERY", evidence_hash="c" * 64, verified_sha=OLD,
    )
    closed = journal.read(path)
    journal.begin(path, OLD, NEW, "/backup/another.db")
    archive = path.parent / f"history-{record['transaction_id']}.json"
    assert archive.exists()
    assert json.loads(archive.read_text(encoding="utf-8")) == closed
    assert archive.stat().st_mode & 0o777 == 0o600
    assert journal.read(path)["phase"] == "prepared"
    assert journal.read(path)["transaction_id"] != record["transaction_id"]


def test_conflicting_transaction_archive_blocks_replacement(tmp_path: Path) -> None:
    """Potentially forged history cannot silently be overwritten."""
    path = _path(tmp_path)
    journal.begin(path, OLD, NEW, "/backup/original.db")
    record = journal.read(path)
    for phase in ("stopping", "backing_up", "checkout", "installing", "migrating", "starting", "verifying"):
        journal.advance(path, phase)
    journal.commit(path)
    archive = path.parent / f"history-{record['transaction_id']}.json"
    archive.write_text("tampered", encoding="utf-8")
    archive.chmod(0o600)
    with pytest.raises(journal.JournalError, match="archive mismatch"):
        journal.begin(path, OLD, NEW, "/backup/another.db")
    assert journal.read(path)["phase"] == "committed"
    assert archive.read_text(encoding="utf-8") == "tampered"
