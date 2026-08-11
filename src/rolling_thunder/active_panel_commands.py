"""Context-aware operator interactions for the active dashboard panel."""

from collections.abc import Callable
from typing import Protocol

from rolling_thunder.context_navigation import ContextId, ContextNavigationController
from rolling_thunder.domain import (
    Frequency,
    RadioConnectionState,
    RadioState,
)
from rolling_thunder.pota_tune_intent import PotaTuneIntent, PotaTuneIntentStatus
from rolling_thunder.repeater_panel import StagedRepeaterActiveAction
from rolling_thunder.spot_domain import SpotIdentity, SpotProvider
from rolling_thunder.spot_selection import StagedSpotAction


class PotaPanelCommands(Protocol):
    """POTA selection capabilities used by active-panel commands."""

    @property
    def selected_index(self) -> int | None:
        """Return the selected POTA row index, if any."""

    @property
    def tune_intent(self) -> PotaTuneIntent | None:
        """Return the current POTA tune intent, if any."""

    def select_previous(self) -> object:
        """Move the POTA selection toward the first row."""

    def select_next(self) -> object:
        """Move the POTA selection toward the last row."""

    def clear_selection(self) -> object:
        """Clear the POTA row selection and any associated intent."""


class PotaFilterCommands(Protocol):
    """Fixed mobile POTA filter-cycle capabilities."""

    def next_band(self) -> object:
        """Cycle to the next supported mobile HF band."""

    def next_mode(self) -> object:
        """Cycle to the next supported POTA mode group."""


class PotaTuneCommands(Protocol):
    """UI-safe POTA tune-intent capabilities."""

    def advance(self) -> bool:
        """Advance the guarded stage, confirm, and execute workflow once."""

    def request(self) -> PotaTuneIntent | None:
        """Stage an intent for the selected POTA row without radio access."""

    def cancel(self) -> PotaTuneIntent | None:
        """Cancel the current POTA intent without radio access."""


class SharedSpotPanelCommands(Protocol):
    """Provider-neutral selection and staging capabilities for POTA/DX."""

    @property
    def provider(self) -> SpotProvider:
        """Return the currently active provider view."""

    @property
    def selected_identity(self) -> SpotIdentity | None:
        """Return the selected stable identity, if any."""

    @property
    def staged_identity(self) -> SpotIdentity | None:
        """Return the currently valid staged identity, if any."""

    @property
    def staged_action(self) -> StagedSpotAction | None:
        """Return the exact still-valid staged receive action, if any."""

    def activate(
        self,
        provider: SpotProvider,
        *,
        current_frequency: Frequency | None = None,
    ) -> object:
        """Activate one shared provider view."""

    def select_previous(self) -> object:
        """Move selection toward the first visible shared row."""

    def select_next(self) -> object:
        """Move selection toward the last visible shared row."""

    def clear_selection(self) -> object:
        """Clear shared selection and staging."""

    def stage_selected(self) -> object:
        """Stage the selected shared spot without external work."""

    def cancel_staging(self) -> object:
        """Cancel shared staging without external work."""

    def invalidate_radio(self) -> object:
        """Invalidate staging after an unsafe or unavailable radio state."""

    def next_pota_band(self) -> object:
        """Cycle the migrated POTA band filter."""

    def next_pota_mode(self) -> object:
        """Cycle the migrated POTA mode filter."""

    def next_dx_band(self) -> object:
        """Cycle the shared DX band filter."""

    def next_dx_mode(self) -> object:
        """Cycle the shared DX mode filter."""


class SharedSpotTuneCommands(Protocol):
    """Background receive tuning after explicit second activation."""

    def start_tune(self, action: StagedSpotAction) -> bool:
        """Submit one exact staged receive action without blocking."""


class RepeaterPanelCommands(Protocol):
    """No-I/O repeater selection, filtering, and exact Active action capture."""

    @property
    def selected_stable_key(self) -> str | None:
        """Return selected repeater stable identity, if any."""

    @property
    def staged_action(self) -> StagedRepeaterActiveAction | None:
        """Return the exact transient local Active action, if any."""

    def activate(self) -> object:
        """Synchronize the repeater view."""

    def toggle_filter(self) -> object:
        """Toggle active-only versus all repeaters."""

    def select_previous(self) -> object:
        """Move toward the previous visible repeater."""

    def select_next(self) -> object:
        """Move toward the next visible repeater."""

    def clear_selection(self) -> object:
        """Clear repeater selection and transient Active state."""

    def stage_selected(self) -> object:
        """Capture the exact inverse Active action without persistence."""

    def cancel_staging(self) -> object:
        """Clear the transient local Active action."""


class RepeaterActiveOverrideCommands(Protocol):
    """Background persistence boundary for one Context Button #2 press."""

    def start_persist(self, action: StagedRepeaterActiveAction) -> bool:
        """Submit one exact Active override without blocking."""


