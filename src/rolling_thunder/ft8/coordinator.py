"""Checkpoint 7 coordinator for exactly one operator-authorized FT8 QSO."""

from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime

from rolling_thunder.ft8.domain import (
    FT8Decode,
    FT8MessageKind,
    FT8Period,
    FT8QsoContext,
    FT8QsoState,
)
from rolling_thunder.ft8.qso import FT8QsoController
from rolling_thunder.ft8.target_activity import TargetActivity
from rolling_thunder.ft8.timing import FT8Clock
from rolling_thunder.ft8.transmit import DigitalTransmitSession


@dataclass(frozen=True, slots=True)
class FT8QsoResult:
    """Immutable terminal result; persistence belongs to a later checkpoint."""

    status: FT8QsoState
    context: FT8QsoContext
    sent_report_db: int
    received_report_db: int | None
    started_utc: datetime
    ended_utc: datetime
    terminal_reason: str | None = None
    transmit_attempt_count: int = 0
    busy_extension_attempts: int = 0


class FT8QsoCoordinator:
    """Serialize timing, decoder events, aborts, and one QSO controller."""

    def __init__(
        self,
        transmit_session: DigitalTransmitSession,
        clock: FT8Clock,
        *,
        attempts_per_state: int = 6,
        terminal_result_handler: Callable[[FT8QsoResult], object] | None = None,
        activity_provider: Callable[[], TargetActivity | None] | None = None,
    ) -> None:
        self._transmit_session = transmit_session
        self._controller = FT8QsoController(
            transmit_session,
            attempts_per_state=attempts_per_state,
        )
        self._clock = clock
        self._lock = threading.RLock()
        self._cancel_lock = threading.Lock()
        self._session_cancelled = False
        self._stop_event = threading.Event()
        self._worker: threading.Thread | None = None
        self._last_observed_period: FT8Period | None = None
        self._last_clock_utc: datetime | None = None
        self._last_monotonic: float | None = None
        self._terminal_reason: str | None = None
        self._started_utc: datetime | None = None
        self._received_report_db: int | None = None
        self._result: FT8QsoResult | None = None
        self._terminal_result_handler = terminal_result_handler
        self._activity_provider = activity_provider

    # Presentation-only reads intentionally do not acquire the coordinator lock.
    # The worker holds it while playing up to a complete FT8 transmit slot;
    # blocking the UI on it hides TX RUNNING until PTT has already released.
    # Mutating operations and transmit authorization remain locked.
    @property
    def state(self) -> FT8QsoState:
        return self._controller.state

    @property
    def context(self) -> FT8QsoContext | None:
        return self._controller.context

    @property
    def attempt_count(self) -> int:
        return self._controller.attempt_count

    @property
    def attempts_per_state(self) -> int:
        """Current effective retry limit for the UI, including busy extension."""
        return self._controller.effective_attempt_limit

    @property
    def terminal_reason(self) -> str | None:
        return self._terminal_reason

    @property
    def result(self) -> FT8QsoResult | None:
        return self._result

    def authorize(self, context: FT8QsoContext) -> None:
        """Freeze exactly one operator-selected station into this coordinator."""
        with self._lock:
            self._controller.authorize(context)
            self._last_observed_period = context.authorized_period
            self._last_clock_utc = self._clock.now_utc()
            self._last_monotonic = self._clock.monotonic()
            self._terminal_reason = None
            self._session_cancelled = False
            self._started_utc = None
            inbound = context.responder_inbound
            self._received_report_db = (
                None if inbound is None else inbound.report_db
            )
            self._result = None

    def start_qso(self) -> None:
        """Start deterministic slot-driven QSO operation."""
        with self._lock:
            self._controller.start()
            self._started_utc = self._clock.now_utc()

    def tick(self) -> None:
        """Process the current UTC period at most once."""
        with self._lock:
            now_utc = self._clock.now_utc()
            monotonic_now = self._clock.monotonic()
            if self._last_clock_utc is not None and self._last_monotonic is not None:
                utc_delta = (now_utc - self._last_clock_utc).total_seconds()
                monotonic_delta = monotonic_now - self._last_monotonic
                if utc_delta < 0:
                    self._fail_locked("system UTC moved backward")
                    return
                if monotonic_delta < 0:
                    self._fail_locked("monotonic clock moved backward")
                    return
                if abs(utc_delta - monotonic_delta) > 1.0:
                    self._fail_locked("system UTC and monotonic clocks diverged")
                    return
            self._last_clock_utc = now_utc
            self._last_monotonic = monotonic_now

            period = FT8Period.from_utc(now_utc)
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
                if self._activity_provider is not None:
                    self._controller.observe_target_activity(self._activity_provider(), period)
                self._controller.on_period(period)
            except (OSError, RuntimeError, ValueError) as exc:
                self._fail_locked(str(exc))
                return
            self._capture_terminal_result_locked()

    def on_decodes(self, decodes: Sequence[FT8Decode]) -> None:
        """Forward normalized decodes; the controller filters authorization relevance."""
        with self._lock:
            for decode in decodes:
                before = self._controller.state
                self._controller.on_decode(decode)
                after = self._controller.state
                if (
                    (
                        before is FT8QsoState.WAIT_REPORT
                        and after is FT8QsoState.TX_R_REPORT
                        and decode.kind is FT8MessageKind.REPORT
                    )
                    or (
                        before is FT8QsoState.WAIT_R_REPORT
                        and after is FT8QsoState.TX_73
                        and decode.kind is FT8MessageKind.R_REPORT
                    )
                ):
                    self._received_report_db = decode.report_db
            self._capture_terminal_result_locked()

    def on_receive_error(self, detail: str) -> None:
        """Fail an active QSO when its decoder/receive path becomes unavailable."""
        cancelled = self._cancel_transmit_session_once()
        with self._lock:
            if self._controller.state in {
                FT8QsoState.IDLE,
                FT8QsoState.COMPLETED,
                FT8QsoState.ABORTED,
                FT8QsoState.RETRY_EXHAUSTED,
                FT8QsoState.ERROR,
            }:
                return
            self._fail_locked(
                f"FT8 receive failure: {detail}",
                session_already_cancelled=cancelled,
            )

    def abort(self) -> None:
        """Idempotently abort and force the transmit session toward receive."""
        self._stop_event.set()
        cancelled = self._cancel_transmit_session_once()
        with self._lock:
            self._controller.abort(session_already_cancelled=cancelled)
            if self._controller.state is FT8QsoState.ABORTED:
                self._terminal_reason = "operator abort"
            self._capture_terminal_result_locked()

    def reset(self) -> None:
        """Reset only after a terminal QSO result."""
        with self._lock:
            self._controller.reset()
            self._last_observed_period = None
            self._last_clock_utc = None
            self._last_monotonic = None
            self._terminal_reason = None
            self._started_utc = None
            self._received_report_db = None
            self._result = None

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
            delay_s = self._next_worker_delay_s(now)
            if delay_s < 0:
                self.on_receive_error("invalid negative FT8 boundary delay")
                return
            if delay_s > 0 and self._stop_event.wait(delay_s):
                return
            self.tick()
            if self.state in {
                FT8QsoState.COMPLETED,
                FT8QsoState.ABORTED,
                FT8QsoState.RETRY_EXHAUSTED,
                FT8QsoState.ERROR,
            }:
                return

    def _next_worker_delay_s(self, now: datetime) -> float:
        """Return zero when an unprocessed period is already current.

        Physical FT8 transmit execution can occupy essentially the entire
        15-second slot and may return just after the following boundary.  In
        that case the worker must process the newly-current period immediately
        instead of sleeping until one more boundary and manufacturing a
        false "skipped an FT8 period" failure.
        """
        current = FT8Period.from_utc(now)
        with self._lock:
            previous = self._last_observed_period
        if previous is not None and current.index > previous.index:
            return 0.0
        return (current.index + 1) * 15.0 - now.timestamp()

    def _cancel_transmit_session_once(self) -> bool:
        """Cancel physical transmit authority at most once for this QSO."""
        with self._cancel_lock:
            if self._session_cancelled:
                return True
            self._transmit_session.cancel()
            self._session_cancelled = True
            return True

    def _fail_locked(
        self,
        reason: str,
        *,
        session_already_cancelled: bool = False,
    ) -> None:
        self._terminal_reason = reason
        self._controller.fail(session_already_cancelled=session_already_cancelled)
        self._capture_terminal_result_locked()
        self._stop_event.set()

    def _capture_terminal_result_locked(self) -> None:
        if self._result is not None:
            return
        state = self._controller.state
        if state not in {
            FT8QsoState.COMPLETED,
            FT8QsoState.ABORTED,
            FT8QsoState.RETRY_EXHAUSTED,
            FT8QsoState.ERROR,
        }:
            return
        context = self._controller.context
        started = self._started_utc
        if context is None or started is None:
            return
        result = FT8QsoResult(
            status=state,
            context=context,
            sent_report_db=context.signal_report_db,
            received_report_db=self._received_report_db,
            started_utc=started,
            ended_utc=self._clock.now_utc(),
            terminal_reason=self._terminal_reason,
            transmit_attempt_count=self._controller.total_transmit_attempts,
            busy_extension_attempts=self._controller.busy_extension_attempts,
        )
        self._result = result
        if self._terminal_result_handler is not None:
            self._terminal_result_handler(result)
