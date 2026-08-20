"""Tests for the glanceable vehicle status-strip presentation."""

from datetime import UTC, datetime

from rolling_thunder.callsign_capture import CallsignCaptureState
from rolling_thunder.dashboard_state import build_dashboard_state
from rolling_thunder.domain import RadioConnectionState, RadioState
from rolling_thunder.status_bar_ui import (
    STATUS_BAR_HEIGHT_PX,
    STATUS_ICON_CANVAS_PX,
    STATUS_ICON_CELL_WIDTH_PX,
    STATUS_ICON_ORDER,
    status_color,
)
from rolling_thunder.status_monitor import ProbeResult, StatusMonitorSnapshot, StatusState
from rolling_thunder.status_strip import (
    STATUS_ITEM_ORDER,
    StatusItemId,
    build_status_bar_routine_message,
    build_status_strip_snapshot,
)


def radio(connection_state: RadioConnectionState) -> RadioState:
    return RadioState(
        connection_state=connection_state,
        updated_at=datetime(2026, 8, 19, 20, 23, tzinfo=UTC),
    )


def monitored() -> StatusMonitorSnapshot:
    return StatusMonitorSnapshot(
        internet=ProbeResult(StatusState.HEALTHY),
        forge=ProbeResult(StatusState.UNAVAILABLE),
        microphone=ProbeResult(StatusState.STARTING),
    )


def test_status_strip_has_four_equal_ordered_icon_cells() -> None:
    assert STATUS_ICON_ORDER == STATUS_ITEM_ORDER == (
        StatusItemId.HF_RADIO,
        StatusItemId.INTERNET,
        StatusItemId.FORGE,
        StatusItemId.MICROPHONE,
    )
    assert len(set(STATUS_ICON_ORDER)) == 4
    assert STATUS_ICON_CELL_WIDTH_PX == STATUS_BAR_HEIGHT_PX
    assert STATUS_ICON_CANVAS_PX >= int(STATUS_BAR_HEIGHT_PX * 0.85)


def test_connected_hf_radio_maps_to_healthy_without_another_probe() -> None:
    snapshot = build_status_strip_snapshot(
        radio(RadioConnectionState.CONNECTED),
        monitored(),
    )

    assert snapshot.items[0].item_id is StatusItemId.HF_RADIO
    assert snapshot.items[0].state is StatusState.HEALTHY


def test_disconnected_and_error_hf_radio_map_to_unavailable() -> None:
    for state in (RadioConnectionState.DISCONNECTED, RadioConnectionState.ERROR):
        snapshot = build_status_strip_snapshot(radio(state), monitored())
        assert snapshot.items[0].state is StatusState.UNAVAILABLE


def test_monitor_states_propagate_in_expected_order() -> None:
    snapshot = build_status_strip_snapshot(
        radio(RadioConnectionState.CONNECTED),
        monitored(),
    )

    assert [item.state for item in snapshot.items] == [
        StatusState.HEALTHY,
        StatusState.HEALTHY,
        StatusState.UNAVAILABLE,
        StatusState.STARTING,
    ]


def test_healthy_unavailable_and_starting_have_distinct_visual_states() -> None:
    colors = {
        status_color(StatusState.HEALTHY),
        status_color(StatusState.UNAVAILABLE),
        status_color(StatusState.STARTING),
    }

    assert len(colors) == 3
    assert status_color(StatusState.HEALTHY) == "#42ff72"
    assert status_color(StatusState.UNAVAILABLE) == "#ff3b3b"


def test_routine_message_does_not_duplicate_icon_owned_health_text() -> None:
    dashboard = build_dashboard_state(
        radio(RadioConnectionState.CONNECTED),
        CallsignCaptureState(voice_state="READY"),
    )

    message = build_status_bar_routine_message(dashboard)

    assert message == "VOICE READY — GPS DISABLED"
    assert "RADIO" not in message
    assert "INTERNET" not in message
    assert "FORGE" not in message
