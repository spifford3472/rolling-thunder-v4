"""DMR-aware active-panel command wrapper."""

from __future__ import annotations

from typing import Protocol

from rolling_thunder.context_navigation import ContextId, ContextNavigationController


class DelegatePanelCommands(Protocol):
    """Existing active-panel command surface preserved outside DMR."""

    def activate_context(self, context_id: ContextId) -> None: ...
    def primary(self) -> bool: ...
    def secondary(self) -> bool: ...
    def tertiary(self) -> bool: ...
    def tertiary_long(self) -> bool: ...
    def move_previous(self) -> bool: ...
    def move_next(self) -> bool: ...
    def activate_selection(self) -> bool: ...
    def back(self) -> bool: ...


class DmrPanelCommands(Protocol):
    """No-I/O DMR panel command surface."""

    def refresh(self) -> object: ...
    def primary(self) -> bool: ...
    def secondary(self) -> bool: ...
    def tertiary(self) -> bool: ...
    def tertiary_long(self) -> bool: ...
    def move_previous(self) -> bool: ...
    def move_next(self) -> bool: ...
    def activate_selection(self) -> bool: ...
    def back(self) -> bool: ...


class DmrAwareActivePanelCommands:
    """Intercept controls only while the DMR context is active."""

    def __init__(
        self,
        context_navigation: ContextNavigationController,
        delegate: DelegatePanelCommands,
        dmr_panel: DmrPanelCommands,
    ) -> None:
        self._context_navigation = context_navigation
        self._delegate = delegate
        self._dmr_panel = dmr_panel

    def activate_context(self, context_id: ContextId) -> None:
        self._delegate.activate_context(context_id)
        if context_id is ContextId.DMR:
            self._dmr_panel.refresh()

    def primary(self) -> bool:
        if self._dmr_is_active():
            return self._dmr_panel.primary()
        return self._delegate.primary()

    def secondary(self) -> bool:
        if self._dmr_is_active():
            return self._dmr_panel.secondary()
        return self._delegate.secondary()

    def tertiary(self) -> bool:
        if self._dmr_is_active():
            return self._dmr_panel.tertiary()
        return self._delegate.tertiary()

    def tertiary_long(self) -> bool:
        if self._dmr_is_active():
            return self._dmr_panel.tertiary_long()
        return self._delegate.tertiary_long()

    def move_previous(self) -> bool:
        if self._dmr_is_active():
            return self._dmr_panel.move_previous()
        return self._delegate.move_previous()

    def move_next(self) -> bool:
        if self._dmr_is_active():
            return self._dmr_panel.move_next()
        return self._delegate.move_next()

    def activate_selection(self) -> bool:
        if self._dmr_is_active():
            return self._dmr_panel.activate_selection()
        return self._delegate.activate_selection()

    def back(self) -> bool:
        if self._dmr_is_active():
            return self._dmr_panel.back()
        return self._delegate.back()

    def _dmr_is_active(self) -> bool:
        return self._context_navigation.state.selected is ContextId.DMR
