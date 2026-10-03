"""Tests for the presentation-safe FT8 CQ browser controller."""

from datetime import UTC, datetime

import pytest

from rolling_thunder.ft8.domain import (
    FT8CQActivity,
    FT8Period,
    FT8QsoContext,
    FT8QsoState,
)
from rolling_thunder.ft8.panel import FT8PanelController, FT8PanelMode
from rolling_thunder.ft8.receive import FT8ReceiveState


def _activity(callsign: str = "K1ABC") -> FT8CQActivity:
    return FT8CQActivity(
        callsign=callsign,
        last_period=FT8Period(100),
        snr_db=-10,
        dt_seconds=0.1,
        audio_frequency_hz=1500,
        grid="FN31",
    )


def test_panel_selects_only_visible_cq_and_never_auto_selects_next() -> None:
    selected: list[str] = []
    state = {"qso": FT8QsoState.IDLE}

    def authorize(activity: FT8CQActivity) -> FT8QsoContext:
        selected.append(activity.callsign)
        state["qso"] = FT8QsoState.WAIT_TX_CALL
        return FT8QsoContext(
            local_callsign="KI5VNB",
            remote_callsign=activity.callsign,
            target_audio_frequency_hz=activity.audio_frequency_hz,
            radio_frequency_hz=14_074_000,
            radio_band="20m",
            radio_mode="DATA",
            local_grid="EM79xm",
            tx_parity=activity.last_period.parity,
            authorized_period=activity.last_period,
            authorized_utc=datetime.fromtimestamp(1501, tz=UTC),
            signal_report_db=activity.snr_db,
        )

    panel = FT8PanelController(
        receive_state=lambda: FT8ReceiveState(cq_activity=(_activity(), _activity("W1XYZ"))),
        qso_state=lambda: state["qso"],
        qso_context=lambda: None,
        qso_result=lambda: None,
        authorize=authorize,
        abort=lambda: None,
        return_to_browser=lambda: None,
    )

    context = panel.select_callsign("k1abc")

    assert context.remote_callsign == "K1ABC"
    assert selected == ["K1ABC"]
    assert panel.snapshot().mode is FT8PanelMode.ACTIVE
    with pytest.raises(RuntimeError, match="cannot select another"):
        panel.select_callsign("W1XYZ")
    assert selected == ["K1ABC"]


def test_panel_refuses_callsign_not_in_current_cq_snapshot() -> None:
    panel = FT8PanelController(
        receive_state=lambda: FT8ReceiveState(cq_activity=(_activity(),)),
        qso_state=lambda: FT8QsoState.IDLE,
        qso_context=lambda: None,
        qso_result=lambda: None,
        authorize=lambda activity: pytest.fail(f"unexpected selection {activity}"),
        abort=lambda: None,
        return_to_browser=lambda: None,
    )

    with pytest.raises(ValueError, match="exactly one"):
        panel.select_callsign("W1XYZ")


def test_panel_abort_is_available_only_while_active() -> None:
    state = {"qso": FT8QsoState.WAIT_REPORT}
    aborts: list[str] = []
    panel = FT8PanelController(
        receive_state=lambda: FT8ReceiveState(),
        qso_state=lambda: state["qso"],
        qso_context=lambda: None,
        qso_result=lambda: None,
        authorize=lambda activity: pytest.fail(f"unexpected selection {activity}"),
        abort=lambda: aborts.append("abort"),
        return_to_browser=lambda: None,
    )

    panel.abort()
    assert aborts == ["abort"]

    state["qso"] = FT8QsoState.ABORTED
    panel.abort()
    assert aborts == ["abort"]
    assert panel.snapshot().mode is FT8PanelMode.TERMINAL


def test_panel_requires_terminal_state_before_return_to_browser() -> None:
    state = {"qso": FT8QsoState.WAIT_REPORT}
    panel = FT8PanelController(
        receive_state=lambda: FT8ReceiveState(),
        qso_state=lambda: state["qso"],
        qso_context=lambda: None,
        qso_result=lambda: None,
        authorize=lambda activity: pytest.fail(f"unexpected selection {activity}"),
        abort=lambda: None,
        return_to_browser=lambda: None,
    )

    with pytest.raises(RuntimeError, match="must be terminal"):
        panel.return_to_browser()