class SettingsPanelCommands(Protocol):
    """Nonblocking operator commands owned by the Settings context."""

    def toggle_radar(self) -> bool:
        """Toggle the Pi-side radar image through Context Button #1."""

    def zoom_out(self) -> bool:
        """Decrease map zoom one step when possible."""

    def zoom_in(self) -> bool:
        """Increase map zoom one step when possible."""


class ActivePanelCommandController:
    """Route generic selection controls to the legacy active POTA panel."""

    def __init__(
        self,
        context_navigation: ContextNavigationController,
        pota_panel: PotaPanelCommands,
        pota_filters: PotaFilterCommands,
        pota_tune: PotaTuneCommands,
    ) -> None:
        self._context_navigation = context_navigation
        self._pota_panel = pota_panel
        self._pota_filters = pota_filters
        self._pota_tune = pota_tune

    def activate_context(self, context_id: ContextId) -> None:
        """Preserve legacy behavior while shared-panel migration is in progress."""
        del context_id

    def primary(self) -> bool:
        """Run the active panel's first context-sensitive command."""
        if not self._pota_is_active():
            return False
        self._pota_filters.next_band()
        return True

    def secondary(self) -> bool:
        """Run the active panel's second context-sensitive command."""
        if not self._pota_is_active():
            return False
        self._pota_filters.next_mode()
        return True

    def tertiary(self) -> bool:
        """Return false while the active panel has no tertiary command."""
        return False

    def tertiary_long(self) -> bool:
        """Return false while the active panel has no tertiary-long command."""
        return False

    def move_previous(self) -> bool:
        """Move selection in the active panel when that panel supports it."""
        if not self._pota_is_active():
            return False

        previous_index = self._pota_panel.selected_index
        self._pota_panel.select_previous()
        return self._pota_panel.selected_index != previous_index

    def move_next(self) -> bool:
        """Move selection in the active panel when that panel supports it."""
        if not self._pota_is_active():
            return False

        previous_index = self._pota_panel.selected_index
        self._pota_panel.select_next()
        return self._pota_panel.selected_index != previous_index

    def activate_selection(self) -> bool:
        """Advance one guarded POTA tune step for the active selection."""
        if not self._pota_is_active():
            return False
        return self._pota_tune.advance()

    def back(self) -> bool:
        """Handle Back within the currently active panel."""
        if not self._pota_is_active():
            return False

        intent = self._pota_panel.tune_intent
        if intent is not None and intent.status is not PotaTuneIntentStatus.CANCELLED:
            cancelled = self._pota_tune.cancel()
            return cancelled is not None and cancelled.status is PotaTuneIntentStatus.CANCELLED

        if self._pota_panel.selected_index is None:
            return False

        self._pota_panel.clear_selection()
        return True

    def _pota_is_active(self) -> bool:
        """Return whether POTA currently owns the active context area."""
        return self._context_navigation.state.selected is ContextId.POTA


