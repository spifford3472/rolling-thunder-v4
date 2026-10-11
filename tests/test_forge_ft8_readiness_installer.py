"""Privileged commissioning helper is reviewed as a candidate, never executed as root."""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_proposed_root_helper_requires_exact_release_and_no_provider_or_radio() -> None:
    script = ROOT / "deploy/scripts/install-forge-ft8-readiness.sh"
    source = script.read_text()
    assert "EUID -eq 0" in source
    assert "^" in source and "[0-9a-f]{40}" in source
    assert "sha256sum -c SHA256SUMS" in source
    assert "--no-index" in source
    assert "--help" in source
    assert "rolling-thunder-forge-ft8-readiness-preflight" in source
    assert "'OFF'" in source
    assert "suggested_start_watts" in source
    assert "trap rollback ERR" in source
    assert "systemctl enable --now" in source
    assert "systemctl start" in source
    assert "rolling-thunder-forge-ft8-readiness" in source
    assert "propagation-qso-worker.service" not in source
    assert "rolling-thunder-deploy" not in source
    assert subprocess.run(["bash", "-n", str(script)], check=False).returncode == 0


def test_service_supports_c3_and_c4_read_groups() -> None:
    unit = (ROOT / "deploy/systemd/rolling-thunder-forge-ft8-readiness.service").read_text()
    assert "SupplementaryGroups=rolling-thunder-propagation-qso rolling-thunder-propagation" in unit
    assert "IPAddressDeny=any" in unit


def test_stage_and_rollback_helpers_parse_and_scope_to_readiness() -> None:
    for name in ("stage-forge-ft8-readiness.sh", "rollback-forge-ft8-readiness.sh"):
        path = ROOT / "deploy/scripts" / name
        script = path.read_text()
        assert subprocess.run(["bash", "-n", str(path)], check=False).returncode == 0
        assert "rolling-thunder-forge-deploy" in script or "forge-ft8-readiness" in script
        assert "propagation-qso-worker.service" not in script
    rollback = (ROOT / "deploy/scripts/rollback-forge-ft8-readiness.sh").read_text()
    assert "systemctl disable --now" in rollback
    assert "previous-current" in rollback
    assert "systemctl daemon-reload" in rollback
    stage = (ROOT / "deploy/scripts/stage-forge-ft8-readiness.sh").read_text()
    assert "git -C" in stage and "archive" in stage and "--no-index" in stage
    assert "SHA256SUMS" in stage
