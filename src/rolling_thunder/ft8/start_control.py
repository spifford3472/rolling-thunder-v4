"""Background FT8 QSO-start preparation and screen-exit restore control."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from threading import Lock, Thread
from typing import Protocol

from rolling_thunder.domain import RadioState
from rolling_thunder.ft8.domain import FT8CQActivity
from rolling_thunder.ft8.radio_preparation import (
    FT8PreparedRadioState,
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


class FT8PreparedQsoStarter(Protocol):
    """Start exactly one QSO after radio preparation is verified."""

    def __call__(self, activity: FT8CQActivity, radio_state: RadioState) -> None:
        ...


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
        worker_launcher: WorkerLauncher = _launch_daemon,
    ) -> None:
        self._preparation = preparation
        self._start_prepared_qso = start_prepared_qso
        self._worker_launcher = worker_launcher
        self._lock = Lock()
        self._status = FT8QsoStartStatus()
        self._exit_requested = False

    @property
    def status(self) -> FT8QsoStartStatus:
        with self._lock:
            return self._status

    def start(self, activity: FT8CQActivity) -> bool:
        """Accept one selected CQ for fail-closed background preparation."""
        if not isinstance(activity, FT8CQActivity):
            raise TypeError("activity must be an FT8CQActivity")

        with self._lock:
            if self._status.busy:
                return False
            self._exit_requested = False
            self._status = FT8QsoStartStatus(
                state=FT8QsoStartState.PREPARING,
                activity=activity,
            )

        self._worker_launcher(lambda: self._prepare_worker(activity))
        return True

    def request_restore(self) -> bool:
        """Cancel a pending start and restore 100 W/AUTO without blocking caller."""
        with self._lock:
            self._exit_requested = True
            if self._status.state is FT8QsoStartState.RESTORING:
                return False
            if self._status.state is FT8QsoStartState.PREPARING:
                return True
            self._status = FT8QsoStartStatus(state=FT8QsoStartState.RESTORING)

        self._worker_launcher(self._restore_worker)
        return True

    def _prepare_worker(self, activity: FT8CQActivity) -> None:
        try:
            prepared = self._preparation.prepare_for_qso()
        except FT8RadioPreparationError as error:
            self._handle_prepare_failure(activity, error)
            return

        with self._lock:
            exit_requested = self._exit_requested
            if exit_requested:
                self._status = FT8QsoStartStatus(
                    state=FT8QsoStartState.RESTORING,
                    activity=activity,
                )

        if exit_requested:
            self._restore_worker(activity=activity)
            return

        try:
            self._start_prepared_qso(activity, prepared.radio_state)
        except (RuntimeError, ValueError) as error:
            with self._lock:
                self._status = FT8QsoStartStatus(
                    state=FT8QsoStartState.FAILED,
                    activity=activity,
                    error=str(error),
                )
            return

        with self._lock:
            self._status = FT8QsoStartStatus(
                state=FT8QsoStartState.STARTED,
                activity=activity,
            )

    def _handle_prepare_failure(
        self,
        activity: FT8CQActivity,
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

        with self._lock:
            self._status = FT8QsoStartStatus(
                state=FT8QsoStartState.FAILED,
                activity=activity,
                error=preparation_error,
            )

    def _restore_worker(self, *, activity: FT8CQActivity | None = None) -> None:
        try:
            self._preparation.restore_after_ft8()
        except FT8RadioPreparationError as error:
            with self._lock:
                self._status = FT8QsoStartStatus(
                    state=FT8QsoStartState.RESTORE_FAILED,
                    activity=activity,
                    error=str(error),
                )
            return

        with self._lock:
            self._status = FT8QsoStartStatus(
                state=FT8QsoStartState.RESTORED,
                activity=activity,
            )
