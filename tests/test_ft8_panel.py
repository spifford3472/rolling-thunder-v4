"""Tests for the presentation-safe FT8 CQ browser controller."""

import pytest

from rolling_thunder.ft8.domain import (
    FT8CQActivity,
    FT8IncomingCall,
    FT8MessageKind,
    FT8Period,
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


def _incoming(callsign: str = "W1XYZ", *, period: int = 105) -> FT8IncomingCall:
    return FT8IncomingCall(
        callsign=callsign,
        period=FT8Period(period),
        snr_db=-6,
        dt_seconds=0.2,
        audio_frequency_hz=1700,
        kind=FT8MessageKind.ADDRESSED_GRID,
        grid="FN42",
        raw_message=f"KI5VNB {callsign} FN42",
    )


def test_incoming_call_requires_explicit_answer_and_uses_exact_decode() -> None:
    authorized: list[FT8IncomingCall] = []
    receive = FT8ReceiveState(
        last_period=FT8Period(105),
        incoming_call=_incoming(),
    )
    panel = FT8PanelController(
        receive_state=lambda: receive,
        qso_state=lambda: FT8QsoState.IDLE,
        qso_context=lambda: None,
        qso_result=lambda: None,
        authorize=lambda activity: authorized.append(activity) is None,
        abort=lambda: None,
        return_to_browser=lambda: None,
        respond=lambda incoming: authorized.append(incoming) is None,
    )

    assert panel.snapshot().incoming_call == _incoming()
    assert authorized == []
    assert panel.answer_incoming_call() is True
    assert [item.callsign for item in authorized] == ["W1XYZ"]
    assert authorized == [_incoming()]
    assert panel.snapshot().incoming_call is None
    assert panel.answer_incoming_call() is False
    assert len(authorized) == 1


def test_report_incoming_call_preserves_report_for_responder_callback() -> None:
    incoming = FT8IncomingCall(
        callsign="K0BQB",
        period=FT8Period(105),
        snr_db=-3,
        dt_seconds=0.2,
        audio_frequency_hz=1700,
        kind=FT8MessageKind.REPORT,
        report_db=-3,
        raw_message="KI5VNB K0BQB -03",
    )
    accepted: list[FT8IncomingCall] = []
    panel = FT8PanelController(
        receive_state=lambda: FT8ReceiveState(
            last_period=FT8Period(105), incoming_call=incoming
        ),
        qso_state=lambda: FT8QsoState.IDLE,
        qso_context=lambda: None,
        qso_result=lambda: None,
        authorize=lambda _activity: True,
        abort=lambda: None,
        return_to_browser=lambda: None,
        respond=lambda call: accepted.append(call) is None,
    )

    assert accepted == []
    assert panel.answer_incoming_call() is True
    assert accepted == [incoming]
    assert accepted[0].report_db == -3


def test_incoming_call_ignore_suppresses_repeats_and_alert_never_interrupts_qso() -> None:
    current = {
        "receive": FT8ReceiveState(
            last_period=FT8Period(105),
            incoming_call=_incoming(),
        ),
        "qso": FT8QsoState.IDLE,
    }
    panel = FT8PanelController(
        receive_state=lambda: current["receive"],
        qso_state=lambda: current["qso"],
        qso_context=lambda: None,
        qso_result=lambda: None,
        authorize=lambda _activity: True,
        abort=lambda: None,
        return_to_browser=lambda: None,
    )

    assert panel.dismiss_incoming_call() is True
    current["receive"] = FT8ReceiveState(
        last_period=FT8Period(106),
        incoming_call=_incoming(period=106),
    )
    assert panel.snapshot().incoming_call is None

    current["receive"] = FT8ReceiveState(
        last_period=FT8Period(107),
        incoming_call=_incoming("K2ABC", period=107),
    )
    assert panel.snapshot().incoming_call == _incoming("K2ABC", period=107)
    current["qso"] = FT8QsoState.WAIT_REPORT
    assert panel.snapshot().mode is FT8PanelMode.ACTIVE
    assert panel.snapshot().incoming_call is None
    current["qso"] = FT8QsoState.ABORTED
    assert panel.snapshot().mode is FT8PanelMode.TERMINAL
    assert panel.snapshot().incoming_call is None


def test_stale_incoming_call_is_not_presented() -> None:
    panel = FT8PanelController(
        receive_state=lambda: FT8ReceiveState(
            last_period=FT8Period(111),
            incoming_call=_incoming(period=105),
        ),
        qso_state=lambda: FT8QsoState.IDLE,
        qso_context=lambda: None,
        qso_result=lambda: None,
        authorize=lambda _activity: True,
        abort=lambda: None,
        return_to_browser=lambda: None,
    )

    assert panel.snapshot().incoming_call is None


def test_panel_selects_only_visible_cq_and_never_auto_selects_next() -> None:
    selected: list[str] = []
    state = {"qso": FT8QsoState.IDLE}

    def authorize(activity: FT8CQActivity) -> bool:
        selected.append(activity.callsign)
        state["qso"] = FT8QsoState.WAIT_TX_CALL
        return True

    panel = FT8PanelController(
        receive_state=lambda: FT8ReceiveState(cq_activity=(_activity(), _activity("W1XYZ"))),
        qso_state=lambda: state["qso"],
        qso_context=lambda: None,
        qso_result=lambda: None,
        authorize=authorize,
        abort=lambda: None,
        return_to_browser=lambda: None,
    )

    accepted = panel.select_callsign("k1abc")

    assert accepted is True
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

    def authorize(activity: FT8CQActivity) -> bool:
        selected.append(activity.callsign)
        state["qso"] = FT8QsoState.WAIT_TX_CALL
        return True

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

    accepted = panel.activate_selection()

    assert accepted is True
    assert selected == ["W1XYZ"]
    assert panel.selected_callsign is None


def test_panel_activity_filter_hides_worked_station_and_clears_selection() -> None:
    hidden = {"callsign": None}
    panel = FT8PanelController(
        receive_state=lambda: FT8ReceiveState(
            cq_activity=(_activity("K1ABC"), _activity("K2BBB"))
        ),
        qso_state=lambda: FT8QsoState.IDLE,
        qso_context=lambda: None,
        qso_result=lambda: None,
        authorize=lambda _activity: True,
        abort=lambda: None,
        return_to_browser=lambda: None,
        activity_filter=lambda item: item.callsign != hidden["callsign"],
    )

    assert panel.select_next() == "K1ABC"
    hidden["callsign"] = "K1ABC"

    snapshot = panel.snapshot()

    assert [item.callsign for item in snapshot.cq_activity] == ["K2BBB"]
    assert panel.selected_callsign is None
    assert panel.activate_selection() is False


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
    assert panel.activate_selection() is False




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
    assert panel.activate_selection() is False
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
