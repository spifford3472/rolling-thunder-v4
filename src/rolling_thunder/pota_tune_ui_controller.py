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
from rolling_thunder.status_messages import (
    StatusMessageService,
    StatusPresentation,
)

ATAS_RETUNE_STATUS_KEY = "radio.atas-retune"
ATAS_RETUNE_STATUS_PRIORITY = 100
ATAS_RETUNE_STATUS_DURATION_S = 10.0


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
    """Coordinate tune intent, execution, status publication, and presentation."""

    def __init__(
        self,
        dashboard: PotaDashboardController,
        executor: PotaTuneIntentExecutor | None = None,
        status_messages: StatusMessageService | None = None,
    ) -> None:
        self._dashboard = dashboard
        self._execution = PotaTuneExecutionController(
            executor or UnavailablePotaTuneExecutor(),
        )
        self._status_messages = (
            status_messages if status_messages is not None else StatusMessageService()
        )

    @property
    def result(self) -> PotaReceiveTuneResult | None:
        """Return the current execution result after context synchronization."""
        self._synchronize_context()
        return self._execution.result

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
            return confirmed is not None and confirmed.status is PotaTuneIntentStatus.CONFIRMED

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
        """Execute confirmed intent and publish a cross-band operator warning."""
        self._synchronize_context()
        result = self._execution.execute(self._dashboard.tune_intent)
        if result.band_changed and result.target_band is not None:
            band_label = result.target_band.value.removesuffix("m")
            self._status_messages.publish(
                replacement_key=ATAS_RETUNE_STATUS_KEY,
                text=f"SET BAND TO {band_label} METERS — TUNE ATAS-120",
                presentation=StatusPresentation.AMBER,
                priority=ATAS_RETUNE_STATUS_PRIORITY,
                duration_s=ATAS_RETUNE_STATUS_DURATION_S,
            )
        return result

    def cancel(self) -> PotaTuneIntent | None:
        """Cancel the current intent without changing timed status messages."""
        self._execution.clear()
        return self._dashboard.cancel_tune_intent()

    def _synchronize_context(self) -> None:
        """Clear stale execution results without changing independent status."""
        executed_intent = self._execution.executed_intent
        current_intent = self._dashboard.tune_intent

        if executed_intent is not None and executed_intent != current_intent:
            self._execution.clear()