def test_panel_browser_selection_is_bounded_and_requires_explicit_activation() -> None:
    selected: list[str] = []
    state = {"qso": FT8QsoState.IDLE}

    def authorize(activity: FT8CQActivity) -> FT8QsoContext:
        selected.append(activity.callsign)
        state["qso"] = FT8QsoState.WAIT_TX_CALL
        return FT8QsoContext(
            local_callsign="KI5VNB",
            remote_callsign=activity.callsign,
            target_audio_frequency_hz=activity.audio_frequency_hz,
            radio_frequency_hz=14_074_000,
            radio_band="20m",
            radio_mode="DATA",
            local_grid="EM79xm",
            tx_parity=activity.last_period.parity,
            authorized_period=activity.last_period,
            authorized_utc=datetime.fromtimestamp(1501, tz=UTC),
            signal_report_db=activity.snr_db,
        )

    panel = FT8PanelController(
        receive_state=lambda: FT8ReceiveState(cq_activity=(_activity(), _activity("W1XYZ"))),
        qso_state=lambda: state["qso"],
        qso_context=lambda: None,
        qso_result=lambda: None,
        authorize=authorize,
        abort=lambda: None,
        return_to_browser=lambda: None,
    )

    assert panel.selected_callsign is None
    assert panel.select_next() == "K1ABC"
    assert panel.select_next() == "W1XYZ"
    assert panel.select_next() == "W1XYZ"
    assert selected == []

    context = panel.activate_selection()

    assert context is not None
    assert context.remote_callsign == "W1XYZ"
    assert selected == ["W1XYZ"]
    assert panel.selected_callsign is None


def test_panel_visible_cq_viewport_follows_selection_without_reordering() -> None:
    activity = tuple(_activity(f"K{index}ABC") for index in range(1, 11))
    panel = FT8PanelController(
        receive_state=lambda: FT8ReceiveState(cq_activity=activity),
        qso_state=lambda: FT8QsoState.IDLE,
        qso_context=lambda: None,
        qso_result=lambda: None,
        authorize=lambda item: pytest.fail(f"unexpected selection {item}"),
        abort=lambda: None,
        return_to_browser=lambda: None,
    )

    assert [item.callsign for item in panel.visible_cq_activity(limit=4)] == [
        "K1ABC",
        "K2ABC",
        "K3ABC",
        "K4ABC",
    ]

    for _ in range(6):
        panel.select_next()

    assert panel.selected_callsign == "K6ABC"
    assert [item.callsign for item in panel.visible_cq_activity(limit=4)] == [
        "K3ABC",
        "K4ABC",
        "K5ABC",
        "K6ABC",
    ]


def test_panel_drops_selection_when_cq_expires() -> None:
    current = {"receive": FT8ReceiveState(cq_activity=(_activity(),))}
    panel = FT8PanelController(
        receive_state=lambda: current["receive"],
        qso_state=lambda: FT8QsoState.IDLE,
        qso_context=lambda: None,
        qso_result=lambda: None,
        authorize=lambda activity: pytest.fail(f"unexpected selection {activity}"),
        abort=lambda: None,
        return_to_browser=lambda: None,
    )

    assert panel.select_next() == "K1ABC"
    current["receive"] = FT8ReceiveState()

    assert panel.selected_callsign is None
    assert panel.activate_selection() is None




def test_receive_only_panel_browses_but_does_not_authorize() -> None:
    authorized: list[str] = []
    panel = FT8PanelController(
        receive_state=lambda: FT8ReceiveState(cq_activity=(_activity(),)),
        qso_state=lambda: FT8QsoState.IDLE,
        qso_context=lambda: None,
        qso_result=lambda: None,
        authorize=lambda activity: authorized.append(activity.callsign) or pytest.fail(
            "receive-only panel must not authorize"
        ),
        abort=lambda: None,
        return_to_browser=lambda: None,
        authorization_enabled=lambda: False,
    )

    assert panel.select_next() == "K1ABC"

    snapshot = panel.snapshot()
    assert snapshot.mode is FT8PanelMode.BROWSE
    assert snapshot.authorization_enabled is False
    assert panel.activate_selection() is None
    assert panel.selected_callsign == "K1ABC"
    assert authorized == []

def test_panel_snapshot_exposes_bounded_retry_progress() -> None:
    panel = FT8PanelController(
        receive_state=lambda: FT8ReceiveState(),
        qso_state=lambda: FT8QsoState.WAIT_REPORT,
        qso_context=lambda: None,
        qso_result=lambda: None,
        authorize=lambda activity: pytest.fail(f"unexpected selection {activity}"),
        abort=lambda: None,
        return_to_browser=lambda: None,
        attempt_count=lambda: 3,
        attempts_per_state=lambda: 6,
    )

    snapshot = panel.snapshot()

    assert snapshot.mode is FT8PanelMode.ACTIVE
    assert snapshot.attempt_count == 3
    assert snapshot.attempts_per_state == 6
