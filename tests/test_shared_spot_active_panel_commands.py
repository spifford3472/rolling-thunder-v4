"""Tests for shared POTA/DX single-press active-panel command routing."""

from collections.abc import Callable
from datetime import UTC, datetime

from rolling_thunder.active_panel_commands import SharedSpotActivePanelCommandController
from rolling_thunder.context_navigation import ContextId, ContextNavigationController
from rolling_thunder.domain import Frequency, RadioConnectionState, RadioMode, RadioState
from rolling_thunder.spot_domain import DxSpotIdentity, PotaSpotIdentity, SpotIdentity, SpotProvider
from rolling_thunder.spot_selection import StagedSpotAction


class RecordingSharedPanel:
    def __init__(self) -> None:
        self.provider = SpotProvider.POTA
        self.selected_identity: SpotIdentity | None = None
        self.staged_identity: SpotIdentity | None = None
        self.staged_action: StagedSpotAction | None = None
        self.calls: list[str] = []
        self._pota_identity = PotaSpotIdentity(
            park_reference="US-1234",
            frequency=Frequency(hz=14_250_000),
        )
        self._dx_identity = DxSpotIdentity(
            callsign="K1DX",
            frequency=Frequency(hz=14_020_000),
        )

    def activate(
        self,
        provider: SpotProvider,
        *,
        current_frequency: Frequency | None = None,
    ) -> object:
        if provider is not self.provider:
            self.selected_identity = None
        self.provider = provider
        frequency_hz = current_frequency.hz if current_frequency is not None else None
        self.calls.append(f"activate:{provider.value}:{frequency_hz}")
        return object()

    def select_previous(self) -> object:
        self.calls.append("select_previous")
        return object()

    def select_next(self) -> object:
        self.calls.append("select_next")
        self.selected_identity = (
            self._pota_identity if self.provider is SpotProvider.POTA else self._dx_identity
        )
        return object()

    def clear_selection(self) -> object:
        self.calls.append("clear_selection")
        self.selected_identity = None
        return object()

    def selected_tune_action(self) -> StagedSpotAction | None:
        self.calls.append("selected_tune_action")
        if self.selected_identity is None:
            return None
        if self.provider is SpotProvider.POTA:
            return StagedSpotAction(
                identity=self._pota_identity,
                callsign="K1POTA",
                frequency=Frequency(hz=14_250_000),
                mode=RadioMode.USB,
            )
        return StagedSpotAction(
            identity=self._dx_identity,
            callsign="K1DX",
            frequency=Frequency(hz=14_020_000),
            mode=RadioMode.CW,
        )

    def cancel_staging(self) -> object:
        self.calls.append("cancel_staging")
        return object()

    def invalidate_radio(self) -> object:
        self.calls.append("invalidate_radio")
        return object()

    def next_pota_band(self) -> object:
        self.calls.append("next_pota_band")
        return object()

    def next_pota_mode(self) -> object:
        self.calls.append("next_pota_mode")
        return object()

    def next_dx_band(self) -> object:
        self.calls.append("next_dx_band")
        return object()

    def next_dx_mode(self) -> object:
        self.calls.append("next_dx_mode")
        return object()


class RecordingSharedTuning:
    def __init__(self, *, accept: bool = True) -> None:
        self.accept = accept
        self.actions: list[StagedSpotAction] = []

    def start_tune(self, action: StagedSpotAction) -> bool:
        self.actions.append(action)
        return self.accept


def connected_radio_state(*, transmitting: bool = False) -> RadioState:
    return RadioState(
        connection_state=RadioConnectionState.CONNECTED,
        frequency=Frequency(hz=7_150_000),
        mode=RadioMode.LSB,
        transmitting=transmitting,
        updated_at=datetime(2026, 8, 8, 3, 55, tzinfo=UTC),
    )


def disconnected_radio_state() -> RadioState:
    return RadioState(
        connection_state=RadioConnectionState.DISCONNECTED,
        updated_at=datetime(2026, 8, 8, 3, 55, tzinfo=UTC),
    )


def build_controller(
    context: ContextId = ContextId.POTA,
    *,
    tuning: RecordingSharedTuning | None = None,
    radio_state: Callable[[], RadioState] | None = None,
) -> tuple[
    SharedSpotActivePanelCommandController,
    ContextNavigationController,
    RecordingSharedPanel,
]:
    navigation = ContextNavigationController(context)
    panel = RecordingSharedPanel()
    commands = SharedSpotActivePanelCommandController(
        navigation,
        panel,
        current_frequency=lambda: Frequency(hz=7_150_000),
        radio_state=radio_state or connected_radio_state,
        shared_tuning=tuning,
    )
    return commands, navigation, panel


