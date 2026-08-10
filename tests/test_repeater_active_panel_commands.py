"""Tests for REPEATERS context command routing and two-press Active control."""

from decimal import Decimal

from rolling_thunder.active_panel_commands import SharedSpotActivePanelCommandController
from rolling_thunder.context_navigation import ContextId, ContextNavigationController
from rolling_thunder.domain import Frequency, RadioState
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

    def activate(self, provider: SpotProvider, *, current_frequency: Frequency | None = None) -> object:
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
        self.action = StagedRepeaterActiveAction.from_nearby(
            NearbyRepeater(record, distance_miles=5.0, effective_active=True)
        )

    def activate(self) -> object:
        self.calls.append("activate")
        return object()

    def toggle_filter(self) -> object:
        self.calls.append("toggle_filter")
        self.staged_action = None
        return object()

    def select_previous(self) -> object:
        self.calls.append("select_previous")
        return object()

    def select_next(self) -> object:
        self.calls.append("select_next")
        self.selected_stable_key = self.action.stable_key
        return object()

    def clear_selection(self) -> object:
        self.calls.append("clear_selection")
        self.selected_stable_key = None
        self.staged_action = None
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
        raise AssertionError("repeater controls must not inspect radio state")

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


def test_first_press_stages_without_persistence_or_radio_access() -> None:
    persistence = RecordingPersistence()
    radio_calls: list[bool] = []
    controller, _navigation, _shared, repeater = build_controller(
        persistence=persistence,
        radio_state_called=radio_calls,
    )
    controller.move_next()
    repeater.calls.clear()

    assert controller.activate_selection() is True

    assert repeater.calls == ["stage_selected"]
    assert repeater.staged_action == repeater.action
    assert persistence.actions == []
    assert radio_calls == []


def test_second_identical_press_submits_exact_active_action_and_clears_stage() -> None:
    persistence = RecordingPersistence()
    radio_calls: list[bool] = []
    controller, _navigation, _shared, repeater = build_controller(
        persistence=persistence,
        radio_state_called=radio_calls,
    )
    controller.move_next()
    assert controller.activate_selection() is True
    staged = repeater.staged_action
    assert staged is not None
    repeater.calls.clear()

    assert controller.activate_selection() is True

    assert persistence.actions == [staged]
    assert repeater.calls == ["cancel_staging"]
    assert repeater.staged_action is None
    assert radio_calls == []


def test_busy_persistence_keeps_staged_action_for_unambiguous_retry() -> None:
    persistence = RecordingPersistence(accept=False)
    controller, _navigation, _shared, repeater = build_controller(persistence=persistence)
    controller.move_next()
    controller.activate_selection()
    staged = repeater.staged_action
    assert staged is not None
    repeater.calls.clear()

    assert controller.activate_selection() is False

    assert persistence.actions == [staged]
    assert repeater.staged_action == staged
    assert repeater.calls == []


def test_back_cancels_active_stage_then_clears_selection() -> None:
    controller, _navigation, _shared, repeater = build_controller()
    controller.move_next()
    controller.activate_selection()

    assert controller.back() is True
    assert repeater.selected_stable_key is not None
    assert repeater.staged_action is None

    assert controller.back() is True
    assert repeater.selected_stable_key is None
    assert controller.back() is False


def test_context_change_invalidates_repeater_staging_without_persistence() -> None:
    persistence = RecordingPersistence()
    controller, navigation, shared, repeater = build_controller(persistence=persistence)
    controller.move_next()
    controller.activate_selection()
    assert repeater.staged_action is not None

    navigation.select(ContextId.AI)
    controller.activate_context(ContextId.AI)

    assert repeater.staged_action is None
    assert persistence.actions == []
    assert shared.calls[-1] == "cancel_staging"
