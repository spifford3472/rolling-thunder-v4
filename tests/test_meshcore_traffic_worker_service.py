"""Contract tests for the staged non-transmitting supervised traffic service."""

from __future__ import annotations

from pathlib import Path

UNIT = Path(__file__).resolve().parents[1] / "deploy/meshcore-traffic-worker.user.service"


def test_service_is_independent_bounded_and_analysis_only() -> None:
    """Supervision must not gain collector, UI, network or radio authority."""
    text = UNIT.read_text()
    assert "meshcore_traffic_worker_main" in text
    assert "--loop" in text
    assert "--poll-seconds 10" in text
    assert "--batch-size 25" in text
    assert "--traffic-slot 1" in text
    assert "meshcore-broker.sock" in text
    assert "rolling-thunder.token" in text
    assert "meshcore-traffic-ledger.db" in text
    assert "Restart=on-failure" in text
    assert "RestartSec=10" in text
    assert "TimeoutStopSec=20" in text
    assert "UMask=0077" in text
    assert "ProtectSystem=strict" in text
    assert "ProtectHome=read-only" in text
    assert "MemoryMax=128M" in text
    assert "CPUQuota=15%" in text
    assert "TasksMax=24" in text
    assert "IOWeight=50" in text
    assert "After=meshcore-collector.service" in text
    assert "Requires=rolling-thunder.service" not in text
    assert "ExecStartPre=" not in text
    assert "ExecStartPost=" not in text
    assert "--once" not in text
    assert "--device" not in text
    assert "--enable-message-broker" not in text
    assert "--transmit" not in text
    assert "--geocode" not in text
    assert "ListenStream=" not in text
    assert "ExecStop=" not in text
