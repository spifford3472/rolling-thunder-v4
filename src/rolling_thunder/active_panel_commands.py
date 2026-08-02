"""Context-aware operator interactions for the active dashboard panel."""

from typing import Protocol

from rolling_thunder.context_navigation import ContextId, ContextNavigationController
from rolling_thunder.pota_tune_intent import PotaTuneIntent, PotaTuneIntentStatus


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
    """UI-safe POTA tune-intent and retune-warning capabilities."""

    @property
    def retune_warning_active(self) -> bool:
        """Return whether an ATAS-120 warning awaits acknowledgement."""

    def request(self) -> PotaTuneIntent | None:
        """Stage an intent for the selected POTA row without radio access."""

    def cancel(self) -> PotaTuneIntent | None:
        """Cancel the current POTA intent without radio access."""

    def acknowledge_retune_warning(self) -> bool:
        """Acknowledge the current ATAS-120 warning when present."""


class PotaOverlayCommands(Protocol):
    """Temporary POTA park-detail overlay capabilities."""

    def show_selected(self) -> bool:
        """Show details for the selected park when possible."""

    def hide(self) -> bool:
        """Dismiss the current overlay when visible."""


class ActivePanelCommandController:
    """Route generic selection controls to the currently active panel."""

    def __init__(
        self,
        context_navigation: ContextNavigationController,
        pota_panel: PotaPanelCommands,
        pota_filters: PotaFilterCommands,
        pota_tune: PotaTuneCommands,
        pota_overlay: PotaOverlayCommands | None = None,
    ) -> None:
        self._context_navigation = context_navigation
        self._pota_panel = pota_panel
        self._pota_filters = pota_filters
        self._pota_tune = pota_tune
        self._pota_overlay = pota_overlay

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
        """Show selected park details over the situational panel."""
        if not self._pota_is_active() or self._pota_overlay is None:
            return False
        return self._pota_overlay.show_selected()

    def tertiary_long(self) -> bool:
        """Dismiss the selected park detail overlay."""
        if not self._pota_is_active() or self._pota_overlay is None:
            return False
        return self._pota_overlay.hide()

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
        """Stage the active selection without confirming or executing it."""
        if not self._pota_is_active():
            return False
        return self._pota_tune.request() is not None

    def back(self) -> bool:
        """Acknowledge warnings, cancel intent, then clear selection."""
        if not self._pota_is_active():
            return False

        if self._pota_tune.retune_warning_active:
            return self._pota_tune.acknowledge_retune_warning()

        intent = self._pota_panel.tune_intent
        if intent is not None and intent.status is not PotaTuneIntentStatus.CANCELLED:
            cancelled = self._pota_tune.cancel()
            return (
                cancelled is not None
                and cancelled.status is PotaTuneIntentStatus.CANCELLED
            )

        if self._pota_panel.selected_index is None:
            return False

        self._pota_panel.clear_selection()
        return True

    def _pota_is_active(self) -> bool:
        """Return whether POTA currently owns the active context area."""
        return self._context_navigation.state.selected is ContextId.POTA
