"""Adapt composed runtime services into pure connectivity presentation state."""

from typing import Protocol

from rolling_thunder.connectivity_status import ConnectivityStatus, build_connectivity_status
from rolling_thunder.contact_sync import ContactSyncService
from rolling_thunder.home_platform_health import HomePlatformHealthService
from rolling_thunder.network_keepalive import NetworkKeepaliveService


class ConnectivityRuntime(Protocol):
    """Runtime service surface needed by connectivity presentation."""

    home_platform_health: HomePlatformHealthService | None
    contact_sync: ContactSyncService | None
    network_keepalive: NetworkKeepaliveService | None


def build_runtime_connectivity_status(
    runtime: ConnectivityRuntime,
    *,
    network_enabled: bool,
    platform_enabled: bool,
) -> ConnectivityStatus:
    """Build one immutable connectivity snapshot without performing I/O."""
    network_state = (
        runtime.network_keepalive.latest_state
        if runtime.network_keepalive is not None
        else None
    )
    platform_state = (
        runtime.home_platform_health.latest_state
        if runtime.home_platform_health is not None
        else None
    )
    sync_result = (
        runtime.contact_sync.latest_result
        if runtime.contact_sync is not None
        else None
    )

    return build_connectivity_status(
        network_enabled=network_enabled,
        platform_enabled=platform_enabled,
        network_state=network_state,
        platform_state=platform_state,
        sync_result=sync_result,
    )
