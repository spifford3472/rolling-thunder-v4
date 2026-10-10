"""Deployment regression: imports must be checked using the runtime identity."""

from pathlib import Path


def test_package_permissions_gate_runs_as_service_user():
    script = Path(__file__).resolve().parents[1] / "scripts/forge-contact-sync-package-permissions.sh"
    contents = script.read_text()
    assert 'chgrp -R rollingthunder' in contents
    assert 'chmod -R g+rX' in contents
    assert 'runuser -u rollingthunder' in contents
    assert 'systemctl restart' not in contents


def test_import_probe_includes_service_and_ft8_api():
    script = Path(__file__).resolve().parents[1] / "scripts/verify-forge-python-access.py"
    contents = script.read_text()
    assert 'rolling_thunder.forge_contact_sync_main' in contents
    assert 'rolling_thunder.forge_ft8_periods' in contents
