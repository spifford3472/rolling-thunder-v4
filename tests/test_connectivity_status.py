"""Tests for pure connectivity and synchronization presentation state."""

from datetime import UTC, datetime

from rolling_thunder.connectivity_status import build_connectivity_status
from rolling_thunder.contact_sync import ContactSyncResult
from rolling_thunder.dashboard_state import build_dashboard_state
from rolling_thunder.domain import Frequency, RadioConnectionState, RadioMode, RadioState
from rolling_thunder.home_platform import HomePlatformAvailability, HomePlatformState
from rolling_thunder.network_keepalive import (
    NetworkKeepaliveAvailability,
    NetworkKeepaliveState,
)

_FIXED_TIME = datetime(2026, 7, 26, 18, 0, tzinfo=UTC)


def _radio() -> RadioState:
    return RadioState(
        connection_state=RadioConnectionState.CONNECTED,
        frequency=Frequency(hz=14_250_000),
        mode=RadioMode.USB,
        transmitting=False,
        updated_at=_FIXED_TIME,
    )


def test_disabled_connectivity_is_explicit() -> None:
    status = build_connectivity_status(
        network_enabled=False,
        platform_enabled=False,
    )

    assert status.network == "DISABLED"
    assert status.home_platform == "DISABLED"
    assert status.synchronization == "DISABLED"
    assert status.detail == "CONNECTIVITY READY"


def test_enabled_connectivity_starts_unknown_and_idle() -> None:
    status = build_connectivity_status(
        network_enabled=True,
        platform_enabled=True,
    )

    assert status.network == "UNKNOWN"
    assert status.home_platform == "UNKNOWN"
    assert status.synchronization == "IDLE"


def test_online_states_and_sync_result_are_operator_facing() -> None:
    status = build_connectivity_status(
        network_enabled=True,
        platform_enabled=True,
        network_state=NetworkKeepaliveState(
            availability=NetworkKeepaliveAvailability.REACHABLE,
            checked_at=_FIXED_TIME,
            last_success_at=_FIXED_TIME,
        ),
        platform_state=HomePlatformState(
            availability=HomePlatformAvailability.AVAILABLE,
            checked_at=_FIXED_TIME,
        ),
        sync_result=ContactSyncResult(attempted=4, synchronized=3, failed=1),
    )

    assert status.network == "ONLINE"
    assert status.home_platform == "ONLINE"
    assert status.synchronization == "3 SYNCED / 1 RETRYING"
    assert status.detail == "CONNECTIVITY READY"


def test_offline_errors_are_concise_and_independent() -> None:
    status = build_connectivity_status(
        network_enabled=True,
        platform_enabled=True,
        network_state=NetworkKeepaliveState(
            availability=NetworkKeepaliveAvailability.UNREACHABLE,
            checked_at=_FIXED_TIME,
            last_error="request timed out",
        ),
        platform_state=HomePlatformState(
            availability=HomePlatformAvailability.UNAVAILABLE,
            checked_at=_FIXED_TIME,
            last_error="HTTP 503",
        ),
    )

    assert status.network == "OFFLINE"
    assert status.home_platform == "OFFLINE"
    assert status.detail == "NETWORK: request timed out — PLATFORM: HTTP 503"


def test_dashboard_exposes_connectivity_without_changing_radio_fields() -> None:
    connectivity = build_connectivity_status(
        network_enabled=True,
        platform_enabled=True,
        network_state=NetworkKeepaliveState(
            availability=NetworkKeepaliveAvailability.REACHABLE,
            checked_at=_FIXED_TIME,
            last_success_at=_FIXED_TIME,
        ),
        platform_state=HomePlatformState(
            availability=HomePlatformAvailability.AVAILABLE,
            checked_at=_FIXED_TIME,
        ),
        sync_result=ContactSyncResult(attempted=2, synchronized=2, failed=0),
    )

    view = build_dashboard_state(_radio(), connectivity=connectivity)

    assert view.radio_state == "CONNECTED"
    assert view.frequency == "14.250 MHz"
    assert view.network_state == "ONLINE"
    assert view.home_platform_state == "ONLINE"
    assert view.synchronization_state == "2 SYNCED / 0 RETRYING"
    assert view.connectivity_detail == "CONNECTIVITY READY"
