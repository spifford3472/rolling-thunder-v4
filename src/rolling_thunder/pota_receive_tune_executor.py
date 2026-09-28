"""Execute confirmed POTA receive tuning through the ordered tuner."""

from enum import StrEnum
from typing import Protocol

from rolling_thunder.domain import DomainModel, Frequency, RadioMode
from rolling_thunder.pota_tune_intent import (
    PotaTuneIntent,
    PotaTuneIntentStatus,
)
from rolling_thunder.radio import RadioBand, RadioError
from rolling_thunder.receive_tuning import ReceiveTuneOutcome


class PotaReceiveTuner(Protocol):
    """Single ordered receive-tuning capability used by POTA."""

    def tune(
        self,
        frequency: Frequency,
        mode: RadioMode,
    ) -> ReceiveTuneOutcome:
        """Perform one verified band-first receive tune."""
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
    target_band: RadioBand | None = None
    band_changed: bool = False
    error: str | None = None


class PotaReceiveTuneExecutor:
    """Apply confirmed POTA intent through the ordered receive tuner."""

    def __init__(self, tuner: PotaReceiveTuner) -> None:
        self._tuner = tuner

    def execute(self, intent: PotaTuneIntent) -> PotaReceiveTuneResult:
        """Execute only confirmed operator intent."""
        if intent.status is not PotaTuneIntentStatus.CONFIRMED:
            return PotaReceiveTuneResult(
                status=PotaReceiveTuneResultStatus.REJECTED,
                error="POTA tune intent must be confirmed before execution.",
            )

        try:
            outcome = self._tuner.tune(
                intent.frequency,
                intent.mode,
            )
        except RadioError as error:
            return PotaReceiveTuneResult(
                status=PotaReceiveTuneResultStatus.FAILED,
                frequency=intent.frequency,
                mode=intent.mode,
                error=f"Unable to complete ordered receive tune: {error}",
            )

        return PotaReceiveTuneResult(
            status=PotaReceiveTuneResultStatus.SUCCEEDED,
            frequency=outcome.state.frequency,
            mode=outcome.state.mode,
            target_band=outcome.target_band,
            band_changed=outcome.band_changed,
        )
