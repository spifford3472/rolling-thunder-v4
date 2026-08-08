"""Tests for shared POTA/DX active-panel command routing."""

from collections.abc import Callable
from datetime import UTC, datetime

from rolling_thunder.active_panel_commands import SharedSpotActivePanelCommandController
from rolling_thunder.context_navigation import ContextId, ContextNavigationController
from rolling_thunder.domain import (
    Frequency,
    RadioConnectionState,
    RadioMode,
    RadioState,
)
from rolling_thunder.spot_domain import (
    DxSpotIdentity,
    PotaSpotIdentity,
    SpotIdentity,
    SpotProvider,
)
from rolling_thunder.spot_selection import StagedSpotAction


class RecordingSharedPanel:
    """Small no-I/O shared-panel fake for command-routing tests."""

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
            self.staged_identity = None
            self.staged_action = None
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
        self.staged_identity = None
        self.staged_action = None
        return object()

    def stage_selected(self) -> object:
        self.calls.append("stage_selected")
        self.staged_identity = self.selected_identity
        if self.selected_identity is None:
            self.staged_action = None
        elif self.provider is SpotProvider.POTA:
            self.staged_action = StagedSpotAction(
                identity=self._pota_identity,
                callsign="K1POTA",
                frequency=Frequency(hz=14_250_000),
                mode=RadioMode.USB,
            )
        else:
            self.staged_action = StagedSpotAction(
                identity=self._dx_identity,
                callsign="K1DX",
                frequency=Frequency(hz=14_020_000),
                mode=RadioMode.CW,
            )
        return object()

    def cancel_staging(self) -> object:
        self.calls.append("cancel_staging")
        self.staged_identity = None
        self.staged_action = None
        return object()

    def invalidate_radio(self) -> object:
        self.calls.append("invalidate_radio")
        self.staged_identity = None
        self.staged_action = None
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
    """Record exact actions submitted to the background tuning boundary."""

    def __init__(self, *, accept: bool = True) -> None:
        self.accept = accept
        self.actions: list[StagedSpotAction] = []

    def start_tune(self, action: StagedSpotAction) -> bool:
        self.actions.append(action)
        return self.accept


def connected_radio_state(
    *,
    transmitting: bool = False,
) -> RadioState:
    """Return one usable immutable radio snapshot."""
    return RadioState(
        connection_state=RadioConnectionState.CONNECTED,
        frequency=Frequency(hz=7_150_000),
        mode=RadioMode.LSB,
        transmitting=transmitting,
        updated_at=datetime(2026, 8, 8, 3, 55, tzinfo=UTC),
    )


def disconnected_radio_state() -> RadioState:
    """Return one unavailable immutable radio snapshot."""
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
    assert panel.provider is SpotProvider.POTA


def test_pota_primary_secondary_and_selection_route_through_shared_panel() -> None:
    commands, _navigation, panel = build_controller()
    panel.calls.clear()

    assert commands.primary() is True
    assert commands.secondary() is True
    assert commands.move_next() is True
    assert commands.activate_selection() is True

    assert panel.calls == [
        "next_pota_band",
        "next_pota_mode",
        "select_next",
        "stage_selected",
    ]
    assert panel.selected_identity is not None
    assert panel.staged_identity == panel.selected_identity


def test_dx_uses_shared_band_mode_and_selection_commands() -> None:
    commands, _navigation, panel = build_controller(ContextId.DX)
    panel.calls.clear()

    assert panel.provider is SpotProvider.DX
    assert commands.primary() is True
    assert commands.secondary() is True
    assert commands.move_next() is True
    assert commands.activate_selection() is True

    assert panel.calls == [
        "next_dx_band",
        "next_dx_mode",
        "select_next",
        "stage_selected",
    ]
    assert isinstance(panel.selected_identity, DxSpotIdentity)


def test_pota_to_dx_context_change_invalidates_shared_staging_immediately() -> None:
    commands, navigation, panel = build_controller()
    commands.move_next()
    commands.activate_selection()
    assert panel.staged_identity is not None

    navigation.select(ContextId.DX)
    commands.activate_context(ContextId.DX)

    assert panel.provider is SpotProvider.DX
    assert panel.selected_identity is None
    assert panel.staged_identity is None
    assert panel.calls[-1] == "activate:dx:7150000"


