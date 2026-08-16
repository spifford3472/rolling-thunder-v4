"""Tests for DMR deployment configuration and dashboard composition wiring."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from rolling_thunder.config import ApplicationConfig, OperatorConfig, load_config
from rolling_thunder.dmr_dashboard_config import DmrHotspotConfig
from rolling_thunder.dmr_dashboard_runtime import (
    build_dmr_panel_runtime,
    dmr_grid_from_gps_state,
)
from rolling_thunder.domain import GPSFixState, GPSPosition
from rolling_thunder.gps import GPSConnectionState, GPSState
from rolling_thunder.maidenhead import maidenhead_grid

NOW = datetime(2026, 8, 16, 4, 30, tzinfo=UTC)


def test_dmr_config_defaults_disabled() -> None:
    config = ApplicationConfig(
        operator=OperatorConfig(callsign="KI5VNB", home_grid="EM79xm")
    )

    assert config.dmr.enabled is False
    assert config.dmr.host is None
    assert config.dmr.private_key is None
    assert config.dmr.history_limit == 20


def test_enabled_dmr_requires_host_and_private_key() -> None:
    with pytest.raises(ValidationError):
        DmrHotspotConfig(enabled=True)


def test_load_config_resolves_relative_dmr_key(tmp_path: Path) -> None:
    path = tmp_path / "rolling-thunder.yaml"
    path.write_text(
        """
operator:
  callsign: KI5VNB
  home_grid: EM79xm
dmr:
  enabled: true
  host: 192.168.8.235
  ssh_user: pi-star
  private_key: keys/id_ed25519_rollingthunder_dmr
""",
        encoding="utf-8",
    )

    config = load_config(path)

    assert config.dmr.enabled
    assert config.dmr.host == "192.168.8.235"
    assert config.dmr.private_key == (
        tmp_path / "keys/id_ed25519_rollingthunder_dmr"
    ).resolve()


def test_grid_provider_uses_only_connected_position_fix() -> None:
    position = GPSPosition(
        fix_state=GPSFixState.THREE_DIMENSIONAL,
        latitude=39.75,
        longitude=-84.20,
        updated_at=NOW,
    )
    state = GPSState(
        connection_state=GPSConnectionState.CONNECTED,
        position=position,
        updated_at=NOW,
    )

    assert dmr_grid_from_gps_state(state) == maidenhead_grid(39.75, -84.20)
    assert dmr_grid_from_gps_state(None) is None


def test_disabled_dmr_builds_no_runtime(tmp_path: Path) -> None:
    runtime = build_dmr_panel_runtime(
        DmrHotspotConfig(),
        database_path=tmp_path / "contacts.db",
        gps_state_provider=lambda: None,
    )

    assert runtime is None


def test_ui_main_contains_complete_dmr_lifecycle_wiring() -> None:
    source = Path("src/rolling_thunder/ui_main.py").read_text(encoding="utf-8")

    for required in (
        "build_dmr_panel_runtime(",
        "dmr_panel_runtime.start()",
        "DmrAwareActivePanelCommands(",
        "DmrWidgets(context_content)",
        "dmr_panel_runtime.synchronize_commit_events()",
        "build_dmr_viewport(",
        "dmr_panel_runtime.stop()",
    ):
        assert required in source
