from datetime import UTC, datetime

from rolling_thunder.domain import Frequency, RadioMode
from rolling_thunder.pota_dashboard_controller import PotaDashboardController
from rolling_thunder.pota_receive_tune_executor import (
    PotaReceiveTuneResult,
    PotaReceiveTuneResultStatus,
)
from rolling_thunder.pota_spot_service import PotaSpotServiceState
from rolling_thunder.pota_spot_source import PotaSpotSourceAvailability
from rolling_thunder.pota_spots import ParkReference, PotaSpot
from rolling_thunder.pota_tune_intent import (
    PotaTuneIntent,
    PotaTuneIntentStatus,
)
from rolling_thunder.pota_tune_ui_controller import (
    ATAS_RETUNE_STATUS_DURATION_S,
    ATAS_RETUNE_STATUS_KEY,
    ATAS_RETUNE_STATUS_PRIORITY,
    PotaTuneUiController,
)
from rolling_thunder.radio import RadioBand
from rolling_thunder.status_messages import (
    StatusMessageService,
    StatusPresentation,
)

NOW = datetime(2026, 7, 27, 1, 0, tzinfo=UTC)


class FakeMonotonicClock:
    def __init__(self, value: float = 100.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class FakeProvider:
    def __init__(self) -> None:
        self.latest_pota_spot_state = PotaSpotServiceState(
            availability=PotaSpotSourceAvailability.AVAILABLE,
            spots=(
                PotaSpot(
                    activator="KI5VNB",
                    park=ParkReference(
                        reference="US-1234",
                        name="Test Park",
                    ),
                    frequency=Frequency(hz=14_250_000),
                    mode=RadioMode.USB,
                    spotted_at=NOW,
                    comments="test spot",
                ),
            ),
            last_attempt_at=NOW,
            last_success_at=NOW,
        )


class FakeExecutor:
    def __init__(
        self,
        outcomes: list[tuple[bool, RadioBand | None]] | None = None,
    ) -> None:
        self.calls: list[PotaTuneIntent] = []
        self._outcomes = outcomes or [(False, None)]

    def execute(self, intent: PotaTuneIntent) -> PotaReceiveTuneResult:
        self.calls.append(intent)
        outcome_index = min(len(self.calls) - 1, len(self._outcomes) - 1)
        band_changed, target_band = self._outcomes[outcome_index]
        return PotaReceiveTuneResult(
            status=PotaReceiveTuneResultStatus.SUCCEEDED,
            frequency=intent.frequency,
            mode=intent.mode,
            target_band=target_band,
            band_changed=band_changed,
        )


def build_controller(
    executor=None,
    status_messages: StatusMessageService | None = None,
):
    dashboard = PotaDashboardController(
        FakeProvider(),
        clock=lambda: NOW,
    )
    dashboard.select_next()
    return dashboard, PotaTuneUiController(
        dashboard,
        executor,
        status_messages=status_messages,
    )


def execute_confirmed(controller: PotaTuneUiController) -> PotaReceiveTuneResult:
    controller.request()
    controller.confirm()
    return controller.execute()


def test_stage_confirm_execute_requires_three_explicit_actions() -> None:
    executor = FakeExecutor()
    _dashboard, controller = build_controller(executor)

    staged = controller.request()

    assert staged is not None
    assert staged.status is PotaTuneIntentStatus.PENDING_CONFIRMATION
    assert executor.calls == []

    confirmed = controller.confirm()

    assert confirmed is not None
    assert confirmed.status is PotaTuneIntentStatus.CONFIRMED
    assert executor.calls == []

    result = controller.execute()

    assert result.status is PotaReceiveTuneResultStatus.SUCCEEDED
    assert executor.calls == [confirmed]


def test_execute_before_confirmation_does_not_call_executor() -> None:
    executor = FakeExecutor()
    _dashboard, controller = build_controller(executor)
    controller.request()

    result = controller.execute()

    assert result.status is PotaReceiveTuneResultStatus.REJECTED
    assert executor.calls == []


def test_repeated_execute_does_not_retune_same_intent() -> None:
    executor = FakeExecutor()
    _dashboard, controller = build_controller(executor)
    controller.request()
    controller.confirm()

    first = controller.execute()
    repeated = controller.execute()

    assert first.status is PotaReceiveTuneResultStatus.SUCCEEDED
    assert repeated.status is PotaReceiveTuneResultStatus.REJECTED
    assert len(executor.calls) == 1


def test_default_executor_rejects_without_radio_access() -> None:
    _dashboard, controller = build_controller()
    controller.request()
    controller.confirm()

    result = controller.execute()

    assert result.status is PotaReceiveTuneResultStatus.REJECTED
    assert result.error == "Receive tuning is unavailable in this runtime."


def test_success_result_is_available_to_presentation() -> None:
    executor = FakeExecutor()
    _dashboard, controller = build_controller(executor)
    execute_confirmed(controller)

    presentation = controller.presentation

    assert presentation.status_line == "RECEIVE TUNE SUCCEEDED"
    assert presentation.detail_line == "14.250 MHz USB"


def test_verified_band_change_publishes_amber_warning_for_ten_seconds() -> None:
    clock = FakeMonotonicClock()
    status_messages = StatusMessageService(clock=clock)
    executor = FakeExecutor([(True, RadioBand.BAND_40M)])
    _dashboard, controller = build_controller(executor, status_messages)

    execute_confirmed(controller)

    warning = status_messages.snapshot().current
    assert warning is not None
    assert warning.replacement_key == ATAS_RETUNE_STATUS_KEY
    assert warning.text == "BAND CHANGED TO 40 METERS — RETUNE ATAS-120"
    assert warning.presentation is StatusPresentation.AMBER
    assert warning.priority == ATAS_RETUNE_STATUS_PRIORITY
    assert warning.expires_at_monotonic == (100.0 + ATAS_RETUNE_STATUS_DURATION_S)
    assert controller.presentation.detail_line == "14.250 MHz USB"

    clock.advance(9.999)
    assert status_messages.snapshot().current == warning
    clock.advance(0.001)
    assert status_messages.snapshot().current is None


def test_same_band_tune_publishes_no_atas_warning() -> None:
    status_messages = StatusMessageService(clock=lambda: 100.0)
    executor = FakeExecutor([(False, RadioBand.BAND_20M)])
    _dashboard, controller = build_controller(executor, status_messages)

    execute_confirmed(controller)

    assert status_messages.snapshot().current is None


def test_warning_survives_selection_and_result_cleanup_until_expiration() -> None:
    status_messages = StatusMessageService(clock=lambda: 100.0)
    executor = FakeExecutor([(True, RadioBand.BAND_40M)])
    dashboard, controller = build_controller(executor, status_messages)
    execute_confirmed(controller)
    warning = status_messages.snapshot().current

    dashboard.clear_selection()

    assert controller.result is None
    assert warning is not None
    assert status_messages.snapshot().current == warning
    assert controller.presentation.summary_line is None
    assert controller.presentation.detail_line is None


def test_later_same_band_tune_does_not_replace_existing_warning() -> None:
    status_messages = StatusMessageService(clock=lambda: 100.0)
    executor = FakeExecutor(
        [
            (True, RadioBand.BAND_40M),
            (False, RadioBand.BAND_40M),
        ]
    )
    _dashboard, controller = build_controller(executor, status_messages)

    execute_confirmed(controller)
    original_warning = status_messages.snapshot().current
    execute_confirmed(controller)

    assert original_warning is not None
    assert status_messages.snapshot().current == original_warning


def test_later_band_change_replaces_warning_and_restarts_duration() -> None:
    clock = FakeMonotonicClock()
    status_messages = StatusMessageService(clock=clock)
    executor = FakeExecutor(
        [
            (True, RadioBand.BAND_40M),
            (True, RadioBand.BAND_20M),
        ]
    )
    _dashboard, controller = build_controller(executor, status_messages)

    execute_confirmed(controller)
    first_warning = status_messages.snapshot().current
    clock.advance(3.0)
    execute_confirmed(controller)
    replacement = status_messages.snapshot().current

    assert first_warning is not None
    assert replacement is not None
    assert replacement.sequence > first_warning.sequence
    assert replacement.text == "BAND CHANGED TO 20 METERS — RETUNE ATAS-120"
    assert replacement.expires_at_monotonic == 113.0


def test_selection_change_clears_stale_execution_result() -> None:
    executor = FakeExecutor()
    dashboard, controller = build_controller(executor)
    controller.request()
    controller.confirm()
    controller.execute()

    dashboard.clear_selection()

    presentation = controller.presentation

    assert controller.result is None
    assert presentation.summary_line is None


def test_new_staged_intent_clears_previous_result() -> None:
    executor = FakeExecutor()
    _dashboard, controller = build_controller(executor)
    controller.request()
    controller.confirm()
    controller.execute()

    controller.request()

    assert controller.result is None
    assert controller.presentation.status_line == ("PRESS ENTER TO CONFIRM — NO RADIO CHANGE")


def test_cancel_clears_result_without_clearing_timed_warning() -> None:
    status_messages = StatusMessageService(clock=lambda: 100.0)
    executor = FakeExecutor([(True, RadioBand.BAND_40M)])
    _dashboard, controller = build_controller(executor, status_messages)
    controller.request()
    controller.confirm()
    controller.execute()
    warning = status_messages.snapshot().current

    controller.cancel()

    assert controller.result is None
    assert warning is not None
    assert status_messages.snapshot().current == warning
    assert controller.presentation.status_line == ("TUNE INTENT CANCELLED — NO RADIO CHANGE")