def test_non_spot_context_cancels_staging_without_mutating_selection() -> None:
    commands, navigation, panel = build_controller()
    commands.move_next()
    commands.activate_selection()
    selected = panel.selected_identity

    navigation.select(ContextId.SETTINGS)
    commands.activate_context(ContextId.SETTINGS)

    assert panel.selected_identity == selected
    assert panel.staged_identity is None
    assert panel.calls[-1] == "cancel_staging"


def test_back_cancels_staging_before_clearing_selection() -> None:
    commands, _navigation, panel = build_controller()
    commands.move_next()
    commands.activate_selection()

    assert commands.back() is True
    assert panel.selected_identity is not None
    assert panel.staged_identity is None

    assert commands.back() is True
    assert panel.selected_identity is None

    assert commands.back() is False


def test_activate_without_explicit_selection_performs_no_radio_or_external_work() -> None:
    commands, _navigation, panel = build_controller()
    panel.calls.clear()

    assert commands.activate_selection() is False
    assert panel.calls == ["stage_selected"]
    assert panel.staged_identity is None


def test_first_press_stages_without_submitting_tune() -> None:
    tuning = RecordingSharedTuning()
    commands, _navigation, panel = build_controller(tuning=tuning)
    commands.move_next()
    panel.calls.clear()

    assert commands.activate_selection() is True

    assert panel.staged_action is not None
    assert panel.calls == ["stage_selected"]
    assert tuning.actions == []


def test_second_press_submits_exact_action_and_clears_stage() -> None:
    tuning = RecordingSharedTuning()
    commands, _navigation, panel = build_controller(
        ContextId.DX,
        tuning=tuning,
    )
    commands.move_next()
    assert commands.activate_selection() is True
    staged = panel.staged_action
    assert staged is not None

    panel.calls.clear()

    assert commands.activate_selection() is True

    assert tuning.actions == [staged]
    assert panel.calls == ["cancel_staging"]
    assert panel.staged_action is None
    assert panel.staged_identity is None


def test_busy_tuning_boundary_keeps_staged_action() -> None:
    tuning = RecordingSharedTuning(accept=False)
    commands, _navigation, panel = build_controller(tuning=tuning)
    commands.move_next()
    assert commands.activate_selection() is True
    staged = panel.staged_action
    assert staged is not None

    panel.calls.clear()

    assert commands.activate_selection() is False

    assert tuning.actions == [staged]
    assert panel.calls == []
    assert panel.staged_action == staged


def test_second_press_without_tuning_boundary_does_nothing() -> None:
    commands, _navigation, panel = build_controller()
    commands.move_next()
    assert commands.activate_selection() is True
    staged = panel.staged_action
    assert staged is not None

    panel.calls.clear()

    assert commands.activate_selection() is False

    assert panel.calls == []
    assert panel.staged_action == staged


def test_disconnect_invalidates_stage_before_background_tuning() -> None:
    current = [connected_radio_state()]
    tuning = RecordingSharedTuning()
    commands, _navigation, panel = build_controller(
        tuning=tuning,
        radio_state=lambda: current[0],
    )
    commands.move_next()
    assert commands.activate_selection() is True
    assert panel.staged_action is not None

    current[0] = disconnected_radio_state()
    panel.calls.clear()

    assert commands.synchronize_radio_state() is False

    assert panel.calls == ["invalidate_radio"]
    assert panel.staged_action is None
    assert tuning.actions == []


def test_transmitting_radio_rejects_second_press_before_worker_start() -> None:
    current = [connected_radio_state()]
    tuning = RecordingSharedTuning()
    commands, _navigation, panel = build_controller(
        ContextId.DX,
        tuning=tuning,
        radio_state=lambda: current[0],
    )
    commands.move_next()
    assert commands.activate_selection() is True
    assert panel.staged_action is not None

    current[0] = connected_radio_state(transmitting=True)
    panel.calls.clear()

    assert commands.activate_selection() is False

    assert panel.calls == ["invalidate_radio"]
    assert panel.staged_action is None
    assert tuning.actions == []
