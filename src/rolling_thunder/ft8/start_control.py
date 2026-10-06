"""Background FT8 QSO-start preparation and screen-exit restore control."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from threading import Lock, Thread

from rolling_thunder.domain import RadioState
from rolling_thunder.ft8.domain import FT8CQActivity, FT8IncomingCall
from rolling_thunder.ft8.performance import FT8AttemptSeed
from rolling_thunder.ft8.radio_preparation import (
    FT8RadioPreparationError,
    FT8RadioPreparationService,
)
from rolling_thunder.radio import RadioError

WorkerLauncher = Callable[[Callable[[], None]], None]


def _launch_daemon(worker: Callable[[], None]) -> None:
    Thread(
        target=worker,
        daemon=True,
        name="rolling-thunder-ft8-qso-start",
    ).start()


FT8QsoCandidate = FT8CQActivity | FT8IncomingCall
FT8PreparedQsoStarter = Callable[[FT8QsoCandidate, RadioState, FT8AttemptSeed], None]
FT8PreparationFailureHandler = Callable[[FT8AttemptSeed, str], object]
FT8FailureRecovery = Callable[[], object]


class FT8QsoStartState(StrEnum):
    IDLE = "idle"
    PREPARING = "preparing"
    STARTED = "started"
    FAILED = "failed"
    RESTORING = "restoring"
    RESTORED = "restored"
    RESTORE_FAILED = "restore_failed"


@dataclass(frozen=True, slots=True)
class FT8QsoStartStatus:
    state: FT8QsoStartState = FT8QsoStartState.IDLE
    activity: FT8CQActivity | None = None
    incoming_call: FT8IncomingCall | None = None
    error: str | None = None
    attempt_seed: FT8AttemptSeed | None = None

    @property
    def busy(self) -> bool:
        return self.state in {
            FT8QsoStartState.PREPARING,
            FT8QsoStartState.RESTORING,
        }


class FT8QsoStartController:
    """Prepare radio state off-thread before granting one existing QSO path."""

    def __init__(
        self,
        preparation: FT8RadioPreparationService,
        start_prepared_qso: FT8PreparedQsoStarter,
        *,
        preparation_failure_handler: FT8PreparationFailureHandler | None = None,
        failure_recovery: FT8FailureRecovery | None = None,
        worker_launcher: WorkerLauncher = _launch_daemon,
    ) -> None:
        self._preparation = preparation
        self._start_prepared_qso = start_prepared_qso
        self._worker_launcher = worker_launcher
        self._preparation_failure_handler = preparation_failure_handler
        self._failure_recovery = failure_recovery
        self._lock = Lock()
        self._status = FT8QsoStartStatus()
        self._exit_requested = False

    @property
    def status(self) -> FT8QsoStartStatus:
        with self._lock:
            return self._status

    def reset_to_idle(self) -> bool:
        """Clear one completed/failed start presentation before the next CQ."""
        with self._lock:
            if self._status.busy:
                return False
            self._exit_requested = False
            self._status = FT8QsoStartStatus()
            return True

    def start(
        self,
        activity: FT8CQActivity,
        *,
        attempt_seed: FT8AttemptSeed,
    ) -> bool:
        """Accept one selected CQ for fail-closed background preparation."""
        if not isinstance(activity, FT8CQActivity):
            raise TypeError("activity must be an FT8CQActivity")
        if not isinstance(attempt_seed, FT8AttemptSeed):
            raise TypeError("attempt_seed must be an FT8AttemptSeed")

        with self._lock:
            if self._status.busy:
                return False
            self._exit_requested = False
            self._status = FT8QsoStartStatus(
                state=FT8QsoStartState.PREPARING,
                activity=activity,
                attempt_seed=attempt_seed,
            )

        self._worker_launcher(
            lambda: self._prepare_worker(activity, attempt_seed)
        )
        return True

    def start_incoming(
        self,
        incoming: FT8IncomingCall,
        *,
        attempt_seed: FT8AttemptSeed,
    ) -> bool:
        """Accept one exact inbound decode for fail-closed responder preparation."""
        if not isinstance(incoming, FT8IncomingCall):
            raise TypeError("incoming must be an FT8IncomingCall")
        if not isinstance(attempt_seed, FT8AttemptSeed):
            raise TypeError("attempt_seed must be an FT8AttemptSeed")

        with self._lock:
            if self._status.busy:
                return False
            self._exit_requested = False
            self._status = FT8QsoStartStatus(
                state=FT8QsoStartState.PREPARING,
                incoming_call=incoming,
                attempt_seed=attempt_seed,
            )

        self._worker_launcher(lambda: self._prepare_worker(incoming, attempt_seed))
        return True

    def request_restore(self) -> bool:
        """Cancel a pending start and restore 100 W/AUTO without blocking caller."""
        with self._lock:
            self._exit_requested = True
            if self._status.state is FT8QsoStartState.RESTORING:
                return False
            if self._status.state is FT8QsoStartState.PREPARING:
                return True
            current_activity = self._status.activity
            current_incoming = self._status.incoming_call
            current_seed = self._status.attempt_seed
            self._status = FT8QsoStartStatus(
                state=FT8QsoStartState.RESTORING,
                activity=current_activity,
                incoming_call=current_incoming,
                attempt_seed=current_seed,
            )

        self._worker_launcher(
            lambda: self._restore_worker(
                activity=current_activity,
                incoming_call=current_incoming,
                attempt_seed=current_seed,
            )
        )
        return True

    def _prepare_worker(
        self,
        candidate: FT8QsoCandidate,
        attempt_seed: FT8AttemptSeed,
    ) -> None:
        try:
            prepared = self._preparation.prepare_for_qso(
                attempt_seed.tx_power_target_watts
            )
        except FT8RadioPreparationError as error:
            self._handle_prepare_failure(candidate, attempt_seed, error)
            return

        with self._lock:
            exit_requested = self._exit_requested
            if exit_requested:
                self._status = FT8QsoStartStatus(
                    state=FT8QsoStartState.RESTORING,
                    activity=candidate if isinstance(candidate, FT8CQActivity) else None,
                    incoming_call=(
                        candidate if isinstance(candidate, FT8IncomingCall) else None
                    ),
                    attempt_seed=attempt_seed,
                )

        if exit_requested:
            self._restore_worker(
                activity=candidate if isinstance(candidate, FT8CQActivity) else None,
                incoming_call=(
                    candidate if isinstance(candidate, FT8IncomingCall) else None
                ),
                attempt_seed=attempt_seed,
            )
            return

        try:
            self._start_prepared_qso(
                candidate,
                prepared.radio_state,
                attempt_seed,
            )
        except (RuntimeError, ValueError) as error:
            self._handle_post_prepare_failure(
                candidate,
                attempt_seed,
                f"FT8 QSO start failed after radio preparation: {error}",
            )
            return

        with self._lock:
            self._status = FT8QsoStartStatus(
                state=FT8QsoStartState.STARTED,
                activity=candidate if isinstance(candidate, FT8CQActivity) else None,
                incoming_call=(
                    candidate if isinstance(candidate, FT8IncomingCall) else None
                ),
                attempt_seed=attempt_seed,
            )

    def _handle_post_prepare_failure(
        self,
        candidate: FT8QsoCandidate,
        attempt_seed: FT8AttemptSeed,
        reason: str,
    ) -> None:
        failure_reason = reason
        try:
            self._preparation.restore_after_ft8()
        except FT8RadioPreparationError as restore_error:
            failure_reason = f"{failure_reason}; rollback failed: {restore_error}"
        failure_reason = self._recover_ft8_receive_profile(failure_reason)

        handler = self._preparation_failure_handler
        if handler is not None:
            handler(attempt_seed, failure_reason)

        with self._lock:
            self._status = FT8QsoStartStatus(
                state=FT8QsoStartState.FAILED,
                activity=candidate if isinstance(candidate, FT8CQActivity) else None,
                incoming_call=(
                    candidate if isinstance(candidate, FT8IncomingCall) else None
                ),
                error=failure_reason,
                attempt_seed=attempt_seed,
            )

    def _handle_prepare_failure(
        self,
        candidate: FT8QsoCandidate,
        attempt_seed: FT8AttemptSeed,
        error: FT8RadioPreparationError,
    ) -> None:
        """Rollback partial preparation while preserving the preparation error."""
        preparation_error = str(error)
        try:
            self._preparation.restore_after_ft8()
        except FT8RadioPreparationError as restore_error:
            preparation_error = (
                f"{preparation_error}; rollback failed: {restore_error}"
            )
        preparation_error = self._recover_ft8_receive_profile(preparation_error)

        handler = self._preparation_failure_handler
        if handler is not None:
            handler(attempt_seed, preparation_error)

        with self._lock:
            self._status = FT8QsoStartStatus(
                state=FT8QsoStartState.FAILED,
                activity=candidate if isinstance(candidate, FT8CQActivity) else None,
                incoming_call=(
                    candidate if isinstance(candidate, FT8IncomingCall) else None
                ),
                error=preparation_error,
                attempt_seed=attempt_seed,
            )

    def _recover_ft8_receive_profile(self, reason: str) -> str:
        with self._lock:
            if self._exit_requested:
                return reason
        recovery = self._failure_recovery
        if recovery is None:
            return reason
        try:
            recovery()
        except (RadioError, RuntimeError, ValueError) as error:
            return f"{reason}; FT8 receive-profile recovery failed: {error}"
        return reason

    def _restore_worker(
        self,
        *,
        activity: FT8CQActivity | None = None,
        incoming_call: FT8IncomingCall | None = None,
        attempt_seed: FT8AttemptSeed | None = None,
    ) -> None:
        try:
            self._preparation.restore_after_ft8()
        except FT8RadioPreparationError as error:
            with self._lock:
                self._status = FT8QsoStartStatus(
                    state=FT8QsoStartState.RESTORE_FAILED,
                    activity=activity,
                    incoming_call=incoming_call,
                    error=str(error),
                    attempt_seed=attempt_seed,
                )
            return

        with self._lock:
            self._status = FT8QsoStartStatus(
                state=FT8QsoStartState.RESTORED,
                activity=activity,
                incoming_call=incoming_call,
                attempt_seed=attempt_seed,
            )
