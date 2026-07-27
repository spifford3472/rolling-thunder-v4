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
from rolling_thunder.pota_tune_intent import PotaTuneIntentStatus
from rolling_thunder.pota_tune_ui_controller import PotaTuneUiController

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
    def __init__(self) -> None:
        self.calls = []

    def execute(self, intent):
        self.calls.append(intent)
        return PotaReceiveTuneResult(
            status=PotaReceiveTuneResultStatus.SUCCEEDED,
            frequency=intent.frequency,
            mode=intent.mode,
        )


def build_controller(executor=None):
    dashboard = PotaDashboardController(
        FakeProvider(),
        clock=lambda: NOW,
    )
    dashboard.select_next()
    return dashboard, PotaTuneUiController(dashboard, executor)


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
    controller.request()
    controller.confirm()
    controller.execute()

    presentation = controller.presentation

    assert presentation.status_line == "RECEIVE TUNE SUCCEEDED"
    assert presentation.detail_line == "14.250 MHz USB"


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


def test_cancel_clears_execution_result() -> None:
    executor = FakeExecutor()
    _dashboard, controller = build_controller(executor)
    controller.request()
    controller.confirm()
    controller.execute()

    controller.cancel()

    assert controller.result is None
    assert controller.presentation.status_line == (
        "TUNE INTENT CANCELLED — NO RADIO CHANGE"
    )
