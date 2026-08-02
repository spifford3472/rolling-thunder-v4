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
from rolling_thunder.pota_tune_ui_controller import PotaTuneUiController
from rolling_thunder.radio import RadioBand

NOW = datetime(2026, 7, 27, 1, 0, tzinfo=UTC)


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


def build_controller(executor=None):
    dashboard = PotaDashboardController(
        FakeProvider(),
        clock=lambda: NOW,
    )
    dashboard.select_next()
    return dashboard, PotaTuneUiController(dashboard, executor)


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


def test_verified_band_change_publishes_exact_atas_warning() -> None:
    executor = FakeExecutor([(True, RadioBand.BAND_40M)])
    _dashboard, controller = build_controller(executor)

    execute_confirmed(controller)

    assert controller.retune_warning_active is True
    assert controller.retune_warning_line == (
        "BAND CHANGED TO 40 METERS — RETUNE ATAS-120"
    )
    assert controller.presentation.detail_line == "14.250 MHz USB"


def test_same_band_tune_publishes_no_atas_warning() -> None:
    executor = FakeExecutor([(False, RadioBand.BAND_20M)])
    _dashboard, controller = build_controller(executor)

    execute_confirmed(controller)

    assert controller.retune_warning_active is False
    assert controller.retune_warning_line is None


def test_warning_survives_selection_and_result_cleanup() -> None:
    executor = FakeExecutor([(True, RadioBand.BAND_40M)])
    dashboard, controller = build_controller(executor)
    execute_confirmed(controller)

    dashboard.clear_selection()

    assert controller.result is None
    assert controller.retune_warning_active is True
    assert controller.retune_warning_line == (
        "BAND CHANGED TO 40 METERS — RETUNE ATAS-120"
    )
    assert controller.presentation.summary_line is None
    assert controller.presentation.detail_line is None


def test_later_same_band_tune_does_not_clear_existing_warning() -> None:
    executor = FakeExecutor(
        [
            (True, RadioBand.BAND_40M),
            (False, RadioBand.BAND_40M),
        ]
    )
    _dashboard, controller = build_controller(executor)

    execute_confirmed(controller)
    execute_confirmed(controller)

    assert controller.retune_warning_line == (
        "BAND CHANGED TO 40 METERS — RETUNE ATAS-120"
    )


def test_later_band_change_replaces_warning_band() -> None:
    executor = FakeExecutor(
        [
            (True, RadioBand.BAND_40M),
            (True, RadioBand.BAND_20M),
        ]
    )
    _dashboard, controller = build_controller(executor)

    execute_confirmed(controller)
    execute_confirmed(controller)

    assert controller.retune_warning_line == (
        "BAND CHANGED TO 20 METERS — RETUNE ATAS-120"
    )


def test_explicit_acknowledgement_clears_warning() -> None:
    executor = FakeExecutor([(True, RadioBand.BAND_40M)])
    _dashboard, controller = build_controller(executor)
    execute_confirmed(controller)

    assert controller.acknowledge_retune_warning() is True
    assert controller.retune_warning_active is False
    assert controller.retune_warning_line is None
    assert controller.acknowledge_retune_warning() is False


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
    assert controller.presentation.status_line == (
        "PRESS ENTER TO CONFIRM — NO RADIO CHANGE"
    )


def test_cancel_clears_execution_result_and_warning() -> None:
    executor = FakeExecutor([(True, RadioBand.BAND_40M)])
    _dashboard, controller = build_controller(executor)
    controller.request()
    controller.confirm()
    controller.execute()

    controller.cancel()

    assert controller.result is None
    assert controller.retune_warning_active is False
    assert controller.presentation.status_line == (
        "TUNE INTENT CANCELLED — NO RADIO CHANGE"
    )
