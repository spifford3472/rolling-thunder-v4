"""Tests for context-aware active-panel operator commands."""

from datetime import UTC, datetime

from rolling_thunder.active_panel_commands import ActivePanelCommandController
from rolling_thunder.context_navigation import ContextId, ContextNavigationController
from rolling_thunder.domain import Frequency, RadioMode
from rolling_thunder.pota_dashboard_controller import PotaDashboardController
from rolling_thunder.pota_dashboard_filters import PotaDashboardFilterController
from rolling_thunder.pota_receive_tune_executor import (
    PotaReceiveTuneResult,
    PotaReceiveTuneResultStatus,
)
from rolling_thunder.pota_spot_service import PotaSpotServiceState
from rolling_thunder.pota_spot_source import PotaSpotSourceAvailability
from rolling_thunder.pota_spots import ParkReference, PotaSpot
from rolling_thunder.pota_tune_intent import PotaTuneIntent, PotaTuneIntentStatus
from rolling_thunder.pota_tune_ui_controller import PotaTuneUiController
from rolling_thunder.radio import RadioBand
from rolling_thunder.status_messages import StatusMessageService


class StaticProvider:
    def __init__(self, state: PotaSpotServiceState) -> None:
        self.latest_pota_spot_state = state


class RecordingExecutor:
    def __init__(self) -> None:
        self.calls: list[PotaTuneIntent] = []

    def execute(self, intent: PotaTuneIntent) -> PotaReceiveTuneResult:
        self.calls.append(intent)
        raise AssertionError("Active-panel commands must never execute radio tuning.")


class BandChangeExecutor:
    def __init__(self) -> None:
        self.calls: list[PotaTuneIntent] = []

    def execute(self, intent: PotaTuneIntent) -> PotaReceiveTuneResult:
        self.calls.append(intent)
        return PotaReceiveTuneResult(
            status=PotaReceiveTuneResultStatus.SUCCEEDED,
            frequency=intent.frequency,
            mode=intent.mode,
            target_band=RadioBand.BAND_20M,
            band_changed=True,
        )


def spot(
    callsign: str,
    reference: str,
    frequency_hz: int,
    mode: RadioMode,
) -> PotaSpot:
    return PotaSpot(
        activator=callsign,
        park=ParkReference(reference=reference),
        frequency=Frequency(hz=frequency_hz),
        mode=mode,
        spotted_at=datetime(2026, 8, 1, 23, 0, tzinfo=UTC),
    )


def available_state() -> PotaSpotServiceState:
    return PotaSpotServiceState(
        availability=PotaSpotSourceAvailability.AVAILABLE,
        spots=(
            spot("KI5VNB", "US-1234", 14_250_000, RadioMode.USB),
            spot("W8ABC", "US-5678", 7_255_000, RadioMode.LSB),
        ),
        last_attempt_at=datetime(2026, 8, 1, 23, 0, tzinfo=UTC),
        last_success_at=datetime(2026, 8, 1, 23, 0, tzinfo=UTC),
    )


def controller(
    context: ContextId = ContextId.POTA,
) -> tuple[
    ActivePanelCommandController,
    ContextNavigationController,
    PotaDashboardController,
    PotaDashboardFilterController,
    RecordingExecutor,
]:
    navigation = ContextNavigationController(context)
    dashboard = PotaDashboardController(
        StaticProvider(available_state()),
        clock=lambda: datetime(2026, 8, 1, 23, 5, tzinfo=UTC),
    )
    filters = PotaDashboardFilterController(dashboard)
    filters.activate_for_frequency(Frequency(hz=14_250_000))
    executor = RecordingExecutor()
    tune = PotaTuneUiController(dashboard, executor)
    return (
        ActivePanelCommandController(
            navigation,
            dashboard,
            filters,
            tune,
        ),
        navigation,
        dashboard,
        filters,
        executor,
    )


def test_non_pota_context_rejects_panel_actions() -> None:
    commands, _navigation, dashboard, filters, executor = controller(ContextId.DX)
    initial_filter = filters.state

    assert commands.primary() is False
    assert commands.secondary() is False
    assert commands.tertiary() is False
    assert commands.tertiary_long() is False
    assert commands.move_previous() is False
    assert commands.move_next() is False
    assert commands.activate_selection() is False
    assert commands.back() is False
    assert filters.state.band_label == initial_filter.band_label
    assert filters.state.mode_label == initial_filter.mode_label
    assert dashboard.selected_index is None
    assert dashboard.tune_intent is None
    assert executor.calls == []


def test_primary_and_secondary_cycle_pota_filters() -> None:
    commands, _navigation, _dashboard, filters, _executor = controller()

    assert filters.state.band_label == "20"
    assert filters.state.mode_label == "SSB"

    assert commands.primary() is True
    assert filters.state.band_label == "17"

    assert commands.secondary() is True
    assert filters.state.mode_label == "CW"


def test_pota_tertiary_actions_are_unassigned() -> None:
    commands, _navigation, _dashboard, _filters, _executor = controller()

    assert commands.tertiary() is False
    assert commands.tertiary_long() is False


