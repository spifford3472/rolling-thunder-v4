import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_scripts_parse_and_preserve_three_gates() -> None:
    for name in ("stage-forge-voacap-baseline.sh", "install-forge-voacap-baseline.sh"):
        path = ROOT / "deploy/scripts" / name
        assert subprocess.run(["bash", "-n", str(path)], check=False).returncode == 0
    install = (ROOT / "deploy/scripts/install-forge-voacap-baseline.sh").read_text()
    assert "v.get('process_enabled') is False" in install
    assert "v.get('scheduler_enabled') is False" in install
    assert "v.get('provider_enabled') is False" in install
    assert "trap rollback ERR" in install
    assert "chmod a+r,go-w" in install
    assert "rolling-thunder-forge-propagation-qso-worker" not in install


def test_systemd_sandbox_limits_writes_and_network_to_c4_loopback() -> None:
    service = (ROOT / "deploy/systemd/rolling-thunder-forge-voacap-baseline.service").read_text()
    assert "User=rolling-thunder-propagation" in service
    assert "ProtectSystem=strict" in service
    assert "ReadWritePaths=/var/lib/rolling-thunder-forge-propagation" in service
    assert "IPAddressAllow=localhost" in service
    assert "IPAddressDeny=any" in service
    assert "CapabilityBoundingSet=" in service
    assert "/var/lib/rolling-thunder-forge-propagation-qso" not in service


def test_installer_preflights_venv_access_before_link_or_systemd_mutation() -> None:
    install = (ROOT / "deploy/scripts/install-forge-voacap-baseline.sh").read_text()
    directory_permissions = 'find "$RELEASE" -type d -exec chmod 0755 {} +'
    file_permissions = 'find "$RELEASE" -type f -exec chmod a+r,go-w {} +'
    launcher_preflight = (
        '"$RELEASE/.venv/bin/rolling-thunder-forge-voacap-baseline" '
        '--config "$CONFIG" --check-config'
    )
    current_link = 'ln -s "releases/$SHA" "$ROOT/current"'
    unit_install = 'install -o root -g root -m 0644 "$STAGE/$SERVICE"'
    assert install.index(directory_permissions) < install.index(launcher_preflight)
    assert install.index(file_permissions) < install.index(launcher_preflight)
    assert install.index(launcher_preflight) < install.index(unit_install)
    assert install.index(launcher_preflight) < install.index(current_link)
    assert install.index("trap rollback ERR") < install.index(unit_install)

def test_upgrade_script_preserves_existing_release_and_fails_closed() -> None:
    path = ROOT / "deploy/scripts/upgrade-forge-voacap-baseline.sh"
    assert subprocess.run(["bash", "-n", str(path)], check=False).returncode == 0
    script = path.read_text()
    assert "ssn_snapshot_path" in script
    assert "trap rollback ERR" in script
    assert "mv -Tf" in script
    assert 'previous-release' in script
    assert 'cp -p "$CONFIG" "$BACKUP/config.json"' in script
    assert 'all(v.get(g) is False' in script
    assert 'systemctl stop "$TIMER"' in script
    assert 'systemctl start "$SERVICE"' in script
    assert 'systemctl enable --now "$TIMER"' in script
    assert "systemctl disable --now" not in script
