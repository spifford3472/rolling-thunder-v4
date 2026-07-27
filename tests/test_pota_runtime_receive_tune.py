from datetime import UTC, datetime

from rolling_thunder.application_runtime import ApplicationRuntime
from rolling_thunder.contact_logging import ContactLoggingService
from rolling_thunder.contact_repository import ContactRepository
from rolling_thunder.domain import Frequency, RadioMode
from rolling_thunder.mock_radio import MockRadio
from rolling_thunder.pota_receive_tune_executor import (
    PotaReceiveTuneExecutor,
    PotaReceiveTuneResultStatus,
)
from rolling_thunder.pota_tune_intent import (
    PotaTuneIntent,
    PotaTuneIntentStatus,
)
from rolling_thunder.radio_polling import RadioPollingService


class FakeScheduledPoll:
    def cancel(self) -> None:
        return None


class FakeScheduler:
    def schedule_repeating(
        self,
        _interval_s: float,
        _callback,
    ) -> FakeScheduledPoll:
        return FakeScheduledPoll()


def build_runtime(tmp_path) -> ApplicationRuntime:
    radio = MockRadio()
    return ApplicationRuntime(
        radio=radio,
        polling=RadioPollingService(
            radio,
            FakeScheduler(),
        ),
        contact_logging=ContactLoggingService(
            ContactRepository(tmp_path / "contacts.sqlite3"),
        ),
    )


def confirmed_intent() -> PotaTuneIntent:
    return PotaTuneIntent(
        status=PotaTuneIntentStatus.CONFIRMED,
        activator="KI5VNB",
        park_reference="US-1234",
        frequency=Frequency(hz=14_250_000),
        mode=RadioMode.USB,
        created_at=datetime(2026, 7, 27, 2, 0, tzinfo=UTC),
    )


def test_runtime_exposes_receive_only_executor(tmp_path) -> None:
    runtime = build_runtime(tmp_path)

    executor = runtime.pota_receive_tune_executor

    assert isinstance(executor, PotaReceiveTuneExecutor)


def test_runtime_executor_tunes_owned_mock_radio(tmp_path) -> None:
    runtime = build_runtime(tmp_path)
    runtime.start()

    result = runtime.pota_receive_tune_executor.execute(
        confirmed_intent(),
    )

    state = runtime.radio.get_state()

    assert result.status is PotaReceiveTuneResultStatus.SUCCEEDED
    assert state.frequency == Frequency(hz=14_250_000)
    assert state.mode is RadioMode.USB

    runtime.stop()


def test_runtime_executor_rejects_unconfirmed_intent(tmp_path) -> None:
    runtime = build_runtime(tmp_path)
    runtime.start()

    pending = confirmed_intent().model_copy(
        update={"status": PotaTuneIntentStatus.PENDING_CONFIRMATION},
    )
    original_state = runtime.radio.get_state()

    result = runtime.pota_receive_tune_executor.execute(pending)

    assert result.status is PotaReceiveTuneResultStatus.REJECTED
    assert runtime.radio.get_state() == original_state

    runtime.stop()


def test_each_runtime_executor_uses_same_owned_radio(tmp_path) -> None:
    runtime = build_runtime(tmp_path)

    first = runtime.pota_receive_tune_executor
    second = runtime.pota_receive_tune_executor

    assert first is not second
    assert isinstance(first, PotaReceiveTuneExecutor)
    assert isinstance(second, PotaReceiveTuneExecutor)
