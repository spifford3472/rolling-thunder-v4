"""Application-facing ownership for one explicitly authorized FT8 QSO."""

from __future__ import annotations

from collections.abc import Callable
from threading import RLock

from rolling_thunder.ft8.coordinator import FT8QsoCoordinator, FT8QsoResult
from rolling_thunder.ft8.domain import FT8QsoContext, FT8QsoState
from rolling_thunder.ft8.receive import FT8ReceiveService
from rolling_thunder.ft8.timing import FT8Clock
from rolling_thunder.ft8.transmit import DigitalTransmitSession

FT8TransmitSessionFactory = Callable[[FT8QsoContext], DigitalTransmitSession]


class FT8OperatorQsoService:
    """Own at most one active operator-authorized QSO.

    The caller supplies the already-frozen context. This service does not choose
    a CQ station, derive a callsign, change bands, tune the radio, or write a
    completed contact.
    """

    def __init__(
        self,
        receive_service: FT8ReceiveService,
        transmit_session_factory: FT8TransmitSessionFactory,
        clock: FT8Clock,
        *,
        attempts_per_state: int = 6,
        terminal_result_handler: Callable[[FT8QsoResult], object] | None = None,
    ) -> None:
        self._receive_service = receive_service
        self._transmit_session_factory = transmit_session_factory
        self._clock = clock
        self._attempts_per_state = attempts_per_state
        self._terminal_result_handler = terminal_result_handler
        self._lock = RLock()
        self._coordinator: FT8QsoCoordinator | None = None

    @property
    def state(self) -> FT8QsoState:
        with self._lock:
            if self._coordinator is None:
                return FT8QsoState.IDLE
            return self._coordinator.state

    @property
    def context(self) -> FT8QsoContext | None:
        with self._lock:
            if self._coordinator is None:
                return None
            return self._coordinator.context

    @property
    def result(self) -> FT8QsoResult | None:
        with self._lock:
            if self._coordinator is None:
                return None
            return self._coordinator.result

    def authorize_and_start(self, context: FT8QsoContext) -> None:
        """Start exactly one QSO from an explicit operator authorization."""
        with self._lock:
            if self._coordinator is not None:
                raise RuntimeError("an FT8 QSO is already authorized")
            session = self._transmit_session_factory(context)
            coordinator = FT8QsoCoordinator(
                session,
                self._clock,
                attempts_per_state=self._attempts_per_state,
                terminal_result_handler=self._terminal_result_handler,
            )
            coordinator.authorize(context)
            coordinator.start_qso()
            self._receive_service.set_observer(coordinator)
            self._coordinator = coordinator
            coordinator.start_worker()

    def abort(self) -> None:
        """Abort the one active QSO; safe to repeat."""
        with self._lock:
            coordinator = self._coordinator
        if coordinator is not None:
            coordinator.abort()

    def return_to_browser(self) -> FT8QsoResult | None:
        """Detach terminal QSO execution and restore CQ-browser ownership."""
        with self._lock:
            coordinator = self._coordinator
            if coordinator is None:
                return None
            if coordinator.state not in {
                FT8QsoState.COMPLETED,
                FT8QsoState.ABORTED,
                FT8QsoState.RETRY_EXHAUSTED,
                FT8QsoState.ERROR,
            }:
                raise RuntimeError("cannot return to the CQ browser while a QSO is active")
            result = coordinator.result
            coordinator.stop_worker()
            self._receive_service.set_observer(None)
            self._coordinator = None
            return result

    def close(self) -> None:
        """Revoke any active QSO and detach receive observation."""
        with self._lock:
            coordinator = self._coordinator
            self._coordinator = None
        if coordinator is not None:
            coordinator.abort()
            coordinator.stop_worker()
        self._receive_service.set_observer(None)
