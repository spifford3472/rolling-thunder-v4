from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "deploy" / "systemd"


def test_sampler_requires_fresh_noaa_success_before_running() -> None:
    unit = (ROOT / "rolling-thunder-forge-voacap-baseline.service").read_text()
    assert "Requires=rolling-thunder-forge-noaa-refresh.service" in unit
    assert "After=local-fs.target rolling-thunder-forge-noaa-refresh.service" in unit
    assert "User=rolling-thunder-propagation" in unit
    assert "IPAddressAllow=localhost" in unit


def test_noaa_refresh_is_separately_privileged_and_software_only() -> None:
    unit = (ROOT / "rolling-thunder-forge-noaa-refresh.service").read_text()
    assert "User=rolling-thunder-noaa" in unit
    assert "--apply" in unit
    assert "forge_voacap_noaa_refresh_main" in unit
    assert "ProtectSystem=strict" in unit
    assert "ReadWritePaths=/var/lib/rolling-thunder-noaa" in unit
    assert "--environment-output /var/lib/rolling-thunder-noaa/environment.json" in unit
    assert "--snapshot-output /var/lib/rolling-thunder-noaa/noaa-snapshot.json" in unit
    assert "voacap-service" not in unit
    timer = (ROOT / "rolling-thunder-forge-noaa-refresh.timer").read_text()
    assert "OnCalendar=*-*-* 00,06,12,18:00:00 UTC" in timer
