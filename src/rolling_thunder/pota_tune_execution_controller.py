"""One-shot orchestration for explicitly confirmed POTA receive tuning."""

from typing import Protocol

from rolling_thunder.pota_receive_tune_executor import (
    PotaReceiveTuneResult,
    PotaReceiveTuneResultStatus,
)
from rolling_thunder.pota_tune_intent import (
    PotaTuneIntent,
    PotaTuneIntentStatus,
)


class PotaTuneIntentExecutor(Protocol):
    """Execute one immutable POTA tune intent."""

    def execute(self, intent: PotaTuneIntent) -> PotaReceiveTuneResult:
        """Attempt one receive-only tune operation."""
        ...


class PotaTuneExecutionController:
    """Prevent duplicate execution of one confirmed immutable intent."""

    def __init__(self, executor: PotaTuneIntentExecutor) -> None:
        self._executor = executor
        self._executed_intent: PotaTuneIntent | None = None
        self._result: PotaReceiveTuneResult | None = None

    @property
    def executed_intent(self) -> PotaTuneIntent | None:
        """Return the intent most recently submitted for execution."""
        return self._executed_intent

    @property
    def result(self) -> PotaReceiveTuneResult | None:
        """Return the latest immutable execution result."""
        return self._result

    def execute(
        self,
        intent: PotaTuneIntent | None,
    ) -> PotaReceiveTuneResult:
        """Execute confirmed intent once and reject duplicate submissions."""
        if intent is None:
            self._result = PotaReceiveTuneResult(
                status=PotaReceiveTuneResultStatus.REJECTED,
                error="No POTA tune intent is available for execution.",
            )
            return self._result

        if intent.status is not PotaTuneIntentStatus.CONFIRMED:
            self._result = PotaReceiveTuneResult(
                status=PotaReceiveTuneResultStatus.REJECTED,
                frequency=intent.frequency,
                mode=intent.mode,
                error="POTA tune intent must be confirmed before execution.",
            )
            return self._result

        if intent == self._executed_intent:
            self._result = PotaReceiveTuneResult(
                status=PotaReceiveTuneResultStatus.REJECTED,
                frequency=intent.frequency,
                mode=intent.mode,
                error="This POTA tune intent has already been executed.",
            )
            return self._result

        self._executed_intent = intent
        self._result = self._executor.execute(intent)
        return self._result

    def clear(self) -> None:
        """Clear retained intent and result when dashboard context changes."""
        self._executed_intent = None
        self._result = None