def test_constructor_synchronizes_initial_pota_context_with_radio_frequency() -> None:
    _commands, _navigation, panel = build_controller()
    assert panel.calls == ["activate:pota:7150000"]


def test_pota_single_press_submits_selected_action() -> None:
    tuning = RecordingSharedTuning()
    commands, _navigation, panel = build_controller(tuning=tuning)
    commands.move_next()
    panel.calls.clear()

    assert commands.activate_selection() is True

    assert panel.calls == ["selected_tune_action"]
    assert len(tuning.actions) == 1
    assert tuning.actions[0].frequency == Frequency(hz=14_250_000)
    assert tuning.actions[0].mode is RadioMode.USB


def test_dx_single_press_submits_selected_action() -> None:
    tuning = RecordingSharedTuning()
    commands, _navigation, panel = build_controller(ContextId.DX, tuning=tuning)
    commands.move_next()
    panel.calls.clear()

    assert commands.activate_selection() is True

    assert panel.calls == ["selected_tune_action"]
    assert len(tuning.actions) == 1
    assert isinstance(tuning.actions[0].identity, DxSpotIdentity)
    assert tuning.actions[0].mode is RadioMode.CW


def test_activate_without_selection_performs_no_tune() -> None:
    tuning = RecordingSharedTuning()
    commands, _navigation, panel = build_controller(tuning=tuning)
    panel.calls.clear()

    assert commands.activate_selection() is False

    assert panel.calls == ["selected_tune_action"]
    assert tuning.actions == []


def test_busy_tuning_boundary_rejects_duplicate_activation() -> None:
    tuning = RecordingSharedTuning(accept=False)
    commands, _navigation, panel = build_controller(tuning=tuning)
    commands.move_next()
    panel.calls.clear()

    assert commands.activate_selection() is False

    assert len(tuning.actions) == 1
    assert panel.calls == ["selected_tune_action"]


def test_missing_tuning_boundary_does_not_create_confirmation_state() -> None:
    commands, _navigation, panel = build_controller()
    commands.move_next()
    panel.calls.clear()

    assert commands.activate_selection() is False

    assert panel.calls == ["selected_tune_action"]
    assert panel.staged_identity is None
    assert panel.staged_action is None


def test_unusable_radio_rejects_before_action_snapshot() -> None:
    tuning = RecordingSharedTuning()
    commands, _navigation, panel = build_controller(
        tuning=tuning,
        radio_state=disconnected_radio_state,
    )
    commands.move_next()
    panel.calls.clear()

    assert commands.activate_selection() is False

    assert panel.calls == []
    assert tuning.actions == []


def test_transmitting_radio_rejects_before_action_snapshot() -> None:
    tuning = RecordingSharedTuning()
    commands, _navigation, panel = build_controller(
        tuning=tuning,
        radio_state=lambda: connected_radio_state(transmitting=True),
    )
    commands.move_next()
    panel.calls.clear()

    assert commands.activate_selection() is False

    assert panel.calls == []
    assert tuning.actions == []


def test_back_clears_selection_in_one_step_without_confirmation_state() -> None:
    commands, _navigation, panel = build_controller()
    commands.move_next()
    panel.calls.clear()

    assert commands.back() is True
    assert panel.selected_identity is None
    assert panel.calls == ["clear_selection"]
    assert commands.back() is False


class RecordingWeatherAlertViewport:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def scroll_previous(self) -> bool:
        self.calls.append("scroll_previous")
        return True

    def scroll_next(self) -> bool:
        self.calls.append("scroll_next")
        return True


def test_weather_context_routes_encoder_movement_only_to_alert_viewport() -> None:
    navigation = ContextNavigationController(ContextId.WEATHER)
    panel = RecordingSharedPanel()
    viewport = RecordingWeatherAlertViewport()
    commands = SharedSpotActivePanelCommandController(
        navigation,
        panel,
        current_frequency=lambda: Frequency(hz=7_150_000),
        weather_alert_viewport=viewport,
    )
    panel.calls.clear()

    assert commands.move_previous() is True
    assert commands.move_next() is True
    assert viewport.calls == ["scroll_previous", "scroll_next"]
    assert panel.calls == []
