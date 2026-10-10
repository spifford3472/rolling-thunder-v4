"""Tests for confirmed POTA tuning through the ordered tuner."""

from datetime import UTC, datetime

from typing_extensions import get_protocol_members

from rolling_thunder.domain import (
    Frequency,
    RadioConnectionState,
    RadioMode,
    RadioState,
)
from rolling_thunder.pota_receive_tune_executor import (
    PotaReceiveTuneExecutor,
    PotaReceiveTuner,
    PotaReceiveTuneResultStatus,
)
from rolling_thunder.pota_tune_intent import (
    PotaTuneIntent,
    PotaTuneIntentStatus,
)
from rolling_thunder.radio import RadioBand, RadioError
from rolling_thunder.receive_tuning import ReceiveTuneOutcome


def intent(
    status: PotaTuneIntentStatus = PotaTuneIntentStatus.CONFIRMED,
) -> PotaTuneIntent:
    return PotaTuneIntent(
        status=status,
        activator="KI5VNB",
        park_reference="US-1234",
        frequency=Frequency(hz=7_255_000),
        mode=RadioMode.LSB,
        created_at=datetime(2026, 8, 2, 18, 0, tzinfo=UTC),
    )


def outcome() -> ReceiveTuneOutcome:
    return ReceiveTuneOutcome(
        state=RadioState(
            connection_state=RadioConnectionState.CONNECTED,
            frequency=Frequency(hz=7_255_000),
            mode=RadioMode.LSB,
            transmitting=False,
            updated_at=datetime(2026, 8, 2, 18, 0, tzinfo=UTC),
        ),
        target_band=RadioBand.BAND_40M,
        band_changed=True,
    )


class FakeReceiveTuner:
    def __init__(self, *, error: RadioError | None = None) -> None:
        self.error = error
        self.calls: list[tuple[Frequency, RadioMode]] = []

    def tune(
        self,
        frequency: Frequency,
        mode: RadioMode,
    ) -> ReceiveTuneOutcome:
        self.calls.append((frequency, mode))
        if self.error is not None:
            raise self.error
        return outcome()


def test_pota_boundary_exposes_only_ordered_tune_operation() -> None:
    assert get_protocol_members(PotaReceiveTuner) == {"tune"}


def test_executor_rejects_pending_intent_without_tuning() -> None:
    tuner = FakeReceiveTuner()
    executor = PotaReceiveTuneExecutor(tuner)

    result = executor.execute(
        intent(PotaTuneIntentStatus.PENDING_CONFIRMATION)
    )

    assert result.status is PotaReceiveTuneResultStatus.REJECTED
    assert tuner.calls == []


def test_executor_rejects_cancelled_intent_without_tuning() -> None:
    tuner = FakeReceiveTuner()
    executor = PotaReceiveTuneExecutor(tuner)

    result = executor.execute(intent(PotaTuneIntentStatus.CANCELLED))

    assert result.status is PotaReceiveTuneResultStatus.REJECTED
    assert tuner.calls == []


def test_executor_routes_confirmed_intent_through_ordered_tuner() -> None:
    tuner = FakeReceiveTuner()
    executor = PotaReceiveTuneExecutor(tuner)

    result = executor.execute(intent())

    assert tuner.calls == [
        (Frequency(hz=7_255_000), RadioMode.LSB),
    ]
    assert result.status is PotaReceiveTuneResultStatus.SUCCEEDED
    assert result.frequency == Frequency(hz=7_255_000)
    assert result.mode is RadioMode.LSB
    assert result.target_band is RadioBand.BAND_40M
    assert result.band_changed is True


def test_ordered_tuning_failure_is_reported_without_retry() -> None:
    tuner = FakeReceiveTuner(
        error=RadioError("band verification failed"),
    )
    executor = PotaReceiveTuneExecutor(tuner)

    result = executor.execute(intent())

    assert result.status is PotaReceiveTuneResultStatus.FAILED
    assert result.error == (
        "Unable to complete ordered receive tune: "
        "band verification failed"
    )
    assert tuner.calls == [
        (Frequency(hz=7_255_000), RadioMode.LSB),
    ]
