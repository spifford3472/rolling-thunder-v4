"""Context-aware operator interactions for the active dashboard panel."""

from collections.abc import Callable
from typing import Protocol

from rolling_thunder.context_navigation import ContextId, ContextNavigationController
from rolling_thunder.domain import Frequency, RadioConnectionState, RadioState
from rolling_thunder.pota_tune_intent import PotaTuneIntent, PotaTuneIntentStatus
from rolling_thunder.repeater_configuration import StagedRepeaterRadioAction
from rolling_thunder.repeater_panel import StagedRepeaterActiveAction
from rolling_thunder.spot_domain import SpotIdentity, SpotProvider
from rolling_thunder.spot_selection import StagedSpotAction


class PotaPanelCommands(Protocol):
    @property
    def selected_index(self) -> int | None:
        ...

    @property
    def tune_intent(self) -> PotaTuneIntent | None:
        ...

    def select_previous(self) -> object:
        ...

    def select_next(self) -> object:
        ...

    def clear_selection(self) -> object:
        ...


class PotaFilterCommands(Protocol):
    def next_band(self) -> object:
        ...

    def next_mode(self) -> object:
        ...


class PotaTuneCommands(Protocol):
    def advance(self) -> bool:
        ...

    def request(self) -> PotaTuneIntent | None:
        ...

    def cancel(self) -> PotaTuneIntent | None:
        ...


class SharedSpotPanelCommands(Protocol):
    @property
    def provider(self) -> SpotProvider:
        ...

    @property
    def selected_identity(self) -> SpotIdentity | None:
        ...

    def activate(
        self,
        provider: SpotProvider,
        *,
        current_frequency: Frequency | None = None,
    ) -> object:
        ...

    def select_previous(self) -> object:
        ...

    def select_next(self) -> object:
        ...

    def clear_selection(self) -> object:
        ...

    def selected_tune_action(self) -> StagedSpotAction | None:
        ...

    def next_pota_band(self) -> object:
        ...

    def next_pota_mode(self) -> object:
        ...

    def next_dx_band(self) -> object:
        ...

    def next_dx_mode(self) -> object:
        ...


class SharedSpotTuneCommands(Protocol):
    def start_tune(self, action: StagedSpotAction) -> bool:
        ...


class PendingCallsignCommands(Protocol):
    """Mutable pending-callsign boundary shared with voice capture."""

    def preload_callsign(self, callsign: str) -> bool:
        """Preload a selected spot callsign when capture/Commit state permits."""
        ...


class RepeaterPanelCommands(Protocol):
    """No-I/O repeater selection plus transient Active-toggle state."""

    @property
    def selected_stable_key(self) -> str | None:
        ...

    @property
    def staged_action(self) -> StagedRepeaterActiveAction | None:
        ...

    def activate(self) -> object:
        ...

    def toggle_filter(self) -> object:
        ...

    def select_previous(self) -> object:
        ...

    def select_next(self) -> object:
        ...

    def clear_selection(self) -> object:
        ...

    def stage_selected(self) -> object:
        ...

    def cancel_staging(self) -> object:
        ...

    def selected_radio_action(self) -> StagedRepeaterRadioAction | None:
        ...


class RepeaterActiveOverrideCommands(Protocol):
    def start_persist(self, action: StagedRepeaterActiveAction) -> bool:
        ...


class RepeaterRadioConfigurationCommands(Protocol):
    """Background typed repeater-radio execution boundary."""

    @property
    def configuring(self) -> bool:
        ...

    def start_configure(self, action: StagedRepeaterRadioAction) -> bool:
        ...


class BrowsePanelCommands(Protocol):
    """Receive-only Browse controls implemented outside the UI thread."""

    def cycle_step(self) -> bool:
        ...

    def cycle_mode(self) -> bool:
        ...

    def adjust_frequency(self, direction: int) -> bool:
        ...


class SettingsPanelCommands(Protocol):
    def toggle_radar(self) -> bool:
        ...

    def toggle_map_style(self) -> bool:
        ...

    def toggle_callsign_info(self) -> bool:
        ...

    def zoom_out(self) -> bool:
        ...

    def zoom_in(self) -> bool:
        ...


class WeatherAlertViewportCommands(Protocol):
    """No-I/O weather alert scrolling reached through generic movement."""

    def scroll_previous(self) -> bool:
        ...

    def scroll_next(self) -> bool:
        ...


