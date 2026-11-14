"""Run a path-rewritten wrapper against fake commands, never production hosts."""

from __future__ import annotations

import fcntl
import os
import sqlite3
import subprocess
from pathlib import Path

CANDIDATE = Path(__file__).resolve().parents[1] / "deploy/rolling-thunder-deploy.candidate"
TARGET = "a" * 40
PREVIOUS = "b" * 40


def _fake(path: Path, body: str) -> None:
    path.write_text("#!/usr/bin/env bash\n" + body + "\n", encoding="utf-8")
    path.chmod(0o755)


def _sandbox(tmp_path: Path) -> tuple[Path, Path, Path, dict[str, str]]:
    """Rewrite all privileged locations and intercept every external mutator."""
    app = tmp_path / "app"
    (app / ".git").mkdir(parents=True)
    (app / "config" / "data").mkdir(parents=True)
    db = app / "config" / "data" / "rolling-thunder.db"
    with sqlite3.connect(db) as connection:
        connection.execute("CREATE TABLE schema_metadata (name TEXT PRIMARY KEY, version INT)")
        connection.execute("INSERT INTO schema_metadata VALUES ('schema', 22)")
        connection.execute("CREATE TABLE contacts (callsign TEXT)")
        connection.execute("INSERT INTO contacts VALUES ('KI5VNB')")
    (app / ".venv" / "bin").mkdir(parents=True)
    for name in ("python", "pip"):
        _fake(app / ".venv" / "bin" / name, "exit 0")
    backup = tmp_path / "backups"
    backup.mkdir()
    lock = tmp_path / "lock"
    trace = tmp_path / "mutations"
    bins = tmp_path / "fake-bin"
    bins.mkdir()
    _fake(bins / "id", "echo 0")
    _fake(bins / "sudo", 'shift 2\nexec "$@"')
    _fake(bins / "chown", "exit 0")
    sha = tmp_path / "current-sha"
    sha.write_text(PREVIOUS, encoding="utf-8")
    _fake(
        bins / "git",
        f'''echo "git $*" >> "{trace}"
case " $* " in
    *" status --porcelain "*) exit 0 ;;
    *" rev-parse HEAD "*) cat "{sha}"; exit 0 ;;
    *" branch -r --contains "*) echo origin/main; exit 0 ;;
    *" checkout "*) echo "${{@: -1}}" > "{sha}"; exit 0 ;;
esac
exit 0''',
    )
    _fake(bins / "systemctl", f'echo "systemctl $*" >> "{trace}"\nexit 0')
    _fake(bins / "python3", "cat >/dev/null\nexit 17")
    text = CANDIDATE.read_text(encoding="utf-8")
    text = text.replace("/home/geoff/projects/rolling-thunder-v4", str(app))
    text = text.replace("/var/backups/rolling-thunder-deploy", str(backup))
    text = text.replace("/run/rolling-thunder-deploy.lock", str(lock))
    text = text.replace(
        '/usr/bin/python3 - "$DB_PATH" "$BACKUP_PATH"',
        f'{bins / "python3"} - "$DB_PATH" "$BACKUP_PATH"',
    )
    text = text.replace(
        '"$(/usr/bin/stat -c %u "$LOCK_PATH")" == 0',
        f'"$(/usr/bin/stat -c %u "$LOCK_PATH")" == {os.getuid()}',
    )
    assert "/home/geoff/projects/rolling-thunder-v4" not in text
    assert "/var/backups/rolling-thunder-deploy" not in text
    assert "/run/rolling-thunder-deploy.lock" not in text
    wrapper = tmp_path / "candidate"
    wrapper.write_text(text, encoding="utf-8")
    env = os.environ.copy()
    env["PATH"] = str(bins) + os.pathsep + env["PATH"]
    return wrapper, lock, trace, env


