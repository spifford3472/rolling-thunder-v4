"""Background FT8 QSO-start preparation and screen-exit restore control."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from threading import Lock, Thread

from rolling_thunder.domain import RadioState
from rolling_thunder.ft8.domain import FT8CQActivity
from rolling_thunder.ft8.performance import FT8AttemptSeed
from rolling_thunder.ft8.radio_preparation import (
    FT8RadioPreparationError,
    FT8RadioPreparationService,
)

WorkerLauncher = Callable[[Callable[[], None]], None]


def _launch_daemon(worker: Callable[[], None]) -> None:
    Thread(
        target=worker,
        daemon=True,
        name="rolling-thunder-ft8-qso-start",
    ).start()


FT8PreparedQsoStarter = Callable[[FT8CQActivity, RadioState, FT8AttemptSeed], None]
FT8PreparationFailureHandler = Callable[[FT8AttemptSeed, str], object]


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
        worker_launcher: WorkerLauncher = _launch_daemon,
    ) -> None:
        self._preparation = preparation
        self._start_prepared_qso = start_prepared_qso
        self._worker_launcher = worker_launcher
        self._preparation_failure_handler = preparation_failure_handler
        self._lock = Lock()
        self._status = FT8QsoStartStatus()
        self._exit_requested = False

    @property
    def status(self) -> FT8QsoStartStatus:
        with self._lock:
            return self._status

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

    def request_restore(self) -> bool:
        """Cancel a pending start and restore 100 W/AUTO without blocking caller."""
        with self._lock:
            self._exit_requested = True
            if self._status.state is FT8QsoStartState.RESTORING:
                return False
            if self._status.state is FT8QsoStartState.PREPARING:
                return True
            current_activity = self._status.activity
            current_seed = self._status.attempt_seed
            self._status = FT8QsoStartStatus(
                state=FT8QsoStartState.RESTORING,
                activity=current_activity,
                attempt_seed=current_seed,
            )

        self._worker_launcher(
            lambda: self._restore_worker(
                activity=current_activity,
                attempt_seed=current_seed,
            )
        )
        return True

    def _prepare_worker(
        self,
        activity: FT8CQActivity,
        attempt_seed: FT8AttemptSeed,
    ) -> None:
        try:
            prepared = self._preparation.prepare_for_qso()
        except FT8RadioPreparationError as error:
            self._handle_prepare_failure(activity, attempt_seed, error)
            return

        with self._lock:
            exit_requested = self._exit_requested
            if exit_requested:
                self._status = FT8QsoStartStatus(
                    state=FT8QsoStartState.RESTORING,
                    activity=activity,
                    attempt_seed=attempt_seed,
                )

        if exit_requested:
            self._restore_worker(
                activity=activity,
                attempt_seed=attempt_seed,
            )
            return

        try:
            self._start_prepared_qso(
                activity,
                prepared.radio_state,
                attempt_seed,
            )
        except (RuntimeError, ValueError) as error:
            self._handle_post_prepare_failure(
                activity,
                attempt_seed,
                f"FT8 QSO start failed after radio preparation: {error}",
            )
            return

        with self._lock:
            self._status = FT8QsoStartStatus(
                state=FT8QsoStartState.STARTED,
                activity=activity,
                attempt_seed=attempt_seed,
            )

    def _handle_post_prepare_failure(
        self,
        activity: FT8CQActivity,
        attempt_seed: FT8AttemptSeed,
        reason: str,
    ) -> None:
        failure_reason = reason
        try:
            self._preparation.restore_after_ft8()
        except FT8RadioPreparationError as restore_error:
            failure_reason = f"{failure_reason}; rollback failed: {restore_error}"

        handler = self._preparation_failure_handler
        if handler is not None:
            handler(attempt_seed, failure_reason)

        with self._lock:
            self._status = FT8QsoStartStatus(
                state=FT8QsoStartState.FAILED,
                activity=activity,
                error=failure_reason,
                attempt_seed=attempt_seed,
            )

    def _handle_prepare_failure(
        self,
        activity: FT8CQActivity,
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

        handler = self._preparation_failure_handler
        if handler is not None:
            handler(attempt_seed, preparation_error)

        with self._lock:
            self._status = FT8QsoStartStatus(
                state=FT8QsoStartState.FAILED,
                activity=activity,
                error=preparation_error,
                attempt_seed=attempt_seed,
            )

    def _restore_worker(
        self,
        *,
        activity: FT8CQActivity | None = None,
        attempt_seed: FT8AttemptSeed | None = None,
    ) -> None:
        try:
            self._preparation.restore_after_ft8()
        except FT8RadioPreparationError as error:
            with self._lock:
                self._status = FT8QsoStartStatus(
                    state=FT8QsoStartState.RESTORE_FAILED,
                    activity=activity,
                    error=str(error),
                    attempt_seed=attempt_seed,
                )
            return

        with self._lock:
            self._status = FT8QsoStartStatus(
                state=FT8QsoStartState.RESTORED,
                activity=activity,
                attempt_seed=attempt_seed,
            )
