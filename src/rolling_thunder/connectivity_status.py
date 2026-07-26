"""Pure connectivity read model for dashboard presentation."""

from dataclasses import dataclass

from rolling_thunder.contact_sync import ContactSyncResult
from rolling_thunder.home_platform import HomePlatformAvailability, HomePlatformState
from rolling_thunder.network_keepalive import (
    NetworkKeepaliveAvailability,
    NetworkKeepaliveState,
)


@dataclass(frozen=True)
class ConnectivityStatus:
    """Stable operator-facing connectivity and synchronization text."""

    network: str
    home_platform: str
    synchronization: str
    detail: str


def build_connectivity_status(
    *,
    network_enabled: bool,
    platform_enabled: bool,
    network_state: NetworkKeepaliveState | None = None,
    platform_state: HomePlatformState | None = None,
    sync_result: ContactSyncResult | None = None,
) -> ConnectivityStatus:
    """Convert service snapshots into concise dashboard text without I/O."""
    if not network_enabled:
        network = "DISABLED"
    elif network_state is None or (
        network_state.availability is NetworkKeepaliveAvailability.UNKNOWN
    ):
        network = "UNKNOWN"
    elif network_state.availability is NetworkKeepaliveAvailability.REACHABLE:
        network = "ONLINE"
    else:
        network = "OFFLINE"

    if not platform_enabled:
        platform = "DISABLED"
    elif platform_state is None or (
        platform_state.availability is HomePlatformAvailability.UNKNOWN
    ):
        platform = "UNKNOWN"
    elif platform_state.availability is HomePlatformAvailability.AVAILABLE:
        platform = "ONLINE"
    else:
        platform = "OFFLINE"

    if not platform_enabled:
        synchronization = "DISABLED"
    elif sync_result is None:
        synchronization = "IDLE"
    else:
        synchronization = (
            f"{sync_result.synchronized} SYNCED / "
            f"{sync_result.failed} RETRYING"
        )

    errors = []
    if network_state is not None and network_state.last_error:
        errors.append(f"NETWORK: {network_state.last_error}")
    if platform_state is not None and platform_state.last_error:
        errors.append(f"PLATFORM: {platform_state.last_error}")

    return ConnectivityStatus(
        network=network,
        home_platform=platform,
        synchronization=synchronization,
        detail=" — ".join(errors) if errors else "CONNECTIVITY READY",
    )
