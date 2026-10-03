"""Tests for operator-facing FT8 map status labels."""

import pytest

from rolling_thunder.ft8.domain import FT8QsoState
from rolling_thunder.ft8.panel import FT8PanelMode
from rolling_thunder.ft8.start_control import FT8QsoStartState
from rolling_thunder.ft8.status import FT8OperatorStatus, operator_ft8_status


def test_browse_status_distinguishes_idle_selected_and_preparing() -> None:
    assert operator_ft8_status(
        panel_mode=FT8PanelMode.BROWSE,
        qso_state=FT8QsoState.IDLE,
    ) is FT8OperatorStatus.IDLE
    assert operator_ft8_status(
        panel_mode=FT8PanelMode.BROWSE,
        qso_state=FT8QsoState.IDLE,
        selected_callsign="K1ABC",
    ) is FT8OperatorStatus.SELECTED
    assert operator_ft8_status(
        panel_mode=FT8PanelMode.BROWSE,
        qso_state=FT8QsoState.IDLE,
        start_state=FT8QsoStartState.PREPARING,
    ) is FT8OperatorStatus.SELECTED


@pytest.mark.parametrize(
    ("qso_state", "expected"),
    [
        (FT8QsoState.AUTHORIZED, FT8OperatorStatus.CALLING),
        (FT8QsoState.WAIT_TX_CALL, FT8OperatorStatus.CALLING),
        (FT8QsoState.TX_CALL, FT8OperatorStatus.CALLING),
        (FT8QsoState.WAIT_REPORT, FT8OperatorStatus.WAITING_FOR_REPORT),
        (FT8QsoState.TX_REPORT, FT8OperatorStatus.SENDING_REPORT),
        (FT8QsoState.WAIT_R_REPORT, FT8OperatorStatus.WAITING_FOR_REPORT),
        (FT8QsoState.TX_R_REPORT, FT8OperatorStatus.SENDING_REPORT),
        (FT8QsoState.WAIT_73, FT8OperatorStatus.WAITING_FOR_ACK),
        (FT8QsoState.TX_73, FT8OperatorStatus.SENDING_73),
        (FT8QsoState.COMPLETED, FT8OperatorStatus.COMPLETE),
        (FT8QsoState.ABORTED, FT8OperatorStatus.ABORTED),
        (FT8QsoState.RETRY_EXHAUSTED, FT8OperatorStatus.FAILED),
        (FT8QsoState.ERROR, FT8OperatorStatus.FAILED),
    ],
)
def test_active_terminal_states_map_to_driver_labels(
    qso_state: FT8QsoState,
    expected: FT8OperatorStatus,
) -> None:
    mode = (
        FT8PanelMode.TERMINAL
        if qso_state
        in {
            FT8QsoState.COMPLETED,
            FT8QsoState.ABORTED,
            FT8QsoState.RETRY_EXHAUSTED,
            FT8QsoState.ERROR,
        }
        else FT8PanelMode.ACTIVE
    )

    assert operator_ft8_status(
        panel_mode=mode,
        qso_state=qso_state,
    ) is expected


@pytest.mark.parametrize(
    "start_state",
    [FT8QsoStartState.FAILED, FT8QsoStartState.RESTORE_FAILED],
)
def test_preparation_and_restore_failures_map_failed(
    start_state: FT8QsoStartState,
) -> None:
    assert operator_ft8_status(
        panel_mode=FT8PanelMode.BROWSE,
        qso_state=FT8QsoState.IDLE,
        start_state=start_state,
    ) is FT8OperatorStatus.FAILED
