"""Tests for REPEATERS context command routing and Active controls."""

from decimal import Decimal

from rolling_thunder.active_panel_commands import SharedSpotActivePanelCommandController
from rolling_thunder.context_navigation import ContextId, ContextNavigationController
from rolling_thunder.domain import Frequency, RadioState
from rolling_thunder.repeater_configuration import StagedRepeaterRadioAction
from rolling_thunder.repeater_domain import (
    RepeaterChannelType,
    RepeaterIdentity,
    RepeaterLocation,
    RepeaterRecord,
)
from rolling_thunder.repeater_nearby import NearbyRepeater
from rolling_thunder.repeater_panel import StagedRepeaterActiveAction
from rolling_thunder.spot_domain import SpotIdentity, SpotProvider
from rolling_thunder.spot_selection import StagedSpotAction


class InertSharedPanel:
    """Minimal shared-spot fake proving repeater controls do not tune."""

    def __init__(self) -> None:
        self.provider = SpotProvider.POTA
        self.selected_identity: SpotIdentity | None = None
        self.staged_identity: SpotIdentity | None = None
        self.staged_action: StagedSpotAction | None = None
        self.calls: list[str] = []

    def activate(
        self,
        provider: SpotProvider,
        *,
        current_frequency: Frequency | None = None,
    ) -> object:
        del current_frequency
        self.provider = provider
        self.calls.append(f"activate:{provider.value}")
        return object()

    def select_previous(self) -> object:
        self.calls.append("select_previous")
        return object()

    def select_next(self) -> object:
        self.calls.append("select_next")
        return object()

    def clear_selection(self) -> object:
        self.calls.append("clear_selection")
        return object()

    def stage_selected(self) -> object:
        self.calls.append("stage_selected")
        return object()

    def cancel_staging(self) -> object:
        self.calls.append("cancel_staging")
        self.staged_action = None
        self.staged_identity = None
        return object()

    def invalidate_radio(self) -> object:
        self.calls.append("invalidate_radio")
        return object()

    def next_pota_band(self) -> object:
        return object()

    def next_pota_mode(self) -> object:
        return object()

    def next_dx_band(self) -> object:
        return object()

    def next_dx_mode(self) -> object:
        return object()


class RecordingRepeaterPanel:
    def __init__(self) -> None:
        self.selected_stable_key: str | None = None
        self.staged_action: StagedRepeaterActiveAction | None = None
        self.radio_staged_action: StagedRepeaterRadioAction | None = None
        self.calls: list[str] = []
        rx = Frequency(hz=52_010_000)
        record = RepeaterRecord(
            identity=RepeaterIdentity(name="K1AAA Alpha", rx_frequency=rx),
            name="K1AAA Alpha",
            callsign="K1AAA",
            channel_type=RepeaterChannelType.ANALOGUE,
            rx_frequency=rx,
            tx_frequency=Frequency(hz=51_010_000),
            bandwidth_khz=Decimal(25),
            rx_tone_hz=Decimal("100.0"),
            tx_tone_hz=Decimal("100.0"),
            location=RepeaterLocation(latitude=39.5, longitude=-84.0),
            source_active=True,
        )
        self.record = record
        self.action = StagedRepeaterActiveAction.from_nearby(
            NearbyRepeater(record, distance_miles=5.0, effective_active=True)
        )

    def activate(self) -> object:
        self.calls.append("activate")
        return object()

    def toggle_filter(self) -> object:
        self.calls.append("toggle_filter")
        self.staged_action = None
        self.radio_staged_action = None
        return object()

    def select_previous(self) -> object:
        self.calls.append("select_previous")
        self.radio_staged_action = None
        return object()

    def select_next(self) -> object:
        self.calls.append("select_next")
        self.selected_stable_key = self.action.stable_key
        self.radio_staged_action = None
        return object()

    def clear_selection(self) -> object:
        self.calls.append("clear_selection")
        self.selected_stable_key = None
        self.staged_action = None
        self.radio_staged_action = None
        return object()

    def stage_selected(self) -> object:
        self.calls.append("stage_selected")
        if self.selected_stable_key is not None:
            self.staged_action = self.action
        return object()

    def cancel_staging(self) -> object:
        self.calls.append("cancel_staging")
        self.staged_action = None
        return object()

    def stage_selected_radio(self) -> object:
        self.calls.append("stage_radio")
        if self.selected_stable_key is not None:
            self.radio_staged_action = StagedRepeaterRadioAction.from_repeater(self.record)
        return object()

    def cancel_radio_staging(self) -> object:
        self.calls.append("cancel_radio")
        self.radio_staged_action = None
        return object()

    def invalidate_radio(self) -> object:
        self.calls.append("invalidate_radio")
        self.radio_staged_action = None
        return object()


