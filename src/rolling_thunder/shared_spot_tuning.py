"""Background execution boundary for confirmed shared-spot receive tuning."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from threading import Lock, Thread
from typing import Protocol

from rolling_thunder.domain import Frequency, RadioMode
from rolling_thunder.radio import RadioError
from rolling_thunder.receive_tuning import ReceiveTuneOutcome
from rolling_thunder.spot_selection import StagedSpotAction


class SharedSpotReceiveTuner(Protocol):
    """Ordered receive-only tuning capability used by shared spots."""

    def tune(
        self,
        frequency: Frequency,
        mode: RadioMode,
    ) -> ReceiveTuneOutcome:
        """Perform one verified ordered receive tune."""
        ...


class SharedSpotTuneState(StrEnum):
    """Observable states for one shared-spot tuning operation."""

    IDLE = "idle"
    TUNING = "tuning"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class SharedSpotTuneStatus:
    """Immutable result/state snapshot for shared receive tuning."""

    state: SharedSpotTuneState = SharedSpotTuneState.IDLE
    action: StagedSpotAction | None = None
    outcome: ReceiveTuneOutcome | None = None
    error: str | None = None

    @property
    def tuning(self) -> bool:
        """Return whether radio work is currently running."""
        return self.state is SharedSpotTuneState.TUNING


class SharedSpotTuneController:
    """Run one ordered receive tune at a time away from the UI thread."""

    def __init__(self, tuner: SharedSpotReceiveTuner) -> None:
        self._tuner = tuner
        self._lock = Lock()
        self._status = SharedSpotTuneStatus()

    @property
    def status(self) -> SharedSpotTuneStatus:
        """Return one consistent immutable tuning snapshot."""
        with self._lock:
            return self._status

    def start_tune(self, action: StagedSpotAction) -> bool:
        """Start one background tune; reject while another is active."""
        if not isinstance(action, StagedSpotAction):
            raise TypeError("action must be a StagedSpotAction")

        with self._lock:
            if self._status.tuning:
                return False
            self._status = SharedSpotTuneStatus(
                state=SharedSpotTuneState.TUNING,
                action=action,
            )

        Thread(
            target=self._tune_worker,
            args=(action,),
            daemon=True,
        ).start()
        return True

    def clear_result(self) -> None:
        """Clear a completed result without interrupting active radio work."""
        with self._lock:
            if self._status.tuning:
                return
            self._status = SharedSpotTuneStatus()

    def _tune_worker(self, action: StagedSpotAction) -> None:
        try:
            outcome = self._tuner.tune(
                action.frequency,
                action.mode,
            )
        except RadioError as error:
            with self._lock:
                self._status = SharedSpotTuneStatus(
                    state=SharedSpotTuneState.FAILED,
                    action=action,
                    error=str(error),
                )
            return

        with self._lock:
            self._status = SharedSpotTuneStatus(
                state=SharedSpotTuneState.SUCCEEDED,
                action=action,
                outcome=outcome,
            )
