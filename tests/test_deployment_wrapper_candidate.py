"""Nonprivileged contract checks for the captured deployment-wrapper candidate."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = ROOT / "deploy" / "rolling-thunder-deploy.candidate"


def test_candidate_is_valid_bash_without_execution() -> None:
    """Verify syntax only; never invoke the root-level deployment transaction."""
    result = subprocess.run(
        ["bash", "-n", str(CANDIDATE)], check=False, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert not (CANDIDATE.stat().st_mode & 0o111), "candidate must remain nonexecutable"


def test_lock_covers_first_mutation_through_rollback() -> None:
    """The same inherited lock must protect fetch, stop, and rollback."""
    script = CANDIDATE.read_text(encoding="utf-8")
    assert "LOCK_PATH=/run/rolling-thunder-deploy.lock" in script
    assert '[[ ! -L "$LOCK_PATH" ]]' in script
    lock = script.index("/usr/bin/flock -n 9")
    fetch = script.index('git -C "$APP_DIR" fetch --prune origin')
    stop = (
        script.index('systemctl stop "$SERVICE"\\\n')
        if 'systemctl stop "$SERVICE"\\\n' in script
        else script.index('systemctl stop "$SERVICE"')
    )
    rollback = script.index("rollback() {")
    assert lock < fetch < rollback
    assert lock < stop
    assert 'exec 9>>"$LOCK_PATH"' in script
    assert "flock -u" not in script


def test_preflight_and_backup_failure_recovery_are_explicit() -> None:
    """Known failures must not continue into checkout or falsely report success."""
    script = CANDIDATE.read_text(encoding="utf-8")
    preflight = script.index('[[ -d "$BACKUP_DIR" && -w "$BACKUP_DIR" ]]')
    stop = script.index('log "stopping $SERVICE"')
    assert preflight < stop
    assert "failed to restart prior service after backup failure" in script
    assert "failed to restart prior service after backup permission failure" in script
    assert 'chmod 600 "$BACKUP_PATH"' in script
    assert 'chown root:root "$BACKUP_PATH"' in script


def test_candidate_replaces_weak_three_second_readiness_check() -> None:
    """Do not equate systemd active with a responding Tk event loop."""
    script = CANDIDATE.read_text(encoding="utf-8")
    assert "sleep 3" not in script
    assert "rolling_thunder.deployment_readiness --timeout 210" in script
    assert "supervised dashboard did not become responsive" in script
