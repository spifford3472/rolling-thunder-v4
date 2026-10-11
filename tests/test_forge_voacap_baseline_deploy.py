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
