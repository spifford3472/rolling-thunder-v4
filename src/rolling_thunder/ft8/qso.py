"""Deterministic hardware-independent FT8 QSO state machine."""

from rolling_thunder.ft8.domain import (
    FT8Decode,
    FT8MessageKind,
    FT8Period,
    FT8QsoContext,
    FT8QsoState,
)
from rolling_thunder.ft8.target_activity import TargetActivity, TargetActivityKind
from rolling_thunder.ft8.transmit import (
    DigitalTransmitSession,
    FT8TransmitKind,
    FT8TransmitRequest,
)

_TERMINAL_STATES = {
    FT8QsoState.COMPLETED,
    FT8QsoState.ABORTED,
    FT8QsoState.RETRY_EXHAUSTED,
    FT8QsoState.ERROR,
}


class FT8QsoController:
    """Own one explicitly authorized FT8 QSO and its bounded retry policy."""

    def __init__(
        self,
        transmit_session: DigitalTransmitSession,
        *,
        attempts_per_state: int = 6,
    ) -> None:
        if attempts_per_state < 1:
            raise ValueError("attempts_per_state must be at least 1")
        self._transmit_session = transmit_session
        self._attempts_per_state = attempts_per_state
        self._state = FT8QsoState.IDLE
        self._context: FT8QsoContext | None = None
        self._attempt_count = 0
        self._busy_extension_granted = False
        self._busy_extension_attempts = 0
        self._total_transmit_attempts = 0
        self._last_tx_period_index: int | None = None
        self._last_consumed_decode_period_index: int | None = None
        self._cancelled = False

    @property
    def state(self) -> FT8QsoState:
        return self._state

    @property
    def context(self) -> FT8QsoContext | None:
        return self._context

    @property
    def attempt_count(self) -> int:
        return self._attempt_count

    @property
    def total_transmit_attempts(self) -> int:
        """Return total transmit requests across all QSO phases."""
        return self._total_transmit_attempts

    @property
    def attempts_per_state(self) -> int:
        """Return the immutable retry budget for the current controller."""
        return self._attempts_per_state

    @property
    def busy_extension_attempts(self) -> int:
        """Number of seventh/eighth transmissions, never reachability failures."""
        return self._busy_extension_attempts

    def observe_target_activity(self, activity: TargetActivity | None, period: FT8Period) -> None:
        """Latch an eligible extension for the current phase only.

        Evidence is rechecked by the caller against the current period; a
        previously granted allowance stays fixed until phase transition.
        """
        context = self._context
        if context is None or self._state in _TERMINAL_STATES:
            return
        if activity is None or activity.callsign != context.remote_callsign:
            return
        if not activity.observed_source or activity.kind not in {
            TargetActivityKind.OTHER_QSO, TargetActivityKind.SIGNOFF,
        }:
            return
        if activity.other_callsign is None or activity.other_callsign in {
            context.local_callsign, context.remote_callsign,
        }:
            return
        if activity.last_period is None or not 0 <= period.index - activity.last_period.index < 4:
            return
        if activity.message_kind not in {
            FT8MessageKind.ADDRESSED_GRID, FT8MessageKind.REPORT,
            FT8MessageKind.R_REPORT, FT8MessageKind.ACK_73,
        }:
            return
        self._busy_extension_granted = True

    def authorize(self, context: FT8QsoContext) -> None:
        """Authorize exactly one remote station from the idle state."""
        if self._state is not FT8QsoState.IDLE:
            raise RuntimeError("a QSO can only be authorized from IDLE")
        self._context = context
        self._attempt_count = 0
        self._busy_extension_granted = False
        self._busy_extension_attempts = 0
        self._total_transmit_attempts = 0
        self._last_tx_period_index = None
        self._last_consumed_decode_period_index = context.authorized_period.index
        self._cancelled = False
        self._state = FT8QsoState.AUTHORIZED

    def start(self) -> None:
        """Move an authorized QSO into slot-driven operation."""
        if self._state is not FT8QsoState.AUTHORIZED:
            raise RuntimeError("QSO start requires AUTHORIZED state")
        inbound = self._require_context().responder_inbound
        if inbound is None:
            self._state = FT8QsoState.WAIT_TX_CALL
        elif inbound.kind is FT8MessageKind.ADDRESSED_GRID:
            self._state = FT8QsoState.TX_REPORT
        elif inbound.kind is FT8MessageKind.REPORT:
            self._state = FT8QsoState.TX_R_REPORT
        else:
            raise RuntimeError("unsupported FT8 responder start message")

    def on_period(self, period: FT8Period) -> None:
        """Handle one observed FT8 period without sleeping or touching hardware."""
        if self._state in _TERMINAL_STATES or self._state in {
            FT8QsoState.IDLE,
            FT8QsoState.AUTHORIZED,
        }:
            return
        context = self._require_context()
        if period.index <= context.authorized_period.index:
            return
        if period.parity is not context.tx_parity:
            return
        if self._last_tx_period_index is not None and period.index <= self._last_tx_period_index:
            return

        kind, tx_state, wait_state = self._transmit_plan()
        limit = min(8, self._attempts_per_state + 2) if self._busy_extension_granted and self._attempts_per_state == 6 else self._attempts_per_state
        if self._attempt_count >= limit:
            self._enter_terminal(FT8QsoState.RETRY_EXHAUSTED)
            return

        self._attempt_count += 1
        self._total_transmit_attempts += 1
        busy_extension = self._attempt_count > self._attempts_per_state
        if busy_extension:
            self._busy_extension_attempts += 1
        self._state = tx_state
        self._transmit_session.request(
            FT8TransmitRequest(
                context=context,
                kind=kind,
                period=period,
                attempt=self._attempt_count,
                busy_extension=busy_extension,
            )
        )
        self._last_tx_period_index = period.index

        if tx_state is FT8QsoState.TX_73:
            self._state = FT8QsoState.COMPLETED
        else:
            self._state = wait_state

    def on_decode(self, decode: FT8Decode) -> None:
        """Advance only for fresh expected traffic from the authorized station."""
        if self._state in _TERMINAL_STATES or self._state in {
            FT8QsoState.IDLE,
            FT8QsoState.AUTHORIZED,
            FT8QsoState.WAIT_TX_CALL,
            FT8QsoState.TX_REPORT,
            FT8QsoState.TX_R_REPORT,
            FT8QsoState.TX_73,
        }:
            return
        context = self._require_context()
        if decode.source_callsign != context.remote_callsign:
            return
        if decode.destination_callsign != context.local_callsign:
            return
        if decode.period.parity is context.tx_parity:
            return
        if decode.period.index <= context.authorized_period.index:
            return
        if (
            self._last_consumed_decode_period_index is not None
            and decode.period.index <= self._last_consumed_decode_period_index
        ):
            return

        expected = self._expected_decode_kind()
        if expected is None or decode.kind is not expected:
            return

        self._last_consumed_decode_period_index = decode.period.index
        self._attempt_count = 0
        self._busy_extension_granted = False
        if self._state is FT8QsoState.WAIT_REPORT:
            self._state = FT8QsoState.TX_R_REPORT
        elif self._state in {FT8QsoState.WAIT_R_REPORT, FT8QsoState.WAIT_73}:
            self._state = FT8QsoState.TX_73

    def abort(self, *, session_already_cancelled: bool = False) -> None:
        """Idempotently cancel an authorized/active QSO."""
        if self._state is FT8QsoState.IDLE or self._state in _TERMINAL_STATES:
            return
        if not self._cancelled:
            if not session_already_cancelled:
                self._transmit_session.cancel()
            self._cancelled = True
        self._state = FT8QsoState.ABORTED

    def fail(self, *, session_already_cancelled: bool = False) -> None:
        """Enter explicit ERROR state and revoke future fake transmission."""
        if self._state is FT8QsoState.IDLE or self._state in _TERMINAL_STATES:
            return
        self._enter_terminal(
            FT8QsoState.ERROR,
            session_already_cancelled=session_already_cancelled,
        )

    def reset(self) -> None:
        """Explicitly clear a terminal QSO and return to CQ-ready idle state."""
        if self._state not in _TERMINAL_STATES:
            raise RuntimeError("QSO reset requires a terminal state")
        self._state = FT8QsoState.IDLE
        self._context = None
        self._attempt_count = 0
        self._busy_extension_granted = False
        self._busy_extension_attempts = 0
        self._total_transmit_attempts = 0
        self._last_tx_period_index = None
        self._last_consumed_decode_period_index = None
        self._cancelled = False

    def _transmit_plan(self) -> tuple[FT8TransmitKind, FT8QsoState, FT8QsoState]:
        if self._state in {FT8QsoState.WAIT_TX_CALL, FT8QsoState.WAIT_REPORT}:
            return (
                FT8TransmitKind.CALL,
                FT8QsoState.TX_CALL,
                FT8QsoState.WAIT_REPORT,
            )
        if self._state in {FT8QsoState.TX_REPORT, FT8QsoState.WAIT_R_REPORT}:
            return (
                FT8TransmitKind.REPORT,
                FT8QsoState.TX_REPORT,
                FT8QsoState.WAIT_R_REPORT,
            )
        if self._state in {FT8QsoState.TX_R_REPORT, FT8QsoState.WAIT_73}:
            return (
                FT8TransmitKind.R_REPORT,
                FT8QsoState.TX_R_REPORT,
                FT8QsoState.WAIT_73,
            )
        if self._state is FT8QsoState.TX_73:
            return (
                FT8TransmitKind.SEVENTY_THREE,
                FT8QsoState.TX_73,
                FT8QsoState.COMPLETED,
            )
        raise RuntimeError(f"no transmit plan for FT8 QSO state {self._state}")

    def _expected_decode_kind(self) -> FT8MessageKind | None:
        if self._state is FT8QsoState.WAIT_REPORT:
            return FT8MessageKind.REPORT
        if self._state is FT8QsoState.WAIT_R_REPORT:
            return FT8MessageKind.R_REPORT
        if self._state is FT8QsoState.WAIT_73:
            return FT8MessageKind.ACK_73
        return None

    def _require_context(self) -> FT8QsoContext:
        if self._context is None:
            raise RuntimeError("active FT8 QSO is missing authorization context")
        return self._context

    def _enter_terminal(
        self,
        state: FT8QsoState,
        *,
        session_already_cancelled: bool = False,
    ) -> None:
        if state not in _TERMINAL_STATES:
            raise ValueError("terminal transition requires a terminal state")
        if not self._cancelled and state is not FT8QsoState.COMPLETED:
            if not session_already_cancelled:
                self._transmit_session.cancel()
            self._cancelled = True
        self._state = state
