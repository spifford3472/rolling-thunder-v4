"""Typed two-press repeater configuration workflow with background radio work."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from threading import Lock, Thread

from rolling_thunder.fm_repeater import (
    FmRepeaterConfigurableRadio,
    FmRepeaterConfigurationOutcome,
    FmRepeaterConfigurationRequest,
    FmRepeaterConfigurationStatus,
    FmRepeaterShiftDirection,
)
from rolling_thunder.radio import RadioError
from rolling_thunder.repeater_domain import RepeaterRecord

WorkerLauncher = Callable[[Callable[[], None]], None]


@dataclass(frozen=True, slots=True)
class StagedRepeaterRadioAction:
    """Exact selected repeater and action-critical radio request captured without I/O."""

    repeater: RepeaterRecord
    request: FmRepeaterConfigurationRequest

    @classmethod
    def from_repeater(cls, repeater: RepeaterRecord) -> StagedRepeaterRadioAction:
        """Capture an immutable typed request from one exact source record."""
        return cls(
            repeater=repeater,
            request=FmRepeaterConfigurationRequest(
                rx_frequency=repeater.rx_frequency,
                shift_direction=FmRepeaterShiftDirection(repeater.shift_direction.value),
                offset_hz=repeater.offset_hz,
                rx_tone_hz=repeater.rx_tone_hz,
                tx_tone_hz=repeater.tx_tone_hz,
            ),
        )

    @property
    def stable_key(self) -> str:
        return self.repeater.stable_key

    def matches(self, repeater: RepeaterRecord) -> bool:
        """Require the same source record, preventing execution after critical mutation."""
        return self.repeater == repeater


class RepeaterConfigurationService:
    """Application service routing an exact staged request through typed radio capability."""

    def __init__(self, radio: FmRepeaterConfigurableRadio) -> None:
        self._radio = radio

    def configure(
        self,
        action: StagedRepeaterRadioAction,
    ) -> FmRepeaterConfigurationOutcome:
        """Configure exactly the request captured by the first operator press."""
        return self._radio.configure_fm_repeater(action.request)


class RepeaterConfigurationStatusKind(StrEnum):
    """Observable nonblocking execution state for the repeater panel."""

    IDLE = "idle"
    CONFIGURING = "configuring"
    CONFIGURED = "configured"
    MANUAL_HANDOFF = "manual_handoff"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class RepeaterConfigurationStatus:
    """Immutable UI-safe status from the background radio worker."""

    kind: RepeaterConfigurationStatusKind = RepeaterConfigurationStatusKind.IDLE
    pending_action: StagedRepeaterRadioAction | None = None
    completed_action: StagedRepeaterRadioAction | None = None
    outcome: FmRepeaterConfigurationOutcome | None = None
    last_error: str | None = None
    completion_revision: int = 0

    @property
    def configuring(self) -> bool:
        return self.kind is RepeaterConfigurationStatusKind.CONFIGURING


def _launch_daemon(worker: Callable[[], None]) -> None:
    Thread(target=worker, daemon=True).start()


class RepeaterConfigurationController:
    """Execute at most one explicitly confirmed repeater action away from Tk callbacks."""

    def __init__(
        self,
        service: RepeaterConfigurationService,
        *,
        worker_launcher: WorkerLauncher = _launch_daemon,
    ) -> None:
        self._service = service
        self._worker_launcher = worker_launcher
        self._lock = Lock()
        self._status = RepeaterConfigurationStatus()

    @property
    def status(self) -> RepeaterConfigurationStatus:
        with self._lock:
            return self._status

    @property
    def configuring(self) -> bool:
        """Return whether a confirmed repeater request currently owns the radio worker."""
        with self._lock:
            return self._status.configuring

    def start_configure(self, action: StagedRepeaterRadioAction) -> bool:
        """Accept one exact second-press action without blocking the caller."""
        with self._lock:
            if self._status.configuring:
                return False
            revision = self._status.completion_revision
            self._status = RepeaterConfigurationStatus(
                kind=RepeaterConfigurationStatusKind.CONFIGURING,
                pending_action=action,
                completion_revision=revision,
            )

        self._worker_launcher(lambda: self._configure_worker(action, revision))
        return True

    def _configure_worker(
        self,
        action: StagedRepeaterRadioAction,
        previous_revision: int,
    ) -> None:
        try:
            outcome = self._service.configure(action)
        except RadioError as error:
            with self._lock:
                self._status = RepeaterConfigurationStatus(
                    kind=RepeaterConfigurationStatusKind.FAILED,
                    completed_action=action,
                    last_error=str(error),
                    completion_revision=previous_revision + 1,
                )
            return

        kind = (
            RepeaterConfigurationStatusKind.CONFIGURED
            if outcome.status is FmRepeaterConfigurationStatus.CONFIGURED
            else RepeaterConfigurationStatusKind.MANUAL_HANDOFF
        )
        with self._lock:
            self._status = RepeaterConfigurationStatus(
                kind=kind,
                completed_action=action,
                outcome=outcome,
                completion_revision=previous_revision + 1,
            )
