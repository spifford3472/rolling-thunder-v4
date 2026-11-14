"""SIGKILL, failed synchronization and unsafe-path tests; sandbox files only."""

from __future__ import annotations

import importlib.util
import json
import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest

JOURNAL_SOURCE = (
    Path(__file__).resolve().parents[1] / "deploy/rolling-thunder-deployment-journal.py"
)
SPEC = importlib.util.spec_from_file_location("rt_stab06f_failure_journal", JOURNAL_SOURCE)
assert SPEC and SPEC.loader
journal = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(journal)
A = "a" * 40
B = "b" * 40


def _path(tmp_path: Path) -> Path:
    parent = tmp_path / "private"
    parent.mkdir(mode=0o700)
    return parent / "transaction.json"


def test_forced_sigkill_preserves_phase_and_refuses_next_transaction(tmp_path: Path) -> None:
    path = _path(tmp_path)
    code = (
        "import importlib.util,os,signal,sys; "
        "spec=importlib.util.spec_from_file_location('m',sys.argv[1]); "
        "m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m); "
        "from pathlib import Path; p=Path(sys.argv[2]); "
        "m.begin(p,'" + A + "','" + B + "','/backup/original.db'); "
        "m.advance(p,'stopping');m.advance(p,'backing_up'); "
        "os.kill(os.getpid(),signal.SIGKILL)"
    )
    child = subprocess.run(
        [sys.executable, "-c", code, str(JOURNAL_SOURCE), str(path)],
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )
    assert child.returncode == -signal.SIGKILL
    assert journal.read(path)["phase"] == "backing_up"
    with pytest.raises(journal.JournalError, match="unreconciled"):
        journal.begin(path, A, B, "/backup/new.db")


def test_fsync_failure_preserves_old_record_and_blocks_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _path(tmp_path)
    journal.begin(path, A, B, "/backup/original.db")
    before = path.read_bytes()

    def fail_fsync(_fd: int) -> None:
        raise OSError("simulated I/O failure before rename")

    monkeypatch.setattr(journal.os, "fsync", fail_fsync)
    with pytest.raises(OSError, match="simulated I/O"):
        journal.advance(path, "stopping")
    assert path.read_bytes() == before
    assert list(path.parent.glob(".transaction-*.tmp")) == []
    with pytest.raises(journal.JournalError, match="unreconciled"):
        journal.begin(path, A, B, "/backup/new.db")


def test_directory_fsync_failure_still_cannot_be_treated_committed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _path(tmp_path)
    journal.begin(path, A, B, "/backup/original.db")
    real_fsync = os.fsync
    calls = 0

    def fail_second_fsync(fd: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated parent directory sync failure")
        real_fsync(fd)

    monkeypatch.setattr(journal.os, "fsync", fail_second_fsync)
    with pytest.raises(OSError, match="directory sync failure"):
        journal.advance(path, "stopping")
    assert journal.read(path)["phase"] == "stopping"
    with pytest.raises(journal.JournalError, match="unreconciled"):
        journal.begin(path, A, B, "/backup/new.db")


def test_atomic_replace_failure_keeps_prior_journal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _path(tmp_path)
    journal.begin(path, A, B, "/backup/original.db")
    before = path.read_bytes()

    def fail_replace(_src: Path, _dst: Path) -> None:
        raise OSError("simulated interrupted rename")

    monkeypatch.setattr(journal.os, "replace", fail_replace)
    with pytest.raises(OSError, match="interrupted rename"):
        journal.advance(path, "stopping")
    assert path.read_bytes() == before
    assert list(path.parent.glob(".transaction-*.tmp")) == []


def test_malformed_journal_never_yields_success_or_reconciliation(tmp_path: Path) -> None:
    path = _path(tmp_path)
    path.write_text(json.dumps({"version": 1, "phase": "committed"}), encoding="utf-8")
    with pytest.raises(journal.JournalError, match="SHA"):
        journal.begin(path, A, B, "/backup/new.db")
