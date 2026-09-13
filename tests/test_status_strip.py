"""Tests for the glanceable vehicle status-strip presentation."""

from datetime import UTC, datetime

from rolling_thunder.callsign_capture import CallsignCaptureState
from rolling_thunder.dashboard_state import build_dashboard_state
from rolling_thunder.domain import (
    Frequency,
    RadioConnectionState,
    RadioMode,
    RadioState,
)
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
    updated_at = datetime(2026, 8, 19, 20, 23, tzinfo=UTC)
    if connection_state is RadioConnectionState.CONNECTED:
        return RadioState(
            connection_state=connection_state,
            frequency=Frequency(hz=14_250_000),
            mode=RadioMode.USB,
            updated_at=updated_at,
        )
    if connection_state is RadioConnectionState.ERROR:
        return RadioState(
            connection_state=connection_state,
            updated_at=updated_at,
            last_error="radio unavailable",
        )
    return RadioState(
        connection_state=connection_state,
        updated_at=updated_at,
    )


def monitored() -> StatusMonitorSnapshot:
    return StatusMonitorSnapshot(
        internet=ProbeResult(StatusState.HEALTHY),
        forge=ProbeResult(StatusState.UNAVAILABLE),
        microphone=ProbeResult(StatusState.STARTING),
    )


def test_status_bar_has_six_equal_ordered_icon_cells() -> None:
    assert STATUS_ITEM_ORDER == (
        StatusItemId.HF_RADIO,
        StatusItemId.INTERNET,
        StatusItemId.FORGE,
        StatusItemId.MICROPHONE,
    )
    assert STATUS_ICON_ORDER == STATUS_ITEM_ORDER + (
        StatusItemId.VOICE,
        StatusItemId.GPS,
    )
    assert len(set(STATUS_ICON_ORDER)) == 6
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


def test_routine_message_encodes_aux_icons_and_only_displays_dates() -> None:
    dashboard = build_dashboard_state(
        radio(RadioConnectionState.CONNECTED),
        CallsignCaptureState(voice_state="READY"),
    )

    message = build_status_bar_routine_message(
        dashboard,
        now=datetime(2026, 8, 19, 21, 30, tzinfo=UTC),
    )

    assert message == (
        "[[VOICE=READY]][[GPS=DISABLED]]"
        "Local Date: 2026-Aug-19 | UTC Date: 2026-Aug-19"
    )
    assert "SYNC" not in message
    assert "RADIO" not in message
    assert "INTERNET" not in message
    assert "FORGE" not in message
