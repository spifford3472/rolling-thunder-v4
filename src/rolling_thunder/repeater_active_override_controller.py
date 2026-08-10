"""Background persistence boundary for confirmed repeater Active overrides."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock, Thread
from typing import Protocol

from rolling_thunder.repeater_domain import RepeaterIdentity
from rolling_thunder.repeater_panel import StagedRepeaterActiveAction
from rolling_thunder.storage import StorageError

WorkerLauncher = Callable[[Callable[[], None]], None]


class RepeaterActiveOverrideWriter(Protocol):
    """Persistence capability used only after explicit second activation."""

    def write(self, identity: RepeaterIdentity, active: bool) -> None:
        """Persist one exact Active override."""


@dataclass(frozen=True, slots=True)
class RepeaterActiveOverrideStatus:
    """Immutable observable state for background Active persistence."""

    saving: bool = False
    pending_action: StagedRepeaterActiveAction | None = None
    last_completed_action: StagedRepeaterActiveAction | None = None
    completion_revision: int = 0
    last_error: str | None = None


def _launch_daemon(worker: Callable[[], None]) -> None:
    Thread(target=worker, daemon=True).start()


class RepeaterActiveOverrideController:
    """Persist one confirmed Active action at a time away from Tk callbacks."""

    def __init__(
        self,
        repository: RepeaterActiveOverrideWriter,
        *,
        worker_launcher: WorkerLauncher = _launch_daemon,
    ) -> None:
        self._repository = repository
        self._worker_launcher = worker_launcher
        self._lock = Lock()
        self._status = RepeaterActiveOverrideStatus()

    @property
    def status(self) -> RepeaterActiveOverrideStatus:
        """Return one consistent immutable persistence snapshot."""
        with self._lock:
            return self._status

    def start_persist(self, action: StagedRepeaterActiveAction) -> bool:
        """Submit one already-confirmed exact action without blocking the caller."""
        with self._lock:
            if self._status.saving:
                return False
            revision = self._status.completion_revision
            self._status = RepeaterActiveOverrideStatus(
                saving=True,
                pending_action=action,
                completion_revision=revision,
            )

        self._worker_launcher(lambda: self._persist_worker(action, revision))
        return True

    def _persist_worker(
        self,
        action: StagedRepeaterActiveAction,
        previous_revision: int,
    ) -> None:
        try:
            self._repository.write(action.repeater.identity, action.target_active)
        except StorageError as error:
            with self._lock:
                self._status = RepeaterActiveOverrideStatus(
                    completion_revision=previous_revision,
                    last_error=str(error),
                )
            return

        with self._lock:
            self._status = RepeaterActiveOverrideStatus(
                last_completed_action=action,
                completion_revision=previous_revision + 1,
            )
