"""Static safety gates for operator-run FT8-P1 Pi release script."""
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'deploy/rolling-thunder-ft8-p1-pi-cutover'


def test_cutover_requires_operator_flag_and_preflight():
    source = SCRIPT.read_text()
    assert '--preflight' in source
    assert '--deploy-approved' in source
    assert 'git merge-base --is-ancestor "$TARGET" origin/main' in source
    assert 'git status --porcelain' in source
    assert 'if [[ "$MODE" == --preflight ]]' in source


def test_rollback_does_not_restore_sqlite_or_drop_wal():
    source = SCRIPT.read_text()
    assert 'ROLLBACK' not in source or 'database' in source
    assert 'cp -f "$BACKUP' not in source
    assert 'rm -f "${DB}' not in source
    assert 'cp -p "$BACKUP/rolling-thunder.yaml" "$CONFIG"' in source
    assert 'git checkout --detach --force "$PREVIOUS"' in source


def test_ft8_transmit_is_disabled_before_restart():
    source = SCRIPT.read_text()
    assert "obj['ft8']['transmit']['enabled']=False" in source
    assert "assert not cfg.ft8.transmit.enabled" in source
    assert source.index("assert not cfg.ft8.transmit.enabled") < source.rindex('sudo -n systemctl start "$SERVICE"')
