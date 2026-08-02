"""UI-safe orchestration for explicit POTA receive-tune actions."""

from rolling_thunder.pota_dashboard_controller import PotaDashboardController
from rolling_thunder.pota_receive_tune_executor import (
    PotaReceiveTuneResult,
    PotaReceiveTuneResultStatus,
)
from rolling_thunder.pota_tune_execution_controller import (
    PotaTuneExecutionController,
    PotaTuneIntentExecutor,
)
from rolling_thunder.pota_tune_intent import PotaTuneIntent, PotaTuneIntentStatus
from rolling_thunder.pota_tune_presentation import (
    PotaTunePresentation,
    build_pota_tune_presentation,
)
from rolling_thunder.radio import RadioBand


class UnavailablePotaTuneExecutor:
    """Reject execution when no receive-only radio boundary was injected."""

    def execute(self, intent: PotaTuneIntent) -> PotaReceiveTuneResult:
        """Return a typed rejection without touching radio hardware."""
        return PotaReceiveTuneResult(
            status=PotaReceiveTuneResultStatus.REJECTED,
            frequency=intent.frequency,
            mode=intent.mode,
            error="Receive tuning is unavailable in this runtime.",
        )


class PotaTuneUiController:
    """Coordinate tune intent, execution, warning, and presentation state."""

    def __init__(
        self,
        dashboard: PotaDashboardController,
        executor: PotaTuneIntentExecutor | None = None,
    ) -> None:
        self._dashboard = dashboard
        self._execution = PotaTuneExecutionController(
            executor or UnavailablePotaTuneExecutor(),
        )
        self._retune_warning_band: RadioBand | None = None

    @property
    def result(self) -> PotaReceiveTuneResult | None:
        """Return the current execution result after context synchronization."""
        self._synchronize_context()
        return self._execution.result

    @property
    def retune_warning_active(self) -> bool:
        """Return whether an ATAS-120 retune warning awaits acknowledgement."""
        return self._retune_warning_band is not None

    @property
    def retune_warning_line(self) -> str | None:
        """Return the sticky ATAS-120 warning for the verified target band."""
        band = self._retune_warning_band
        if band is None:
            return None
        band_label = band.value.removesuffix("m")
        return (
            f"BAND CHANGED TO {band_label} METERS — RETUNE ATAS-120"
        )

    @property
    def presentation(self) -> PotaTunePresentation:
        """Return POTA-local intent and execution presentation state."""
        self._synchronize_context()
        return build_pota_tune_presentation(
            self._dashboard.tune_intent,
            self._execution.result,
        )

    def advance(self) -> bool:
        """Advance exactly one guarded stage, confirm, or execute step."""
        self._synchronize_context()
        intent = self._dashboard.tune_intent

        if intent is None or intent.status is PotaTuneIntentStatus.CANCELLED:
            return self.request() is not None

        if intent.status is PotaTuneIntentStatus.PENDING_CONFIRMATION:
            confirmed = self.confirm()
            return (
                confirmed is not None
                and confirmed.status is PotaTuneIntentStatus.CONFIRMED
            )

        if self._execution.result is not None:
            return False

        self.execute()
        return True

    def request(self) -> PotaTuneIntent | None:
        """Stage the selected POTA spot and clear prior execution state."""
        self._execution.clear()
        return self._dashboard.request_tune_intent()

    def confirm(self) -> PotaTuneIntent | None:
        """Confirm the current staged intent without executing it."""
        self._execution.clear()
        return self._dashboard.confirm_tune_intent()

    def execute(self) -> PotaReceiveTuneResult:
        """Execute confirmed intent and publish a verified band-change warning."""
        self._synchronize_context()
        result = self._execution.execute(self._dashboard.tune_intent)
        if result.band_changed and result.target_band is not None:
            self._retune_warning_band = result.target_band
        return result

    def cancel(self) -> PotaTuneIntent | None:
        """Cancel the current intent and acknowledge any retune warning."""
        self._execution.clear()
        self.acknowledge_retune_warning()
        return self._dashboard.cancel_tune_intent()

    def acknowledge_retune_warning(self) -> bool:
        """Clear the sticky warning only after an explicit operator action."""
        if self._retune_warning_band is None:
            return False
        self._retune_warning_band = None
        return True

    def _synchronize_context(self) -> None:
        """Clear stale results without clearing a safety warning."""
        executed_intent = self._execution.executed_intent
        current_intent = self._dashboard.tune_intent

        if executed_intent is not None and executed_intent != current_intent:
            self._execution.clear()
