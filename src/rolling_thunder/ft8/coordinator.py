"""Checkpoint 7 coordinator for exactly one operator-authorized FT8 QSO."""

from __future__ import annotations

import threading
from collections.abc import Sequence

from rolling_thunder.ft8.domain import FT8Decode, FT8Period, FT8QsoContext, FT8QsoState
from rolling_thunder.ft8.qso import FT8QsoController
from rolling_thunder.ft8.timing import FT8Clock
from rolling_thunder.ft8.transmit import DigitalTransmitSession


class FT8QsoCoordinator:
    """Serialize timing, decoder events, aborts, and one QSO controller."""

    def __init__(
        self,
        transmit_session: DigitalTransmitSession,
        clock: FT8Clock,
        *,
        attempts_per_state: int = 6,
    ) -> None:
        self._controller = FT8QsoController(
            transmit_session,
            attempts_per_state=attempts_per_state,
        )
        self._clock = clock
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._worker: threading.Thread | None = None
        self._last_observed_period: FT8Period | None = None
        self._terminal_reason: str | None = None

    @property
    def state(self) -> FT8QsoState:
        with self._lock:
            return self._controller.state

    @property
    def context(self) -> FT8QsoContext | None:
        with self._lock:
            return self._controller.context

    @property
    def terminal_reason(self) -> str | None:
        with self._lock:
            return self._terminal_reason

    def authorize(self, context: FT8QsoContext) -> None:
        """Freeze exactly one operator-selected station into this coordinator."""
        with self._lock:
            self._controller.authorize(context)
            self._last_observed_period = context.authorized_period
            self._terminal_reason = None

    def start_qso(self) -> None:
        """Start deterministic slot-driven QSO operation."""
        with self._lock:
            self._controller.start()

    def tick(self) -> None:
        """Process the current UTC period at most once."""
        with self._lock:
            period = self._clock.current_period()
            previous = self._last_observed_period
            if previous is not None:
                if period.index < previous.index:
                    self._fail_locked("system UTC moved backward")
                    return
                if period.index == previous.index:
                    return
                if period.index > previous.index + 1:
                    self._fail_locked("system UTC skipped an FT8 period")
                    return
            self._last_observed_period = period
            try:
                self._controller.on_period(period)
            except (OSError, RuntimeError, ValueError) as exc:
                self._fail_locked(str(exc))

    def on_decodes(self, decodes: Sequence[FT8Decode]) -> None:
        """Forward normalized decodes; the controller filters authorization relevance."""
        with self._lock:
            for decode in decodes:
                self._controller.on_decode(decode)

    def on_receive_error(self, detail: str) -> None:
        """Fail an active QSO when its decoder/receive path becomes unavailable."""
        with self._lock:
            if self._controller.state in {
                FT8QsoState.IDLE,
                FT8QsoState.COMPLETED,
                FT8QsoState.ABORTED,
                FT8QsoState.RETRY_EXHAUSTED,
                FT8QsoState.ERROR,
            }:
                return
            self._fail_locked(f"FT8 receive failure: {detail}")

    def abort(self) -> None:
        """Idempotently abort and force the transmit session toward receive."""
        with self._lock:
            self._controller.abort()
            if self._controller.state is FT8QsoState.ABORTED:
                self._terminal_reason = "operator abort"
        self._stop_event.set()

    def reset(self) -> None:
        """Reset only after a terminal QSO result."""
        with self._lock:
            self._controller.reset()
            self._last_observed_period = None
            self._terminal_reason = None

    def start_worker(self) -> None:
        """Start one background period-boundary observer."""
        with self._lock:
            if self._worker is not None:
                raise RuntimeError("FT8 QSO coordinator worker is already running")
            self._stop_event.clear()
            worker = threading.Thread(
                target=self._worker_loop,
                name="ft8-qso",
                daemon=True,
            )
            self._worker = worker
            worker.start()

    def stop_worker(self) -> None:
        """Stop period observation without inventing another QSO."""
        self._stop_event.set()
        with self._lock:
            worker = self._worker
        if worker is not None:
            worker.join(timeout=3.0)
        with self._lock:
            self._worker = None

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            now = self._clock.now_utc()
            current = FT8Period.from_utc(now)
            delay_s = (current.index + 1) * 15.0 - now.timestamp()
            if delay_s < 0:
                self.on_receive_error("invalid negative FT8 boundary delay")
                return
            if self._stop_event.wait(delay_s):
                return
            self.tick()
            if self.state in {
                FT8QsoState.COMPLETED,
                FT8QsoState.ABORTED,
                FT8QsoState.RETRY_EXHAUSTED,
                FT8QsoState.ERROR,
            }:
                return

    def _fail_locked(self, reason: str) -> None:
        self._terminal_reason = reason
        self._controller.fail()
        self._stop_event.set()
