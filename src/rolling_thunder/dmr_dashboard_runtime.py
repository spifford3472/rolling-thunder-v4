"""Dashboard composition helpers for the optional DMR hotspot panel."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from rolling_thunder.dmr_dashboard_config import DmrHotspotConfig
from rolling_thunder.dmr_panel_runtime import DmrPanelRuntime
from rolling_thunder.domain import GPSFixState
from rolling_thunder.gps import GPSConnectionState, GPSState
from rolling_thunder.maidenhead import maidenhead_grid
from rolling_thunder.value_types import MaidenheadGrid


def dmr_grid_from_gps_state(gps_state: GPSState | None) -> MaidenheadGrid | None:
    """Return the current six-character grid only from a usable GPS fix."""
    if gps_state is None or gps_state.connection_state is not GPSConnectionState.CONNECTED:
        return None
    position = gps_state.position
    if position is None or position.fix_state is GPSFixState.NO_FIX:
        return None
    if position.latitude is None or position.longitude is None:
        return None
    return maidenhead_grid(position.latitude, position.longitude)


def build_dmr_panel_runtime(
    config: DmrHotspotConfig,
    *,
    database_path: Path,
    gps_state_provider: Callable[[], GPSState | None],
) -> DmrPanelRuntime | None:
    """Build the DMR runtime when enabled without starting any network activity."""
    if not config.enabled:
        return None
    host = config.host
    private_key = config.private_key
    if host is None or private_key is None:
        raise ValueError("Enabled DMR hotspot configuration is incomplete.")
    return DmrPanelRuntime.build(
        database_path=database_path,
        hotspot_host=host,
        ssh_user=config.ssh_user,
        private_key=private_key,
        my_grid_provider=lambda: dmr_grid_from_gps_state(gps_state_provider()),
        http_timeout_s=config.http_timeout_s,
        connect_timeout_s=config.connect_timeout_s,
        history_limit=config.history_limit,
        history_refresh_interval_s=config.history_refresh_interval_s,
        reconnect_delay_s=config.reconnect_delay_s,
    )
