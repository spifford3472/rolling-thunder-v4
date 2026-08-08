"""Tests for shared-spot receive-tune operator status presentation."""

from datetime import UTC, datetime

from rolling_thunder.domain import (
    Frequency,
    RadioConnectionState,
    RadioMode,
    RadioState,
)
from rolling_thunder.radio import RadioBand
from rolling_thunder.receive_tuning import ReceiveTuneOutcome
from rolling_thunder.shared_spot_tune_status import (
    ATAS_RETUNE_STATUS_KEY,
    SHARED_TUNE_STATUS_KEY,
    SharedSpotTuneStatusController,
)
from rolling_thunder.shared_spot_tuning import (
    SharedSpotTuneState,
    SharedSpotTuneStatus,
)
from rolling_thunder.spot_domain import DxSpotIdentity
from rolling_thunder.spot_selection import StagedSpotAction
from rolling_thunder.status_messages import (
    StatusMessageService,
    StatusPresentation,
)


class FakeTuneStatusProvider:
    """Mutable no-I/O provider for deterministic presentation tests."""

    def __init__(self, status: SharedSpotTuneStatus) -> None:
        self.current = status
        self.clear_count = 0

    @property
    def status(self) -> SharedSpotTuneStatus:
        return self.current

    def clear_result(self) -> None:
        self.clear_count += 1
        self.current = SharedSpotTuneStatus()


def action() -> StagedSpotAction:
    frequency = Frequency(hz=14_025_000)
    return StagedSpotAction(
        identity=DxSpotIdentity(
            callsign="K1DX",
            frequency=frequency,
        ),
        callsign="K1DX",
        frequency=frequency,
        mode=RadioMode.CW,
    )


def outcome(
    *,
    target_band: RadioBand = RadioBand.BAND_20M,
    band_changed: bool = False,
) -> ReceiveTuneOutcome:
    return ReceiveTuneOutcome(
        state=RadioState(
            connection_state=RadioConnectionState.CONNECTED,
            frequency=Frequency(hz=14_025_000),
            mode=RadioMode.CW,
            updated_at=datetime(2026, 8, 8, 3, 45, tzinfo=UTC),
        ),
        target_band=target_band,
        band_changed=band_changed,
    )


def test_tuning_transition_publishes_normal_operator_status_once() -> None:
    staged = action()
    provider = FakeTuneStatusProvider(
        SharedSpotTuneStatus(
            state=SharedSpotTuneState.TUNING,
            action=staged,
        )
    )
    messages = StatusMessageService()
    controller = SharedSpotTuneStatusController(provider, messages)

    assert controller.refresh() is True
    first = messages.snapshot().current

    assert first is not None
    assert first.replacement_key == SHARED_TUNE_STATUS_KEY
    assert first.text == "TUNING K1DX — 14.025 MHz CW"
    assert first.presentation is StatusPresentation.NORMAL

    assert controller.refresh() is False
    assert messages.snapshot().current == first


def test_success_publishes_tuned_status_and_clears_completed_result() -> None:
    staged = action()
    provider = FakeTuneStatusProvider(
        SharedSpotTuneStatus(
            state=SharedSpotTuneState.SUCCEEDED,
            action=staged,
            outcome=outcome(),
        )
    )
    messages = StatusMessageService()
    controller = SharedSpotTuneStatusController(provider, messages)

    assert controller.refresh() is True

    current = messages.snapshot().current
    assert current is not None
    assert current.replacement_key == SHARED_TUNE_STATUS_KEY
    assert current.text == "TUNED K1DX — 14.025 MHz CW"
    assert current.presentation is StatusPresentation.SUCCESS
    assert provider.clear_count == 1
    assert provider.status.state is SharedSpotTuneState.IDLE


def test_cross_band_success_publishes_higher_priority_atas_warning() -> None:
    staged = action()
    provider = FakeTuneStatusProvider(
        SharedSpotTuneStatus(
            state=SharedSpotTuneState.SUCCEEDED,
            action=staged,
            outcome=outcome(
                target_band=RadioBand.BAND_40M,
                band_changed=True,
            ),
        )
    )
    messages = StatusMessageService()
    controller = SharedSpotTuneStatusController(provider, messages)

    assert controller.refresh() is True

    current = messages.snapshot().current
    assert current is not None
    assert current.replacement_key == ATAS_RETUNE_STATUS_KEY
    assert current.text == "BAND CHANGED TO 40 METERS — RETUNE ATAS-120"
    assert current.presentation is StatusPresentation.AMBER
    assert provider.clear_count == 1


def test_failure_publishes_error_and_clears_completed_result() -> None:
    staged = action()
    provider = FakeTuneStatusProvider(
        SharedSpotTuneStatus(
            state=SharedSpotTuneState.FAILED,
            action=staged,
            error="radio unavailable",
        )
    )
    messages = StatusMessageService()
    controller = SharedSpotTuneStatusController(provider, messages)

    assert controller.refresh() is True

    current = messages.snapshot().current
    assert current is not None
    assert current.replacement_key == SHARED_TUNE_STATUS_KEY
    assert current.text == "TUNE FAILED — radio unavailable"
    assert current.presentation is StatusPresentation.ERROR
    assert provider.clear_count == 1
