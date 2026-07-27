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
from rolling_thunder.pota_tune_intent import PotaTuneIntent
from rolling_thunder.pota_tune_presentation import (
    PotaTunePresentation,
    build_pota_tune_presentation,
)


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
    """Coordinate stage, confirm, execute, cancel, and presentation state."""

    def __init__(
        self,
        dashboard: PotaDashboardController,
        executor: PotaTuneIntentExecutor | None = None,
    ) -> None:
        self._dashboard = dashboard
        self._execution = PotaTuneExecutionController(
            executor or UnavailablePotaTuneExecutor(),
        )

    @property
    def result(self) -> PotaReceiveTuneResult | None:
        """Return the current execution result after context synchronization."""
        self._synchronize_context()
        return self._execution.result

    @property
    def presentation(self) -> PotaTunePresentation:
        """Return display state for the current intent and execution result."""
        self._synchronize_context()
        return build_pota_tune_presentation(
            self._dashboard.tune_intent,
            self._execution.result,
        )

    def request(self) -> PotaTuneIntent | None:
        """Stage the selected POTA spot and clear prior execution state."""
        self._execution.clear()
        return self._dashboard.request_tune_intent()

    def confirm(self) -> PotaTuneIntent | None:
        """Confirm the current staged intent without executing it."""
        self._execution.clear()
        return self._dashboard.confirm_tune_intent()

    def execute(self) -> PotaReceiveTuneResult:
        """Execute the current confirmed intent through the narrow boundary."""
        self._synchronize_context()
        return self._execution.execute(self._dashboard.tune_intent)

    def cancel(self) -> PotaTuneIntent | None:
        """Cancel the current intent and clear prior execution state."""
        self._execution.clear()
        return self._dashboard.cancel_tune_intent()

    def _synchronize_context(self) -> None:
        """Clear stale results when selection, filters, or intent change."""
        executed_intent = self._execution.executed_intent
        current_intent = self._dashboard.tune_intent

        if executed_intent is not None and executed_intent != current_intent:
            self._execution.clear()
