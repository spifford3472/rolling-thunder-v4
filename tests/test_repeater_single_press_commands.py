"""Single-press repeater operator-command acceptance tests."""

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal

from rolling_thunder.active_panel_commands import SharedSpotActivePanelCommandController
from rolling_thunder.context_navigation import ContextId, ContextNavigationController
from rolling_thunder.domain import Frequency, RadioConnectionState, RadioMode, RadioState
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

_TEST_TIME = datetime(2026, 8, 11, 22, 0, tzinfo=UTC)


class InertSharedPanel:
    provider = SpotProvider.POTA
    selected_identity: SpotIdentity | None = None
    staged_identity: SpotIdentity | None = None
    staged_action: StagedSpotAction | None = None

    def activate(
        self,
        provider: SpotProvider,
        *,
        current_frequency: Frequency | None = None,
    ) -> object:
        del current_frequency
        self.provider = provider
        return object()

    def select_previous(self) -> object:
        return object()

    def select_next(self) -> object:
        return object()

    def clear_selection(self) -> object:
        return object()

    def selected_tune_action(self) -> StagedSpotAction | None:
        return None

    def cancel_staging(self) -> object:
        return object()

    def invalidate_radio(self) -> object:
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
        rx = Frequency(hz=53_050_000)
        self.record = RepeaterRecord(
            identity=RepeaterIdentity(name="K8AAA Alpha", rx_frequency=rx),
            name="K8AAA Alpha",
            callsign="K8AAA",
            channel_type=RepeaterChannelType.ANALOGUE,
            rx_frequency=rx,
            tx_frequency=Frequency(hz=52_050_000),
            bandwidth_khz=Decimal(25),
            rx_tone_hz=None,
            tx_tone_hz=Decimal("131.8"),
            location=RepeaterLocation(latitude=39.5, longitude=-84.0),
            source_active=True,
        )
        nearby = NearbyRepeater(self.record, distance_miles=5.0, effective_active=True)
        self.active_action = StagedRepeaterActiveAction.from_nearby(nearby)
        self.selected_stable_key: str | None = None
        self.staged_action: StagedRepeaterActiveAction | None = None
        self.radio_staged_action: StagedRepeaterRadioAction | None = None
        self.calls: list[str] = []

    def activate(self) -> object:
        self.calls.append("activate")
        return object()

    def toggle_filter(self) -> object:
        self.calls.append("toggle_filter")
        return object()

    def select_previous(self) -> object:
        self.calls.append("select_previous")
        return object()

    def select_next(self) -> object:
        self.calls.append("select_next")
        self.selected_stable_key = self.record.stable_key
        return object()

    def clear_selection(self) -> object:
        self.calls.append("clear_selection")
        self.selected_stable_key = None
        self.staged_action = None
        return object()

    def stage_selected(self) -> object:
        self.calls.append("stage_selected_active")
        if self.selected_stable_key is not None:
            self.staged_action = self.active_action
        return object()

    def cancel_staging(self) -> object:
        self.calls.append("cancel_active")
        self.staged_action = None
        return object()

    def selected_radio_action(self) -> StagedRepeaterRadioAction | None:
        self.calls.append("selected_radio_action")
        if self.selected_stable_key is None:
            return None
        return StagedRepeaterRadioAction.from_repeater(self.record)

    def cancel_radio_staging(self) -> object:
        self.calls.append("cancel_radio")
        self.radio_staged_action = None
        return object()

    def invalidate_radio(self) -> object:
        self.calls.append("invalidate_radio")
        self.radio_staged_action = None
        return object()


class RecordingExecutor:
    def __init__(self, *, accept: bool = True) -> None:
        self.accept = accept
        self.is_configuring = False
        self.actions: list[StagedRepeaterRadioAction] = []

    @property
    def configuring(self) -> bool:
        return self.is_configuring

    def start_configure(self, action: StagedRepeaterRadioAction) -> bool:
        self.actions.append(action)
        if self.accept:
            self.is_configuring = True
        return self.accept


class RecordingPersistence:
    def __init__(self) -> None:
        self.actions: list[StagedRepeaterActiveAction] = []

    def start_persist(self, action: StagedRepeaterActiveAction) -> bool:
        self.actions.append(action)
        return True


def connected_state() -> RadioState:
    return RadioState(
        connection_state=RadioConnectionState.CONNECTED,
        frequency=Frequency(hz=50_100_000),
        mode=RadioMode.USB,
        transmitting=False,
        updated_at=_TEST_TIME,
    )


def build(
    *,
    radio_state: Callable[[], RadioState] = connected_state,
) -> tuple[
    SharedSpotActivePanelCommandController,
    ContextNavigationController,
    RecordingRepeaterPanel,
    RecordingExecutor,
    RecordingPersistence,
]:
    panel = RecordingRepeaterPanel()
    executor = RecordingExecutor()
    persistence = RecordingPersistence()
    navigation = ContextNavigationController(ContextId.REPEATERS)
    controller = SharedSpotActivePanelCommandController(
        navigation,
        InertSharedPanel(),
        current_frequency=lambda: Frequency(hz=50_100_000),
        radio_state=radio_state,
        repeater_panel=panel,
        repeater_active_overrides=persistence,
        repeater_configuration=executor,
    )
    panel.calls.clear()
    return controller, navigation, panel, executor, persistence


def test_single_encoder_press_executes_exact_selected_repeater_once() -> None:
    controller, _navigation, panel, executor, _persistence = build()
    controller.move_next()
    panel.calls.clear()

    assert controller.activate_selection() is True

    assert len(executor.actions) == 1
    assert executor.actions[0].repeater == panel.record
    assert panel.calls == ["selected_radio_action"]


def test_rapid_second_press_is_rejected_while_configuration_is_running() -> None:
    controller, _navigation, panel, executor, _persistence = build()
    controller.move_next()
    assert controller.activate_selection() is True
    panel.calls.clear()

    assert controller.activate_selection() is False

    assert len(executor.actions) == 1
    assert panel.calls == []


def test_no_selection_performs_zero_radio_execution() -> None:
    controller, _navigation, panel, executor, _persistence = build()
    panel.calls.clear()

    assert controller.activate_selection() is False

    assert executor.actions == []
    assert panel.calls == ["selected_radio_action"]


def test_radio_disconnect_blocks_single_press_before_action_snapshot() -> None:
    controller, _navigation, panel, executor, _persistence = build(
        radio_state=lambda: RadioState(
            connection_state=RadioConnectionState.DISCONNECTED,
            updated_at=_TEST_TIME,
        )
    )
    controller.move_next()
    panel.calls.clear()

    assert controller.activate_selection() is False

    assert executor.actions == []
    assert panel.calls == []


def test_context_button_two_remains_active_only() -> None:
    controller, _navigation, panel, executor, persistence = build()
    controller.move_next()

    assert controller.secondary() is True

    assert executor.actions == []
    assert persistence.actions == [panel.active_action]


def test_back_clears_repeater_selection_without_radio_confirmation_state() -> None:
    controller, _navigation, panel, executor, _persistence = build()
    controller.move_next()
    panel.calls.clear()

    assert controller.back() is True

    assert panel.selected_stable_key is None
    assert executor.actions == []
    assert panel.calls == ["clear_selection"]
