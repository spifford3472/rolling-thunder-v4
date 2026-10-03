"""Operator-facing FT8 status labels for the mobile map banner."""

from __future__ import annotations

from enum import StrEnum

from rolling_thunder.ft8.domain import FT8QsoState
from rolling_thunder.ft8.panel import FT8PanelMode
from rolling_thunder.ft8.start_control import FT8QsoStartState


class FT8OperatorStatus(StrEnum):
    IDLE = "IDLE"
    SELECTED = "SELECTED"
    CALLING = "CALLING"
    WAITING_FOR_REPORT = "WAITING FOR REPORT"
    SENDING_REPORT = "SENDING REPORT"
    WAITING_FOR_ACK = "WAITING FOR ACK"
    SENDING_73 = "SENDING 73"
    COMPLETE = "COMPLETE"
    ABORTED = "ABORTED"
    FAILED = "FAILED"


def operator_ft8_status(
    *,
    panel_mode: FT8PanelMode,
    qso_state: FT8QsoState,
    selected_callsign: str | None = None,
    start_state: FT8QsoStartState | None = None,
) -> FT8OperatorStatus:
    """Map internal FT8 execution into concise driver-facing state."""
    if start_state is FT8QsoStartState.PREPARING:
        return FT8OperatorStatus.SELECTED
    if start_state in {
        FT8QsoStartState.FAILED,
        FT8QsoStartState.RESTORE_FAILED,
    }:
        return FT8OperatorStatus.FAILED

    if panel_mode is FT8PanelMode.BROWSE:
        return (
            FT8OperatorStatus.SELECTED
            if selected_callsign is not None
            else FT8OperatorStatus.IDLE
        )

    return {
        FT8QsoState.AUTHORIZED: FT8OperatorStatus.CALLING,
        FT8QsoState.WAIT_TX_CALL: FT8OperatorStatus.CALLING,
        FT8QsoState.TX_CALL: FT8OperatorStatus.CALLING,
        FT8QsoState.WAIT_REPORT: FT8OperatorStatus.WAITING_FOR_REPORT,
        FT8QsoState.TX_REPORT: FT8OperatorStatus.SENDING_REPORT,
        FT8QsoState.WAIT_R_REPORT: FT8OperatorStatus.WAITING_FOR_REPORT,
        FT8QsoState.TX_R_REPORT: FT8OperatorStatus.SENDING_REPORT,
        FT8QsoState.WAIT_73: FT8OperatorStatus.WAITING_FOR_ACK,
        FT8QsoState.TX_73: FT8OperatorStatus.SENDING_73,
        FT8QsoState.COMPLETED: FT8OperatorStatus.COMPLETE,
        FT8QsoState.ABORTED: FT8OperatorStatus.ABORTED,
        FT8QsoState.RETRY_EXHAUSTED: FT8OperatorStatus.FAILED,
        FT8QsoState.ERROR: FT8OperatorStatus.FAILED,
        FT8QsoState.IDLE: FT8OperatorStatus.IDLE,
    }[qso_state]
