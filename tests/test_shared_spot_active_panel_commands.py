"""Tests for shared POTA/DX active-panel command routing."""

from rolling_thunder.active_panel_commands import SharedSpotActivePanelCommandController
from rolling_thunder.context_navigation import ContextId, ContextNavigationController
from rolling_thunder.domain import Frequency
from rolling_thunder.spot_domain import DxSpotIdentity, PotaSpotIdentity, SpotIdentity, SpotProvider


class RecordingSharedPanel:
    """Small no-I/O shared-panel fake for command-routing tests."""

    def __init__(self) -> None:
        self.provider = SpotProvider.POTA
        self.selected_identity: SpotIdentity | None = None
        self.staged_identity: SpotIdentity | None = None
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
        return object()

    def stage_selected(self) -> object:
        self.calls.append("stage_selected")
        self.staged_identity = self.selected_identity
        return object()

    def cancel_staging(self) -> object:
        self.calls.append("cancel_staging")
        self.staged_identity = None
        return object()

    def next_pota_band(self) -> object:
        self.calls.append("next_pota_band")
        return object()

    def next_pota_mode(self) -> object:
        self.calls.append("next_pota_mode")
        return object()


def build_controller(
    context: ContextId = ContextId.POTA,
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


def test_dx_uses_shared_selection_but_does_not_inherit_pota_filter_commands() -> None:
    commands, _navigation, panel = build_controller(ContextId.DX)
    panel.calls.clear()

    assert panel.provider is SpotProvider.DX
    assert commands.primary() is False
    assert commands.secondary() is False
    assert commands.move_next() is True
    assert commands.activate_selection() is True

    assert panel.calls == ["select_next", "stage_selected"]
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
    assert panel.calls[-1] == "activate:dx:None"


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