class RecordingPersistence:
    def __init__(self, *, accept: bool = True) -> None:
        self.accept = accept
        self.actions: list[StagedRepeaterActiveAction] = []

    def start_persist(self, action: StagedRepeaterActiveAction) -> bool:
        self.actions.append(action)
        return self.accept


def build_controller(
    *,
    persistence: RecordingPersistence | None = None,
    radio_state_called: list[bool] | None = None,
) -> tuple[
    SharedSpotActivePanelCommandController,
    ContextNavigationController,
    InertSharedPanel,
    RecordingRepeaterPanel,
]:
    navigation = ContextNavigationController(ContextId.REPEATERS)
    shared = InertSharedPanel()
    repeater = RecordingRepeaterPanel()

    def radio_state() -> RadioState:
        if radio_state_called is not None:
            radio_state_called.append(True)
        raise AssertionError("Active-only repeater controls must not inspect radio state")

    controller = SharedSpotActivePanelCommandController(
        navigation,
        shared,
        current_frequency=lambda: Frequency(hz=7_150_000),
        radio_state=radio_state,
        repeater_panel=repeater,
        repeater_active_overrides=persistence,
    )
    return controller, navigation, shared, repeater


def test_repeater_context_activates_panel_and_cancels_shared_staging() -> None:
    _controller, _navigation, shared, repeater = build_controller()

    assert shared.calls == ["cancel_staging"]
    assert repeater.calls == ["activate"]


def test_primary_toggles_filter_and_encoder_moves_repeater_selection() -> None:
    controller, _navigation, _shared, repeater = build_controller()
    repeater.calls.clear()

    assert controller.primary() is True
    assert controller.move_next() is True
    assert controller.move_previous() is False

    assert repeater.calls == ["toggle_filter", "select_next", "select_previous"]


def test_context_button_two_flips_selected_active_in_one_press_without_radio() -> None:
    persistence = RecordingPersistence()
    radio_calls: list[bool] = []
    controller, _navigation, _shared, repeater = build_controller(
        persistence=persistence,
        radio_state_called=radio_calls,
    )
    controller.move_next()
    repeater.calls.clear()

    assert controller.secondary() is True

    assert persistence.actions == [repeater.action]
    assert repeater.action.target_active is False
    assert repeater.calls == ["cancel_radio", "stage_selected", "cancel_staging"]
    assert repeater.staged_action is None
    assert repeater.radio_staged_action is None
    assert radio_calls == []


def test_context_button_two_requires_a_selected_repeater() -> None:
    persistence = RecordingPersistence()
    controller, _navigation, _shared, repeater = build_controller(persistence=persistence)
    repeater.calls.clear()

    assert controller.secondary() is False

    assert persistence.actions == []
    assert repeater.calls == ["cancel_radio", "stage_selected"]
    assert repeater.staged_action is None


def test_busy_active_persistence_does_not_leave_operator_stage() -> None:
    persistence = RecordingPersistence(accept=False)
    controller, _navigation, _shared, repeater = build_controller(persistence=persistence)
    controller.move_next()
    repeater.calls.clear()

    assert controller.secondary() is False

    assert persistence.actions == [repeater.action]
    assert repeater.staged_action is None
    assert repeater.calls == ["cancel_radio", "stage_selected", "cancel_staging"]


def test_encoder_without_repeater_capability_does_not_mutate_active_state() -> None:
    persistence = RecordingPersistence()
    radio_calls: list[bool] = []
    controller, _navigation, _shared, repeater = build_controller(
        persistence=persistence,
        radio_state_called=radio_calls,
    )
    controller.move_next()
    repeater.calls.clear()

    assert controller.activate_selection() is False

    assert persistence.actions == []
    assert repeater.staged_action is None
    assert repeater.radio_staged_action is None
    assert radio_calls == []


def test_back_clears_repeater_selection_without_active_persistence() -> None:
    persistence = RecordingPersistence()
    controller, _navigation, _shared, repeater = build_controller(persistence=persistence)
    controller.move_next()

    assert controller.back() is True
    assert repeater.selected_stable_key is None
    assert controller.back() is False
    assert persistence.actions == []


def test_context_change_performs_no_active_persistence() -> None:
    persistence = RecordingPersistence()
    controller, navigation, shared, repeater = build_controller(persistence=persistence)
    controller.move_next()

    navigation.select(ContextId.AI)
    controller.activate_context(ContextId.AI)

    assert repeater.staged_action is None
    assert repeater.radio_staged_action is None
    assert persistence.actions == []
    assert shared.calls[-1] == "cancel_staging"
    assert repeater.calls[-2:] == ["cancel_staging", "cancel_radio"]
