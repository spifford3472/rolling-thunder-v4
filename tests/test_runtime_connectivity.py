"""Tests for adapting runtime services into connectivity presentation state."""

from dataclasses import dataclass
from datetime import UTC, datetime

from rolling_thunder.contact_sync import ContactSyncResult
from rolling_thunder.home_platform import HomePlatformAvailability, HomePlatformState
from rolling_thunder.network_keepalive import (
    NetworkKeepaliveAvailability,
    NetworkKeepaliveState,
)
from rolling_thunder.runtime_connectivity import build_runtime_connectivity_status

_FIXED_TIME = datetime(2026, 7, 26, 22, 0, tzinfo=UTC)


@dataclass
class _StateHolder:
    latest_state: object


@dataclass
class _ResultHolder:
    latest_result: ContactSyncResult


@dataclass
class _Runtime:
    home_platform_health: object | None = None
    contact_sync: object | None = None
    network_keepalive: object | None = None


def test_disabled_services_produce_disabled_status() -> None:
    status = build_runtime_connectivity_status(
        _Runtime(),
        network_enabled=False,
        platform_enabled=False,
    )

    assert status.network == "DISABLED"
    assert status.home_platform == "DISABLED"
    assert status.synchronization == "DISABLED"


def test_runtime_snapshots_are_adapted_without_io() -> None:
    runtime = _Runtime(
        network_keepalive=_StateHolder(
            NetworkKeepaliveState(
                availability=NetworkKeepaliveAvailability.REACHABLE,
                checked_at=_FIXED_TIME,
                last_success_at=_FIXED_TIME,
            )
        ),
        home_platform_health=_StateHolder(
            HomePlatformState(
                availability=HomePlatformAvailability.AVAILABLE,
                checked_at=_FIXED_TIME,
            )
        ),
        contact_sync=_ResultHolder(
            ContactSyncResult(attempted=3, synchronized=2, failed=1)
        ),
    )

    status = build_runtime_connectivity_status(
        runtime,
        network_enabled=True,
        platform_enabled=True,
    )

    assert status.network == "ONLINE"
    assert status.home_platform == "ONLINE"
    assert status.synchronization == "2 SYNCED / 1 RETRYING"
    assert status.detail == "CONNECTIVITY READY"
