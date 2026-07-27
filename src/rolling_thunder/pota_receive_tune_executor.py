"""Execute confirmed POTA receive tuning through a minimal radio boundary."""

from enum import StrEnum
from typing import Protocol

from rolling_thunder.domain import DomainModel, Frequency, RadioMode, RadioState
from rolling_thunder.pota_tune_intent import (
    PotaTuneIntent,
    PotaTuneIntentStatus,
)
from rolling_thunder.radio import RadioError


class PotaReceiveTuneRadio(Protocol):
    """Receive-only radio operations required for POTA tuning.

    This boundary deliberately exposes no connect, disconnect, band-change,
    transmit, PTT, MOX, tuner, power, or audio operations.
    """

    def set_frequency(self, frequency: Frequency) -> RadioState:
        """Set an operator-confirmed receive frequency."""
        ...

    def set_mode(self, mode: RadioMode) -> RadioState:
        """Set an operator-confirmed receive mode."""
        ...


class PotaReceiveTuneResultStatus(StrEnum):
    """Outcomes from one receive-only tune execution attempt."""

    SUCCEEDED = "succeeded"
    REJECTED = "rejected"
    FAILED = "failed"


class PotaReceiveTuneResult(DomainModel):
    """Immutable result from attempting one confirmed receive tune."""

    status: PotaReceiveTuneResultStatus
    frequency: Frequency | None = None
    mode: RadioMode | None = None
    error: str | None = None


class PotaReceiveTuneExecutor:
    """Apply confirmed frequency and mode without any transmit capability."""

    def __init__(self, radio: PotaReceiveTuneRadio) -> None:
        self._radio = radio

    def execute(self, intent: PotaTuneIntent) -> PotaReceiveTuneResult:
        """Execute only confirmed intent, setting frequency before mode."""
        if intent.status is not PotaTuneIntentStatus.CONFIRMED:
            return PotaReceiveTuneResult(
                status=PotaReceiveTuneResultStatus.REJECTED,
                error="POTA tune intent must be confirmed before execution.",
            )

        try:
            self._radio.set_frequency(intent.frequency)
        except RadioError as error:
            return PotaReceiveTuneResult(
                status=PotaReceiveTuneResultStatus.FAILED,
                frequency=intent.frequency,
                error=f"Unable to set receive frequency: {error}",
            )

        try:
            self._radio.set_mode(intent.mode)
        except RadioError as error:
            return PotaReceiveTuneResult(
                status=PotaReceiveTuneResultStatus.FAILED,
                frequency=intent.frequency,
                mode=intent.mode,
                error=f"Receive frequency set, but mode change failed: {error}",
            )

        return PotaReceiveTuneResult(
            status=PotaReceiveTuneResultStatus.SUCCEEDED,
            frequency=intent.frequency,
            mode=intent.mode,
        )
