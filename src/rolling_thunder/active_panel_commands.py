"""Context-aware operator interactions for the active dashboard panel."""

from collections.abc import Callable
from typing import Protocol

from rolling_thunder.context_navigation import ContextId, ContextNavigationController
from rolling_thunder.domain import Frequency
from rolling_thunder.pota_tune_intent import PotaTuneIntent, PotaTuneIntentStatus
from rolling_thunder.spot_domain import SpotIdentity, SpotProvider


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

    def next_pota_band(self) -> object:
        """Cycle the migrated POTA band filter."""

    def next_pota_mode(self) -> object:
        """Cycle the migrated POTA mode filter."""

    def next_dx_band(self) -> object:
        """Cycle the shared DX band filter."""

    def next_dx_mode(self) -> object:
        """Cycle the shared DX mode filter."""


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
    """Route POTA/DX controls through one shared provider-neutral panel."""

    def __init__(
        self,
        context_navigation: ContextNavigationController,
        shared_panel: SharedSpotPanelCommands,
        *,
        current_frequency: Callable[[], Frequency | None],
    ) -> None:
        self._context_navigation = context_navigation
        self._shared_panel = shared_panel
        self._current_frequency = current_frequency
        self.activate_context(context_navigation.state.selected)

    def activate_context(self, context_id: ContextId) -> None:
        """Synchronize provider view and invalidate staging on context change."""
        if context_id is ContextId.POTA:
            self._shared_panel.activate(
                SpotProvider.POTA,
                current_frequency=self._current_frequency(),
            )
            return
        if context_id is ContextId.DX:
            self._shared_panel.activate(
                SpotProvider.DX,
                current_frequency=self._current_frequency(),
            )
            return
        self._shared_panel.cancel_staging()

    def primary(self) -> bool:
        """Cycle the active shared provider's band filter."""
        if self._pota_is_active():
            self._shared_panel.next_pota_band()
            return True
        if self._dx_is_active():
            self._shared_panel.next_dx_band()
            return True
        return False

    def secondary(self) -> bool:
        """Cycle the active shared provider's mode filter."""
        if self._pota_is_active():
            self._shared_panel.next_pota_mode()
            return True
        if self._dx_is_active():
            self._shared_panel.next_dx_mode()
            return True
        return False

    def tertiary(self) -> bool:
        """Return false while the shared panel has no tertiary command."""
        return False

    def tertiary_long(self) -> bool:
        """Return false while the shared panel has no tertiary-long command."""
        return False

    def move_previous(self) -> bool:
        """Move shared stable selection without wrapping."""
        if not self._shared_spot_is_active():
            return False
        previous_identity = self._shared_panel.selected_identity
        self._shared_panel.select_previous()
        return self._shared_panel.selected_identity != previous_identity

    def move_next(self) -> bool:
        """Move shared stable selection without wrapping."""
        if not self._shared_spot_is_active():
            return False
        previous_identity = self._shared_panel.selected_identity
        self._shared_panel.select_next()
        return self._shared_panel.selected_identity != previous_identity

    def activate_selection(self) -> bool:
        """Stage one selected POTA/DX target without radio execution."""
        if not self._shared_spot_is_active():
            return False
        previous = self._shared_panel.staged_identity
        self._shared_panel.stage_selected()
        staged = self._shared_panel.staged_identity
        return staged is not None and staged != previous

    def back(self) -> bool:
        """Cancel staging first, then clear selection on a later Back action."""
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
