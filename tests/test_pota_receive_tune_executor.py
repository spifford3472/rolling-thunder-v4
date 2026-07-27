from datetime import UTC, datetime
from typing import get_protocol_members

from rolling_thunder.domain import (
    Frequency,
    RadioConnectionState,
    RadioMode,
    RadioState,
)
from rolling_thunder.pota_receive_tune_executor import (
    PotaReceiveTuneExecutor,
    PotaReceiveTuneRadio,
    PotaReceiveTuneResultStatus,
)
from rolling_thunder.pota_tune_intent import (
    PotaTuneIntent,
    PotaTuneIntentStatus,
)
from rolling_thunder.radio import RadioError


def intent(
    status: PotaTuneIntentStatus = PotaTuneIntentStatus.CONFIRMED,
) -> PotaTuneIntent:
    return PotaTuneIntent(
        status=status,
        activator="KI5VNB",
        park_reference="US-1234",
        frequency=Frequency(hz=14_250_000),
        mode=RadioMode.USB,
        created_at=datetime(2026, 7, 27, 1, 0, tzinfo=UTC),
    )


def radio_state(
    *,
    frequency: Frequency | None = None,
    mode: RadioMode | None = None,
) -> RadioState:
    return RadioState(
        connection_state=RadioConnectionState.CONNECTED,
        frequency=frequency or Frequency(hz=14_250_000),
        mode=mode or RadioMode.USB,
        updated_at=datetime(2026, 7, 27, 1, 0, tzinfo=UTC),
    )


class FakeReceiveTuneRadio:
    def __init__(
        self,
        *,
        frequency_error: RadioError | None = None,
        mode_error: RadioError | None = None,
    ) -> None:
        self.frequency_error = frequency_error
        self.mode_error = mode_error
        self.calls: list[tuple[str, object]] = []

    def set_frequency(self, frequency: Frequency) -> RadioState:
        self.calls.append(("set_frequency", frequency))
        if self.frequency_error is not None:
            raise self.frequency_error
        return radio_state(frequency=frequency)

    def set_mode(self, mode: RadioMode) -> RadioState:
        self.calls.append(("set_mode", mode))
        if self.mode_error is not None:
            raise self.mode_error
        return radio_state(mode=mode)


def test_receive_tune_boundary_exposes_only_frequency_and_mode() -> None:
    assert get_protocol_members(PotaReceiveTuneRadio) == {
        "set_frequency",
        "set_mode",
    }


def test_executor_rejects_pending_intent_without_radio_calls() -> None:
    radio = FakeReceiveTuneRadio()
    executor = PotaReceiveTuneExecutor(radio)

    result = executor.execute(
        intent(PotaTuneIntentStatus.PENDING_CONFIRMATION)
    )

    assert result.status is PotaReceiveTuneResultStatus.REJECTED
    assert radio.calls == []


def test_executor_rejects_cancelled_intent_without_radio_calls() -> None:
    radio = FakeReceiveTuneRadio()
    executor = PotaReceiveTuneExecutor(radio)

    result = executor.execute(intent(PotaTuneIntentStatus.CANCELLED))

    assert result.status is PotaReceiveTuneResultStatus.REJECTED
    assert radio.calls == []


def test_executor_sets_frequency_then_mode() -> None:
    radio = FakeReceiveTuneRadio()
    executor = PotaReceiveTuneExecutor(radio)

    result = executor.execute(intent())

    assert result.status is PotaReceiveTuneResultStatus.SUCCEEDED
    assert result.frequency == Frequency(hz=14_250_000)
    assert result.mode is RadioMode.USB
    assert radio.calls == [
        ("set_frequency", Frequency(hz=14_250_000)),
        ("set_mode", RadioMode.USB),
    ]


def test_frequency_failure_prevents_mode_change() -> None:
    radio = FakeReceiveTuneRadio(
        frequency_error=RadioError("frequency rejected"),
    )
    executor = PotaReceiveTuneExecutor(radio)

    result = executor.execute(intent())

    assert result.status is PotaReceiveTuneResultStatus.FAILED
    assert result.error == (
        "Unable to set receive frequency: frequency rejected"
    )
    assert radio.calls == [
        ("set_frequency", Frequency(hz=14_250_000)),
    ]


def test_mode_failure_reports_partial_receive_tune() -> None:
    radio = FakeReceiveTuneRadio(
        mode_error=RadioError("mode rejected"),
    )
    executor = PotaReceiveTuneExecutor(radio)

    result = executor.execute(intent())

    assert result.status is PotaReceiveTuneResultStatus.FAILED
    assert result.frequency == Frequency(hz=14_250_000)
    assert result.mode is RadioMode.USB
    assert result.error == (
        "Receive frequency set, but mode change failed: mode rejected"
    )
    assert radio.calls == [
        ("set_frequency", Frequency(hz=14_250_000)),
        ("set_mode", RadioMode.USB),
    ]
