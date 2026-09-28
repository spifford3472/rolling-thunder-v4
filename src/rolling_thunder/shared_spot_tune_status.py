"""Operator status presentation for background shared-spot receive tuning."""

from __future__ import annotations

from typing import Protocol

from rolling_thunder.shared_spot_tuning import (
    SharedSpotTuneState,
    SharedSpotTuneStatus,
)
from rolling_thunder.status_messages import (
    StatusMessageService,
    StatusPresentation,
)

SHARED_TUNE_STATUS_KEY = "radio.shared-spot-tune"
SHARED_TUNE_STATUS_PRIORITY = 80
SHARED_TUNE_SUCCESS_DURATION_S = 5.0
SHARED_TUNE_FAILURE_DURATION_S = 8.0

ATAS_RETUNE_STATUS_KEY = "radio.atas-retune"
ATAS_RETUNE_STATUS_PRIORITY = 100
ATAS_RETUNE_STATUS_DURATION_S = 10.0


class SharedSpotTuneStatusProvider(Protocol):
    """Immutable background-tune status consumed by presentation."""

    @property
    def status(self) -> SharedSpotTuneStatus:
        """Return the current immutable tuning status."""

    def clear_result(self) -> None:
        """Clear a completed result without interrupting active tuning."""


class SharedSpotTuneStatusController:
    """Publish each background receive-tune transition exactly once."""

    def __init__(
        self,
        tuning: SharedSpotTuneStatusProvider,
        status_messages: StatusMessageService,
    ) -> None:
        self._tuning = tuning
        self._status_messages = status_messages
        self._last_status: SharedSpotTuneStatus | None = None

    def refresh(self) -> bool:
        """Publish a newly observed tune transition, if one exists."""
        status = self._tuning.status
        if status == self._last_status:
            return False

        self._last_status = status

        if status.state is SharedSpotTuneState.IDLE:
            return False

        action = status.action
        if action is None:
            return False

        target = (
            f"{action.callsign} — "
            f"{action.frequency.hz / 1_000_000:.3f} MHz "
            f"{action.mode.value}"
        )

        if status.state is SharedSpotTuneState.TUNING:
            self._status_messages.publish(
                replacement_key=SHARED_TUNE_STATUS_KEY,
                text=f"TUNING {target}",
                presentation=StatusPresentation.NORMAL,
                priority=SHARED_TUNE_STATUS_PRIORITY,
            )
            return True

        if status.state is SharedSpotTuneState.SUCCEEDED:
            self._status_messages.publish(
                replacement_key=SHARED_TUNE_STATUS_KEY,
                text=f"TUNED {target}",
                presentation=StatusPresentation.SUCCESS,
                priority=SHARED_TUNE_STATUS_PRIORITY,
                duration_s=SHARED_TUNE_SUCCESS_DURATION_S,
            )

            outcome = status.outcome
            if outcome is not None and outcome.band_changed:
                band_label = outcome.target_band.value.removesuffix("m")
                self._status_messages.publish(
                    replacement_key=ATAS_RETUNE_STATUS_KEY,
                    text=f"SET BAND TO {band_label} METERS — TUNE ATAS-120",
                    presentation=StatusPresentation.AMBER,
                    priority=ATAS_RETUNE_STATUS_PRIORITY,
                    duration_s=ATAS_RETUNE_STATUS_DURATION_S,
                )

            self._tuning.clear_result()
            return True

        self._status_messages.publish(
            replacement_key=SHARED_TUNE_STATUS_KEY,
            text=f"TUNE FAILED — {status.error or 'UNKNOWN RADIO ERROR'}",
            presentation=StatusPresentation.ERROR,
            priority=SHARED_TUNE_STATUS_PRIORITY,
            duration_s=SHARED_TUNE_FAILURE_DURATION_S,
        )
        self._tuning.clear_result()
        return True
