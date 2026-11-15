"""Read-only recovery evidence collection, with no deployment or RF controls.

The standalone inspector uses fixed, read-only Git/systemd/SQLite calls and
never changes a deployment journal. The returned report is *evidence*, not an
authorization to resume deployments or to restore any database.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import pwd
import sqlite3
import stat
import subprocess
import time
from collections import Counter
from pathlib import Path
from typing import Any

DEFAULT_JOURNAL = Path("/var/lib/rolling-thunder-deploy/transaction.json")
DEFAULT_APP = Path("/home/geoff/projects/rolling-thunder-v4")
DEFAULT_DB = DEFAULT_APP / "config/data/rolling-thunder.db"
SERVICE = "rolling-thunder.service"


def _journal_reader() -> Any:
    """Load adjacent stable journal helper, not mutable application checkout."""
    path = Path(__file__).with_name("rolling-thunder-deployment-journal.py")
    spec = importlib.util.spec_from_file_location("rt_deployment_journal", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("stable deployment journal helper missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(*argv: str) -> str:
    """Capture a bounded read-only command; never use a shell."""
    return subprocess.run(
        argv,
        capture_output=True,
        text=True,
        check=True,
        timeout=4,
        env={"PATH": "/usr/bin:/bin", "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0"},
    ).stdout.strip()


def _private_file(path: Path) -> bool:
    """Refuse symlinks and nonregular files; leave bytes untouched."""
    try:
        metadata = path.lstat()
        return stat.S_ISREG(metadata.st_mode) and not path.is_symlink()
    except OSError:
        return False


def database_evidence(path: Path) -> dict[str, Any]:
    """Inspect SQLite using mode=ro; never initiate migrations or backups."""
    result: dict[str, Any] = {"path": str(path), "integrity": "unknown", "schema": "unknown"}
    if not _private_file(path):
        result["error"] = "missing_or_unsafe_database"
        return result
    # A conventional mode=ro SQLite connection can still initialize a WAL
    # shared-memory sidecar. Immutable mode guarantees no SQLite file writes,
    # but cannot safely inspect an active WAL. Refuse that case instead of
    # silently reading stale data and incorrectly approving reconciliation.
    wal = Path(str(path) + "-wal")
    if wal.exists() or wal.is_symlink():
        result["error"] = "wal_present_requires_parked_snapshot"
        return result
    try:
        initial = path.stat()
        with sqlite3.connect(
            path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True, timeout=2
        ) as db:
            db.execute("PRAGMA query_only=ON")
            db.execute("BEGIN")
            integrity = db.execute("PRAGMA integrity_check").fetchall()
            foreign = db.execute("PRAGMA foreign_key_check").fetchall()
            result["integrity"] = "ok" if integrity == [("ok",)] and not foreign else "failed"
            result["user_version"] = db.execute("PRAGMA user_version").fetchone()[0]
            schema = db.execute(
                "SELECT type, name, tbl_name, sql FROM sqlite_master "
                "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
            ).fetchall()
            result["schema"] = hashlib.sha256(
                json.dumps(schema, sort_keys=True).encode("utf-8")
            ).hexdigest()
            result["table_count"] = sum(1 for table in schema if table[0] == "table")
            # Compare durable contact counts without reading or exporting callsigns.
            if any(table[0] == "table" and table[1] == "contacts" for table in schema):
                result["contact_count"] = db.execute("SELECT COUNT(*) FROM contacts").fetchone()[0]
            else:
                result["contact_count"] = None
            try:
                metadata = db.execute("SELECT * FROM schema_metadata ORDER BY 1").fetchall()
                result["schema_metadata_hash"] = hashlib.sha256(
                    json.dumps(metadata, default=str).encode("utf-8")
                ).hexdigest()
            except sqlite3.DatabaseError:
                result["schema_metadata_hash"] = None
            db.execute("ROLLBACK")
        final = path.stat()
        if (
            (final.st_size, final.st_mtime_ns, final.st_ino)
            != (initial.st_size, initial.st_mtime_ns, initial.st_ino)
            or wal.exists()
            or wal.is_symlink()
        ):
            result["integrity"] = "unknown"
            result["error"] = "database_changed_during_readonly_inspection"
    except (sqlite3.DatabaseError, OSError, ValueError) as exc:
        result["error"] = type(exc).__name__
    return result


def backup_contacts_preserved(current: Path, backup: Path) -> bool:
    """Verify each saved backup contact row still exists, without exporting QSOs.

    A mere count comparison could miss deletion plus replacement. This check
    compares the full row multiset for compatible schema snapshots. Neither
    contact bodies nor hashes leave this process in the inspection report.
    """

    def contact_rows(path: Path) -> Counter[tuple[Any, ...]]:
        if not _private_file(path) or Path(str(path) + "-wal").exists():
            raise ValueError("unsafe or WAL-enabled database")
        before = path.stat()
        with sqlite3.connect(
            path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True, timeout=2
        ) as db:
            db.execute("PRAGMA query_only=ON")
            rows = Counter(tuple(row) for row in db.execute("SELECT * FROM contacts"))
        after = path.stat()
        if (before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ) or Path(str(path) + "-wal").exists():
            raise ValueError("database changed during verification")
        return rows

    try:
        prior = contact_rows(backup)
        present = contact_rows(current)
        return all(present[row] >= occurrences for row, occurrences in prior.items())
    except (sqlite3.DatabaseError, OSError, ValueError):
        return False


def _service_evidence(*, proc: Path, expected_user: str) -> dict[str, Any]:
    """Verify exact system-manager MainPID, user, cgroup and process identity."""
    result: dict[str, Any] = {"state": "unverified", "responsiveness": "unverified"}
    try:
        output = _run(
            "/usr/bin/systemctl",
            "show",
            SERVICE,
            "--no-pager",
            "-p",
            "ActiveState",
            "-p",
            "MainPID",
            "-p",
            "ControlGroup",
            "-p",
            "User",
        )
        values = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
        result.update({"active": values.get("ActiveState"), "pid": values.get("MainPID")})
        pid = int(values.get("MainPID", "0"))
        uid = pwd.getpwnam(expected_user).pw_uid
        group = f"/system.slice/{SERVICE}"
        if (
            pid <= 1
            or values.get("ActiveState") != "active"
            or values.get("User") != expected_user
            or values.get("ControlGroup") != group
        ):
            return result
        member = proc / str(pid)
        if (
            member.stat().st_uid != uid
            or member.joinpath("cgroup").read_text().strip() != "0::" + group
        ):
            return result
        argv = member.joinpath("cmdline").read_bytes().split(b"\0")
        if not any(
            part == b"rolling-thunder-ui" or part.endswith(b"/rolling-thunder-ui") for part in argv
        ):
            return result
        matches = []
        for child in proc.iterdir():
            if not child.name.isdigit():
                continue
            try:
                if child.stat().st_uid == uid:
                    cmd = child.joinpath("cmdline").read_bytes().split(b"\0")
                    if any(
                        arg == b"rolling-thunder-ui" or arg.endswith(b"/rolling-thunder-ui")
                        for arg in cmd
                    ):
                        matches.append(int(child.name))
            except (OSError, ValueError):
                continue
        if matches != [pid]:
            return result
        result["state"] = "single_expected_service_process"
        # A previous release can legitimately lack the new Tk marker. The
        # correct label is unverified, not healthy, and cannot authorize resume.
        marker = Path(f"/run/user/{uid}/rolling-thunder-ui-readiness.json")
        try:
            info = marker.lstat()
            payload = json.loads(marker.read_text(encoding="utf-8"))
            age = time.time() - float(payload["time"])
            if (
                stat.S_ISREG(info.st_mode)
                and info.st_uid == uid
                and info.st_mode & 0o077 == 0
                and info.st_size <= 128
                and type(payload["pid"]) is int
                and payload["pid"] == pid
                and 0 <= age <= 5
            ):
                result["responsiveness"] = "tk_heartbeat_fresh"
        except (OSError, ValueError, TypeError, KeyError):
            pass
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        pass
    return result


def inspect(
    journal_path: Path,
    app_dir: Path,
    db_path: Path,
    *,
    proc: Path = Path("/proc"),
    expected_user: str = "geoff",
) -> dict[str, Any]:
    """Collect evidence without changing any journal, Git, systemd or radio state."""
    evidence: dict[str, Any] = {
        "version": 1,
        "disposition": "blocked_manual_review",
        "journal": None,
        "git_sha": None,
        "service": {},
        "database": {},
        "backup": {},
        "radio_ptt_state": "not_independently_verified",
        "runtime_code_identity": {
            "loaded_python_bytes_independently_proven": False,
            "state": "unverified_mutable_or_unattested_runtime",
        },
    }
    try:
        reader = _journal_reader()
        try:
            evidence["journal"] = reader.read(journal_path)
        except (reader.JournalError, OSError, ValueError) as exc:
            evidence["journal_error"] = type(exc).__name__
    except (OSError, ValueError, RuntimeError) as exc:
        evidence["journal_error"] = type(exc).__name__
    try:
        if (app_dir / ".git").is_dir():
            commit = _run("/usr/bin/git", "-C", str(app_dir), "rev-parse", "--verify", "HEAD")
            if len(commit) == 40 and all(c in "0123456789abcdef" for c in commit):
                evidence["git_sha"] = commit
    except (OSError, subprocess.SubprocessError):
        pass
    evidence["service"] = _service_evidence(proc=proc, expected_user=expected_user)
    evidence["database"] = database_evidence(db_path)
    record = evidence["journal"]
    if isinstance(record, dict):
        backup = Path(record["backup_path"])
        evidence["backup"] = database_evidence(backup)
        evidence["contact_count_not_regressed"] = (
            isinstance(evidence["database"].get("contact_count"), int)
            and isinstance(evidence["backup"].get("contact_count"), int)
            and evidence["database"]["contact_count"] >= evidence["backup"]["contact_count"]
        )
        evidence["backup_contact_records_preserved"] = backup_contacts_preserved(db_path, backup)
        evidence["schema_compatible_with_backup"] = (
            evidence["database"].get("integrity") == "ok"
            and evidence["backup"].get("integrity") == "ok"
            and evidence["database"].get("schema") == evidence["backup"].get("schema")
            and evidence["database"].get("schema_metadata_hash")
            == evidence["backup"].get("schema_metadata_hash")
            and evidence["database"].get("user_version") == evidence["backup"].get("user_version")
        )
    # No inspection result automatically grants rollback or unlock authority.
    return evidence


def main() -> int:
    """CLI renders bounded JSON evidence, never performs recovery."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--journal", type=Path, default=DEFAULT_JOURNAL)
    parser.add_argument("--app", type=Path, default=DEFAULT_APP)
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    options = parser.parse_args()
    report = inspect(options.journal, options.app, options.database)
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0 if isinstance(report.get("journal"), dict) and "journal_error" not in report else 2


if __name__ == "__main__":
    raise SystemExit(main())
