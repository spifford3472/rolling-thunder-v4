"""LOG-aware wrapper preserving all existing active-panel control semantics."""

from __future__ import annotations

from typing import Protocol

from rolling_thunder.context_navigation import ContextId, ContextNavigationController


class DelegatePanelCommands(Protocol):
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


class LogSyncRequestCommands(Protocol):
    def request_sync(self) -> bool:
        """Submit synchronization in the background and return immediately."""
        ...


class LogAwareActivePanelCommands:
    """Intercept only LOG Context Button #1 and delegate every other existing command."""

    def __init__(
        self,
        context_navigation: ContextNavigationController,
        delegate: DelegatePanelCommands,
        log_sync: LogSyncRequestCommands,
    ) -> None:
        self._context_navigation = context_navigation
        self._delegate = delegate
        self._log_sync = log_sync

    def activate_context(self, context_id: ContextId) -> None:
        self._delegate.activate_context(context_id)

    def primary(self) -> bool:
        if self._context_navigation.state.selected is ContextId.LOG:
            return self._log_sync.request_sync()
        return self._delegate.primary()

    def secondary(self) -> bool:
        return self._delegate.secondary()

    def tertiary(self) -> bool:
        return self._delegate.tertiary()

    def tertiary_long(self) -> bool:
        return self._delegate.tertiary_long()

    def move_previous(self) -> bool:
        return self._delegate.move_previous()

    def move_next(self) -> bool:
        return self._delegate.move_next()

    def activate_selection(self) -> bool:
        return self._delegate.activate_selection()

    def back(self) -> bool:
        return self._delegate.back()

    def synchronize_radio_state(self) -> bool:
        return self._delegate.synchronize_radio_state()