class SharedSpotActivePanelCommandController:
    """Route POTA/DX/Repeater/Settings controls through the active context."""

    def __init__(
        self,
        context_navigation: ContextNavigationController,
        shared_panel: SharedSpotPanelCommands,
        *,
        current_frequency: Callable[[], Frequency | None],
        radio_state: Callable[[], RadioState] | None = None,
        shared_tuning: SharedSpotTuneCommands | None = None,
        settings_panel: SettingsPanelCommands | None = None,
        repeater_panel: RepeaterPanelCommands | None = None,
        repeater_active_overrides: RepeaterActiveOverrideCommands | None = None,
    ) -> None:
        self._context_navigation = context_navigation
        self._shared_panel = shared_panel
        self._current_frequency = current_frequency
        self._radio_state = radio_state
        self._shared_tuning = shared_tuning
        self._settings_panel = settings_panel
        self._repeater_panel = repeater_panel
        self._repeater_active_overrides = repeater_active_overrides
        self.activate_context(context_navigation.state.selected)

    def activate_context(self, context_id: ContextId) -> None:
        """Synchronize active view and invalidate unrelated staged actions."""
        repeater = self._repeater_panel
        if context_id is ContextId.POTA:
            if repeater is not None:
                repeater.cancel_staging()
            self._shared_panel.activate(
                SpotProvider.POTA,
                current_frequency=self._current_frequency(),
            )
            return
        if context_id is ContextId.DX:
            if repeater is not None:
                repeater.cancel_staging()
            self._shared_panel.activate(
                SpotProvider.DX,
                current_frequency=self._current_frequency(),
            )
            return

        self._shared_panel.cancel_staging()
        if context_id is ContextId.REPEATERS and repeater is not None:
            repeater.activate()
            return
        if repeater is not None:
            repeater.cancel_staging()

    def primary(self) -> bool:
        """Run Context Button #1 for the active provider, repeater, or Settings panel."""
        if self._pota_is_active():
            self._shared_panel.next_pota_band()
            return True
        if self._dx_is_active():
            self._shared_panel.next_dx_band()
            return True
        if self._repeater_is_active():
            if self._repeater_panel is None:
                return False
            self._repeater_panel.toggle_filter()
            return True
        if self._settings_is_active():
            return self._settings_panel is not None and self._settings_panel.toggle_radar()
        return False

    def secondary(self) -> bool:
        """Run Context Button #2 for the active provider or repeater panel."""
        if self._pota_is_active():
            self._shared_panel.next_pota_mode()
            return True
        if self._dx_is_active():
            self._shared_panel.next_dx_mode()
            return True
        if self._repeater_is_active():
            return self._toggle_repeater_active()
        return False

    def tertiary(self) -> bool:
        """Return false while the shared/repeater panel has no tertiary command."""
        return False

    def tertiary_long(self) -> bool:
        """Return false while the shared/repeater panel has no tertiary-long command."""
        return False

    def move_previous(self) -> bool:
        """Move active selection, or zoom out when Settings owns the encoder."""
        if self._settings_is_active():
            return self._settings_panel is not None and self._settings_panel.zoom_out()
        if self._repeater_is_active():
            repeater = self._repeater_panel
            if repeater is None:
                return False
            previous = repeater.selected_stable_key
            repeater.select_previous()
            return repeater.selected_stable_key != previous
        if not self._shared_spot_is_active():
            return False
        previous_identity = self._shared_panel.selected_identity
        self._shared_panel.select_previous()
        return self._shared_panel.selected_identity != previous_identity

    def move_next(self) -> bool:
        """Move active selection, or zoom in when Settings owns the encoder."""
        if self._settings_is_active():
            return self._settings_panel is not None and self._settings_panel.zoom_in()
        if self._repeater_is_active():
            repeater = self._repeater_panel
            if repeater is None:
                return False
            previous = repeater.selected_stable_key
            repeater.select_next()
            return repeater.selected_stable_key != previous
        if not self._shared_spot_is_active():
            return False
        previous_identity = self._shared_panel.selected_identity
        self._shared_panel.select_next()
        return self._shared_panel.selected_identity != previous_identity

    def activate_selection(self) -> bool:
        """Advance shared tuning; reserve repeater encoder activation for #169."""
        if self._repeater_is_active():
            return False
        if not self._shared_spot_is_active():
            return False

        if not self.synchronize_radio_state():
            return False

        staged = self._shared_panel.staged_action
        if staged is None:
            self._shared_panel.stage_selected()
            return self._shared_panel.staged_action is not None

        tuning = self._shared_tuning
        if tuning is None:
            return False
        if not tuning.start_tune(staged):
            return False

        self._shared_panel.cancel_staging()
        return True

    def _toggle_repeater_active(self) -> bool:
        """Submit one exact inverse Active override from Context Button #2."""
        repeater = self._repeater_panel
        persistence = self._repeater_active_overrides
        if repeater is None or persistence is None:
            return False

        repeater.stage_selected()
        action = repeater.staged_action
        if action is None:
            return False

        accepted = persistence.start_persist(action)
        repeater.cancel_staging()
        return accepted

    def synchronize_radio_state(self) -> bool:
        """Invalidate spot staging when radio state is unsafe for retuning."""
        if not self._shared_spot_is_active():
            return True
        provider = self._radio_state
        if provider is None:
            return True

        state = provider()
        usable = (
            state.connection_state is RadioConnectionState.CONNECTED
            and state.frequency is not None
            and state.mode is not None
            and not state.transmitting
        )
        if usable:
            return True

        if self._shared_panel.staged_action is not None:
            self._shared_panel.invalidate_radio()
        return False

    def back(self) -> bool:
        """Cancel staging first, then clear selection on a later Back action."""
        if self._repeater_is_active():
            repeater = self._repeater_panel
            if repeater is None:
                return False
            if repeater.staged_action is not None:
                repeater.cancel_staging()
                return True
            if repeater.selected_stable_key is None:
                return False
            repeater.clear_selection()
            return True

        if not self._shared_spot_is_active():
            return False
        if self._shared_panel.staged_identity is not None:
            self._shared_panel.cancel_staging()
            return True
        if self._shared_panel.selected_identity is None:
            return False
        self._shared_panel.clear_selection()
        return True

    def _shared_spot_is_active(self) -> bool:
        return self._context_navigation.state.selected in {ContextId.POTA, ContextId.DX}

    def _pota_is_active(self) -> bool:
        return self._context_navigation.state.selected is ContextId.POTA

    def _dx_is_active(self) -> bool:
        return self._context_navigation.state.selected is ContextId.DX

    def _repeater_is_active(self) -> bool:
        return self._context_navigation.state.selected is ContextId.REPEATERS

    def _settings_is_active(self) -> bool:
        return self._context_navigation.state.selected is ContextId.SETTINGS