def test_encoder_rotation_moves_pota_selection_without_wrapping() -> None:
    commands, _navigation, dashboard, _filters, _executor = controller()

    assert commands.move_next() is True
    assert dashboard.selected_index == 0
    assert commands.move_next() is False
    assert dashboard.selected_index == 0

    assert commands.move_previous() is False
    assert dashboard.selected_index == 0


def test_activate_requires_an_explicit_pota_selection() -> None:
    commands, _navigation, dashboard, _filters, executor = controller()

    assert commands.activate_selection() is False
    assert dashboard.tune_intent is None
    assert executor.calls == []


def test_activate_stages_intent_without_confirming_or_executing() -> None:
    commands, _navigation, dashboard, _filters, executor = controller()
    commands.move_next()

    assert commands.activate_selection() is True

    intent = dashboard.tune_intent
    assert intent is not None
    assert intent.status is PotaTuneIntentStatus.PENDING_CONFIRMATION
    assert executor.calls == []


def test_encoder_short_advances_stage_confirm_execute_once() -> None:
    navigation = ContextNavigationController(ContextId.POTA)
    dashboard = PotaDashboardController(
        StaticProvider(available_state()),
        clock=lambda: datetime(2026, 8, 1, 23, 5, tzinfo=UTC),
    )
    filters = PotaDashboardFilterController(dashboard)
    filters.activate_for_frequency(Frequency(hz=14_250_000))
    dashboard.select_next()
    executor = BandChangeExecutor()
    status_messages = StatusMessageService(clock=lambda: 100.0)
    tune = PotaTuneUiController(
        dashboard,
        executor,
        status_messages=status_messages,
    )
    commands = ActivePanelCommandController(
        navigation,
        dashboard,
        filters,
        tune,
    )

    assert commands.activate_selection() is True
    assert dashboard.tune_intent is not None
    assert dashboard.tune_intent.status is PotaTuneIntentStatus.PENDING_CONFIRMATION
    assert executor.calls == []

    assert commands.activate_selection() is True
    assert dashboard.tune_intent is not None
    assert dashboard.tune_intent.status is PotaTuneIntentStatus.CONFIRMED
    assert executor.calls == []

    assert commands.activate_selection() is True
    assert len(executor.calls) == 1
    assert tune.result is not None
    assert tune.result.status is PotaReceiveTuneResultStatus.SUCCEEDED
    warning = status_messages.snapshot().current
    assert warning is not None
    assert warning.text == "SET BAND TO 20 METERS — TUNE ATAS-120"

    assert commands.activate_selection() is False
    assert len(executor.calls) == 1


def test_back_cancels_intent_before_clearing_selection() -> None:
    commands, _navigation, dashboard, _filters, executor = controller()
    commands.move_next()
    commands.activate_selection()

    assert commands.back() is True
    assert dashboard.selected_index == 0
    assert dashboard.tune_intent is not None
    assert dashboard.tune_intent.status is PotaTuneIntentStatus.CANCELLED

    assert commands.back() is True
    assert dashboard.selected_index is None
    assert dashboard.tune_intent is None

    assert commands.back() is False
    assert executor.calls == []


def test_back_outside_pota_does_not_clear_timed_warning_or_intent() -> None:
    navigation = ContextNavigationController(ContextId.POTA)
    dashboard = PotaDashboardController(
        StaticProvider(available_state()),
        clock=lambda: datetime(2026, 8, 1, 23, 5, tzinfo=UTC),
    )
    filters = PotaDashboardFilterController(dashboard)
    filters.activate_for_frequency(Frequency(hz=14_250_000))
    dashboard.select_next()
    status_messages = StatusMessageService(clock=lambda: 100.0)
    tune = PotaTuneUiController(
        dashboard,
        BandChangeExecutor(),
        status_messages=status_messages,
    )
    commands = ActivePanelCommandController(
        navigation,
        dashboard,
        filters,
        tune,
    )
    tune.request()
    tune.confirm()
    tune.execute()
    original_intent = dashboard.tune_intent
    original_warning = status_messages.snapshot().current
    navigation.select(ContextId.SETTINGS)

    assert original_warning is not None
    assert navigation.state.selected is ContextId.SETTINGS
    assert commands.back() is False
    assert status_messages.snapshot().current == original_warning
    assert dashboard.selected_index == 0
    assert dashboard.tune_intent is original_intent
    assert dashboard.tune_intent is not None
    assert dashboard.tune_intent.status is PotaTuneIntentStatus.CONFIRMED


def test_context_change_prevents_encoder_from_mutating_pota_state() -> None:
    commands, navigation, dashboard, _filters, _executor = controller()
    commands.move_next()
    commands.activate_selection()
    pending = dashboard.tune_intent

    navigation.select(ContextId.SETTINGS)

    assert commands.move_next() is False
    assert commands.back() is False
    assert dashboard.selected_index == 0
    assert dashboard.tune_intent is pending