class CallsignInfoPresentationCommands(Protocol):
    """Shared station-popup lifecycle reached only through operator intent."""

    def dismiss_presentation(self) -> bool:
        """Suppress presentation across background target observation."""

    def rearm_presentation(self) -> bool:
        """Permit a fresh lifecycle after explicit station selection."""


class DelegatedActivePanelCommands(Protocol):
    """Complete active-panel surface decorated by shared lifecycle wrappers."""

    def activate_context(self, context_id: ContextId) -> None: ...
    def primary(self) -> bool: ...
    def secondary(self) -> bool: ...
    def tertiary(self) -> bool: ...
    def tertiary_long(self) -> bool: ...
    def move_previous(self) -> bool: ...
    def move_next(self) -> bool: ...
    def activate_selection(self) -> bool: ...
    def back(self) -> bool: ...
    def synchronize_radio_state(self) -> bool: ...


class CallsignInfoAwareActivePanelCommands:
    """Apply shared popup lifecycle to accepted station-browser commands."""

    _STATION_CONTEXTS = frozenset({ContextId.POTA, ContextId.DX, ContextId.FT8})

    def __init__(
        self,
        context_navigation: ContextNavigationController,
        delegate: DelegatedActivePanelCommands,
        callsign_info: CallsignInfoPresentationCommands,
    ) -> None:
        self._context_navigation = context_navigation
        self._delegate = delegate
        self._callsign_info = callsign_info
        self._last_context_id = context_navigation.state.selected

    def activate_context(self, context_id: ContextId) -> None:
        previous = self._last_context_id
        self._delegate.activate_context(context_id)
        self._last_context_id = context_id
        if context_id is not previous and previous in self._STATION_CONTEXTS:
            self._callsign_info.dismiss_presentation()

    def primary(self) -> bool:
        accepted = self._delegate.primary()
        if accepted and self._station_context_is_active():
            self._callsign_info.dismiss_presentation()
        return accepted

    def secondary(self) -> bool:
        accepted = self._delegate.secondary()
        if accepted and self._context_navigation.state.selected is ContextId.FT8:
            # FT8 Button 2 is an explicit acceptance of the exact incoming station.
            self._callsign_info.rearm_presentation()
        return accepted

    def tertiary(self) -> bool:
        return self._delegate.tertiary()

    def tertiary_long(self) -> bool:
        return self._delegate.tertiary_long()

    def move_previous(self) -> bool:
        accepted = self._delegate.move_previous()
        if self._station_context_is_active():
            self._callsign_info.dismiss_presentation()
        return accepted

    def move_next(self) -> bool:
        accepted = self._delegate.move_next()
        if self._station_context_is_active():
            self._callsign_info.dismiss_presentation()
        return accepted

    def activate_selection(self) -> bool:
        accepted = self._delegate.activate_selection()
        if accepted and self._station_context_is_active():
            self._callsign_info.rearm_presentation()
        return accepted

    def back(self) -> bool:
        return self._delegate.back()

    def synchronize_radio_state(self) -> bool:
        return self._delegate.synchronize_radio_state()

    def _station_context_is_active(self) -> bool:
        return self._context_navigation.state.selected in self._STATION_CONTEXTS


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
        del context_id

    def primary(self) -> bool:
        if not self._pota_is_active():
            return False
        self._pota_filters.next_band()
        return True

    def secondary(self) -> bool:
        if not self._pota_is_active():
            return False
        self._pota_filters.next_mode()
        return True

    def tertiary(self) -> bool:
        return False

    def tertiary_long(self) -> bool:
        return False

    def move_previous(self) -> bool:
        if not self._pota_is_active():
            return False
        previous_index = self._pota_panel.selected_index
        self._pota_panel.select_previous()
        return self._pota_panel.selected_index != previous_index

    def move_next(self) -> bool:
        if not self._pota_is_active():
            return False
        previous_index = self._pota_panel.selected_index
        self._pota_panel.select_next()
        return self._pota_panel.selected_index != previous_index

    def activate_selection(self) -> bool:
        if not self._pota_is_active():
            return False
        return self._pota_tune.advance()

    def back(self) -> bool:
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
        pending_callsign: PendingCallsignCommands | None = None,
        browse_panel: BrowsePanelCommands | None = None,
        settings_panel: SettingsPanelCommands | None = None,
        repeater_panel: RepeaterPanelCommands | None = None,
        repeater_active_overrides: RepeaterActiveOverrideCommands | None = None,
        repeater_configuration: RepeaterRadioConfigurationCommands | None = None,
        weather_alert_viewport: WeatherAlertViewportCommands | None = None,
    ) -> None:
        self._context_navigation = context_navigation
        self._shared_panel = shared_panel
        self._current_frequency = current_frequency
        self._radio_state = radio_state
        self._shared_tuning = shared_tuning
        self._pending_callsign = pending_callsign
        self._browse_panel = browse_panel
        self._settings_panel = settings_panel
        self._repeater_panel = repeater_panel
        self._repeater_active_overrides = repeater_active_overrides
        self._repeater_configuration = repeater_configuration
        self._weather_alert_viewport = weather_alert_viewport
        self.activate_context(context_navigation.state.selected)

    def activate_context(self, context_id: ContextId) -> None:
        """Synchronize the application controller with the active panel."""
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

        if context_id is ContextId.REPEATERS and repeater is not None:
            repeater.activate()
            return
        if repeater is not None:
            repeater.cancel_staging()

    def primary(self) -> bool:
        if self._pota_is_active():
            self._shared_panel.next_pota_band()
            return True
        if self._dx_is_active():
            self._shared_panel.next_dx_band()
            return True
        if self._browse_is_active():
            return False
        if self._repeater_is_active():
            if self._repeater_panel is None:
                return False
            self._repeater_panel.toggle_filter()
            return True
        if self._settings_is_active():
            return self._settings_panel is not None and self._settings_panel.toggle_radar()
        return False

    def secondary(self) -> bool:
        if self._pota_is_active():
            self._shared_panel.next_pota_mode()
            return True
        if self._dx_is_active():
            self._shared_panel.next_dx_mode()
            return True
        if self._browse_is_active():
            return self._browse_panel is not None and self._browse_panel.cycle_step()
        if self._repeater_is_active():
            return self._toggle_repeater_active()
        if self._settings_is_active():
            return self._settings_panel is not None and self._settings_panel.toggle_map_style()
        return False

    def tertiary(self) -> bool:
        if self._browse_is_active():
            return self._browse_panel is not None and self._browse_panel.cycle_mode()
        if self._settings_is_active():
            return (
                self._settings_panel is not None
                and self._settings_panel.toggle_callsign_info()
            )
        return False

    def tertiary_long(self) -> bool:
        return False

    def move_previous(self) -> bool:
        if self._browse_is_active():
            return self._browse_panel is not None and self._browse_panel.adjust_frequency(-1)
        if self._weather_is_active():
            viewport = self._weather_alert_viewport
            return viewport is not None and viewport.scroll_previous()
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
        if self._browse_is_active():
            return self._browse_panel is not None and self._browse_panel.adjust_frequency(1)
        if self._weather_is_active():
            viewport = self._weather_alert_viewport
            return viewport is not None and viewport.scroll_next()
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
        """Submit the currently selected receive target with one operator activation."""
        if self._repeater_is_active():
            return self._activate_repeater_selection()
        if not self._shared_spot_is_active():
            return False
        if not self.synchronize_radio_state():
            return False

        action = self._shared_panel.selected_tune_action()
        tuning = self._shared_tuning
        if action is None or tuning is None:
            return False

        accepted = tuning.start_tune(action)
        if not accepted:
            return False

        pending_callsign = self._pending_callsign
        if pending_callsign is not None:
            pending_callsign.preload_callsign(action.callsign)
        return True

    def _activate_repeater_selection(self) -> bool:
        repeater = self._repeater_panel
        executor = self._repeater_configuration
        if repeater is None or executor is None:
            return False
        if not self.synchronize_radio_state() or executor.configuring:
            return False

        action = repeater.selected_radio_action()
        if action is None:
            return False
        return executor.start_configure(action)

    def _toggle_repeater_active(self) -> bool:
        """Context Button #2 is Active-only and can never reach radio execution."""
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
        """Return whether the latest radio state is usable for a receive action."""
        provider = self._radio_state
        if provider is None:
            return True
        state = provider()
        return (
            state.connection_state is RadioConnectionState.CONNECTED
            and state.frequency is not None
            and state.mode is not None
            and not state.transmitting
        )

    def back(self) -> bool:
        """Back cancels Active-only work first, otherwise clears selection."""
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

    def _browse_is_active(self) -> bool:
        return self._context_navigation.state.selected is ContextId.BROWSE

    def _repeater_is_active(self) -> bool:
        return self._context_navigation.state.selected is ContextId.REPEATERS

    def _settings_is_active(self) -> bool:
        return self._context_navigation.state.selected is ContextId.SETTINGS

    def _weather_is_active(self) -> bool:
        return self._context_navigation.state.selected is ContextId.WEATHER