def test_concurrent_wrapper_refuses_before_any_git_or_service_action(tmp_path: Path) -> None:
    wrapper, lock, trace, env = _sandbox(tmp_path)
    with lock.open("w", encoding="utf-8") as descriptor:
        lock.chmod(0o600)
        fcntl.flock(descriptor.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = subprocess.run(
            ["bash", str(wrapper), TARGET],
            env=env,
            text=True,
            capture_output=True,
            check=False,
            timeout=5,
        )
    assert result.returncode != 0
    assert "deployment already in progress" in result.stdout
    assert not trace.exists(), "overlapping deployment touched Git or systemctl"


def test_backup_failure_attempts_old_service_recovery_without_checkout(tmp_path: Path) -> None:
    wrapper, _, trace, env = _sandbox(tmp_path)
    result = subprocess.run(
        ["bash", str(wrapper), TARGET],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=5,
    )
    assert result.returncode != 0
    assert "database backup failed" in result.stdout
    commands = trace.read_text(encoding="utf-8")
    assert "systemctl stop rolling-thunder.service" in commands
    assert "systemctl start rolling-thunder.service" in commands
    assert "checkout" not in commands


def test_malformed_sha_refused_before_mutation(tmp_path: Path) -> None:
    wrapper, _, trace, env = _sandbox(tmp_path)
    result = subprocess.run(
        ["bash", str(wrapper), "NOT_A_SHA"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=5,
    )
    assert result.returncode != 0
    assert "40-character lowercase" in result.stdout
    assert not trace.exists()


def test_schema_changing_migration_refuses_destructive_rollback(tmp_path: Path) -> None:
    """No old-code restart or data restore after migration changes SQLite schema."""
    wrapper, _, trace, env = _sandbox(tmp_path)
    bins = tmp_path / "fake-bin"
    app = tmp_path / "app"
    wrapper.write_text(
        wrapper.read_text(encoding="utf-8").replace(
            str(bins / "python3") + ' - "$DB_PATH" "$BACKUP_PATH"',
            '/usr/bin/python3 - "$DB_PATH" "$BACKUP_PATH"',
        ),
        encoding="utf-8",
    )
    _fake(
        app / ".venv" / "bin" / "python",
        """if [[ $1 == "-" ]]; then
    /usr/bin/python3 -c 'import sqlite3,sys; d=sqlite3.connect(sys.argv[1]); d.execute("CREATE TABLE migrated (id INT)"); d.commit()' "$2"
    exit 18
fi
exit 0""",
    )
    result = subprocess.run(
        ["bash", str(wrapper), TARGET],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=8,
    )
    assert result.returncode != 0
    assert "ROLLBACK BLOCKED" in result.stderr
    assert "schema/integrity check failed" in result.stderr
    lines = trace.read_text(encoding="utf-8")
    assert f"checkout --detach --force {TARGET}" in lines
    assert f"checkout --detach --force {PREVIOUS}" not in lines
    assert "systemctl restart" not in lines
    with sqlite3.connect(app / "config" / "data" / "rolling-thunder.db") as db:
        assert db.execute("SELECT callsign FROM contacts").fetchone() == ("KI5VNB",)
        assert db.execute("SELECT name FROM sqlite_master WHERE name='migrated'").fetchone() == (
            "migrated",
        )


def test_failed_service_start_restores_old_code_without_replacing_database(tmp_path: Path) -> None:
    """Rollback keeps the live DB and attempts the previous verified code SHA."""
    wrapper, _, trace, env = _sandbox(tmp_path)
    bins = tmp_path / "fake-bin"
    wrapper.write_text(
        wrapper.read_text(encoding="utf-8").replace(
            str(bins / "python3") + ' - "$DB_PATH" "$BACKUP_PATH"',
            '/usr/bin/python3 - "$DB_PATH" "$BACKUP_PATH"',
        ),
        encoding="utf-8",
    )
    _fake(bins / "systemctl", f'echo "systemctl $*" >> "{trace}"\n[[ $1 != start ]]')
    result = subprocess.run(
        ["bash", str(wrapper), TARGET],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=8,
    )
    assert result.returncode != 0
    trace_text = trace.read_text(encoding="utf-8")
    assert f"checkout --detach --force {TARGET}" in trace_text
    assert f"checkout --detach --force {PREVIOUS}" in trace_text
    assert "systemctl restart rolling-thunder.service" in trace_text
    assert (tmp_path / "current-sha").read_text(encoding="utf-8").strip() == PREVIOUS
    with sqlite3.connect(tmp_path / "app" / "config" / "data" / "rolling-thunder.db") as db:
        assert db.execute("SELECT callsign FROM contacts").fetchone() == ("KI5VNB",)
