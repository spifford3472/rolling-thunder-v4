"""No-I/O command routing for the DMR dashboard panel."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from rolling_thunder.dmr_monitor import DmrMonitorSnapshot
from rolling_thunder.dmr_selection import (
    DmrSelectionController,
    DmrSelectionState,
    StagedDmrQso,
)


class DmrMonitorStateProvider(Protocol):
    """Synchronous snapshot boundary; implementations must perform no I/O here."""

    @property
    def latest_state(self) -> DmrMonitorSnapshot:
        """Return the latest immutable background-produced DMR snapshot."""
        ...


class DmrCommitCommands(Protocol):
    """Asynchronous persistence boundary reached only by Context Button #2."""

    def start_commit(self, staged_qso: StagedDmrQso) -> bool:
        """Accept one immutable staged QSO for background persistence."""
        ...


class DmrPanelCommandController:
    """Map generic physical controls onto DMR selection, staging, and commit intent."""

    def __init__(
        self,
        monitor: DmrMonitorStateProvider,
        selection: DmrSelectionController,
        commit: DmrCommitCommands | None = None,
    ) -> None:
        self._monitor = monitor
        self._selection = selection
        self._commit = commit
        self._submitted_stage_ids: set[UUID] = set()

    @property
    def state(self) -> DmrSelectionState:
        """Return selection/staging state without performing external I/O."""
        return self._selection.state

    def refresh(self) -> DmrSelectionState:
        """Apply the latest background history snapshot while preserving stable identity."""
        snapshot = self._monitor.latest_state
        return self._selection.replace_history(snapshot.history)

    def primary(self) -> bool:
        """Context Button #1 stages the currently active DMR caller."""
        snapshot = self._monitor.latest_state
        self._selection.replace_history(snapshot.history)
        active = snapshot.active_calls[0] if snapshot.active_calls else None
        before = self._selection.state.staged_qso
        state = self._selection.stage_current(active, snapshot.radio_info)
        return state.staged_qso is not None and state.staged_qso is not before

    def secondary(self) -> bool:
        """Context Button #2 submits the current immutable stage at most once."""
        self.refresh()
        staged = self._selection.state.staged_qso
        commit = self._commit
        if staged is None or commit is None:
            return False
        if staged.stage_id in self._submitted_stage_ids:
            return False
        if not commit.start_commit(staged):
            return False
        self._submitted_stage_ids.add(staged.stage_id)
        return True

    def tertiary(self) -> bool:
        """DMR currently has no tertiary button action."""
        return False

    def tertiary_long(self) -> bool:
        """DMR currently has no tertiary-long button action."""
        return False

    def move_previous(self) -> bool:
        """Encoder counter-clockwise moves toward newer history entries."""
        self.refresh()
        before = self._selection.state.selected_identity
        state = self._selection.select_previous()
        return state.selected_identity != before

    def move_next(self) -> bool:
        """Encoder clockwise moves toward older history entries."""
        self.refresh()
        before = self._selection.state.selected_identity
        state = self._selection.select_next()
        return state.selected_identity != before

    def activate_selection(self) -> bool:
        """Encoder press stages the selected completed history caller."""
        snapshot = self._monitor.latest_state
        self._selection.replace_history(snapshot.history)
        before = self._selection.state.staged_qso
        state = self._selection.stage_selected(snapshot.radio_info)
        return state.staged_qso is not None and state.staged_qso is not before

    def back(self) -> bool:
        """Back cancels staging first, then clears history selection."""
        state = self._selection.state
        if state.staged_qso is not None:
            self._selection.cancel_staging()
            return True
        if state.selected_identity is not None:
            self._selection.clear_selection()
            return True
        return False

    def complete_commit(self, stage_id: UUID) -> DmrSelectionState:
        """Acknowledge successful persistence without clearing a newer staged QSO."""
        self._submitted_stage_ids.discard(stage_id)
        return self._selection.complete_commit(stage_id)
