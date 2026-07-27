from datetime import UTC, datetime

from rolling_thunder.domain import Frequency, RadioMode
from rolling_thunder.pota_receive_tune_executor import (
    PotaReceiveTuneResult,
    PotaReceiveTuneResultStatus,
)
from rolling_thunder.pota_tune_execution_controller import (
    PotaTuneExecutionController,
)
from rolling_thunder.pota_tune_intent import (
    PotaTuneIntent,
    PotaTuneIntentStatus,
)


def tune_intent(
    *,
    status: PotaTuneIntentStatus = PotaTuneIntentStatus.CONFIRMED,
    frequency_hz: int = 14_250_000,
) -> PotaTuneIntent:
    return PotaTuneIntent(
        status=status,
        activator="KI5VNB",
        park_reference="US-1234",
        frequency=Frequency(hz=frequency_hz),
        mode=RadioMode.USB,
        created_at=datetime(2026, 7, 27, 1, 0, tzinfo=UTC),
    )


class FakeIntentExecutor:
    def __init__(
        self,
        result_status: PotaReceiveTuneResultStatus = (
            PotaReceiveTuneResultStatus.SUCCEEDED
        ),
    ) -> None:
        self.result_status = result_status
        self.calls: list[PotaTuneIntent] = []

    def execute(self, intent: PotaTuneIntent) -> PotaReceiveTuneResult:
        self.calls.append(intent)
        return PotaReceiveTuneResult(
            status=self.result_status,
            frequency=intent.frequency,
            mode=intent.mode,
            error=(
                None
                if self.result_status
                is PotaReceiveTuneResultStatus.SUCCEEDED
                else "simulated failure"
            ),
        )


def test_execute_requires_an_intent() -> None:
    executor = FakeIntentExecutor()
    controller = PotaTuneExecutionController(executor)

    result = controller.execute(None)

    assert result.status is PotaReceiveTuneResultStatus.REJECTED
    assert result.error == "No POTA tune intent is available for execution."
    assert executor.calls == []


def test_execute_rejects_pending_intent_without_executor_call() -> None:
    executor = FakeIntentExecutor()
    controller = PotaTuneExecutionController(executor)
    pending = tune_intent(
        status=PotaTuneIntentStatus.PENDING_CONFIRMATION,
    )

    result = controller.execute(pending)

    assert result.status is PotaReceiveTuneResultStatus.REJECTED
    assert executor.calls == []


def test_execute_rejects_cancelled_intent_without_executor_call() -> None:
    executor = FakeIntentExecutor()
    controller = PotaTuneExecutionController(executor)
    cancelled = tune_intent(
        status=PotaTuneIntentStatus.CANCELLED,
    )

    result = controller.execute(cancelled)

    assert result.status is PotaReceiveTuneResultStatus.REJECTED
    assert executor.calls == []


def test_execute_submits_confirmed_intent_once() -> None:
    executor = FakeIntentExecutor()
    controller = PotaTuneExecutionController(executor)
    confirmed = tune_intent()

    result = controller.execute(confirmed)

    assert result.status is PotaReceiveTuneResultStatus.SUCCEEDED
    assert controller.executed_intent == confirmed
    assert controller.result == result
    assert executor.calls == [confirmed]


def test_repeated_execution_of_same_intent_is_rejected() -> None:
    executor = FakeIntentExecutor()
    controller = PotaTuneExecutionController(executor)
    confirmed = tune_intent()

    first = controller.execute(confirmed)
    repeated = controller.execute(confirmed)

    assert first.status is PotaReceiveTuneResultStatus.SUCCEEDED
    assert repeated.status is PotaReceiveTuneResultStatus.REJECTED
    assert repeated.error == (
        "This POTA tune intent has already been executed."
    )
    assert executor.calls == [confirmed]


def test_failed_execution_is_still_consumed_once() -> None:
    executor = FakeIntentExecutor(
        PotaReceiveTuneResultStatus.FAILED,
    )
    controller = PotaTuneExecutionController(executor)
    confirmed = tune_intent()

    first = controller.execute(confirmed)
    repeated = controller.execute(confirmed)

    assert first.status is PotaReceiveTuneResultStatus.FAILED
    assert repeated.status is PotaReceiveTuneResultStatus.REJECTED
    assert executor.calls == [confirmed]


def test_distinct_confirmed_intent_can_execute_after_previous_intent() -> None:
    executor = FakeIntentExecutor()
    controller = PotaTuneExecutionController(executor)
    first_intent = tune_intent()
    second_intent = tune_intent(frequency_hz=14_300_000)

    first_result = controller.execute(first_intent)
    second_result = controller.execute(second_intent)

    assert first_result.status is PotaReceiveTuneResultStatus.SUCCEEDED
    assert second_result.status is PotaReceiveTuneResultStatus.SUCCEEDED
    assert executor.calls == [first_intent, second_intent]


def test_clear_allows_same_intent_to_be_submitted_again() -> None:
    executor = FakeIntentExecutor()
    controller = PotaTuneExecutionController(executor)
    confirmed = tune_intent()

    controller.execute(confirmed)
    controller.clear()
    repeated = controller.execute(confirmed)

    assert repeated.status is PotaReceiveTuneResultStatus.SUCCEEDED
    assert executor.calls == [confirmed, confirmed]


def test_clear_removes_retained_execution_state() -> None:
    executor = FakeIntentExecutor()
    controller = PotaTuneExecutionController(executor)
    controller.execute(tune_intent())

    controller.clear()

    assert controller.executed_intent is None
    assert controller.result is None
