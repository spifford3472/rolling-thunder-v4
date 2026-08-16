"""Stable DMR history selection and immutable QSO staging."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from rolling_thunder.dmr_activity import (
    DmrActivitySource,
    DmrCallIdentity,
    DmrCallSnapshot,
)
from rolling_thunder.dmr_wpsd import (
    WpsdDmrHistoryIdentity,
    WpsdDmrHistoryRecord,
    WpsdRadioInfo,
)
from rolling_thunder.value_types import MaidenheadGrid

_TALKGROUP = re.compile(r"\bTG\s+(?P<talkgroup>\d+)\b", re.IGNORECASE)


class DmrStageOrigin(StrEnum):
    """Where an immutable staged DMR QSO was selected."""

    CURRENT_AUDIO = "current_audio"
    HISTORY = "history"


DmrStageIdentity = DmrCallIdentity | WpsdDmrHistoryIdentity


@dataclass(frozen=True, slots=True)
class StagedDmrQso:
    """Immutable DMR QSO values captured before an explicit commit."""

    origin: DmrStageOrigin
    identity: DmrStageIdentity
    callsign: str
    slot: int
    target: str
    talkgroup: int | None
    source: DmrActivitySource
    started_at: datetime | None
    ended_at: datetime | None
    name: str | None
    country: str | None
    talker_alias: str | None
    duration_s: float | None
    packet_loss_percent: float | None
    ber_percent: float | None
    radio_rx_hz: int
    radio_tx_hz: int
    my_grid: MaidenheadGrid | None = None
    stage_id: UUID = field(default_factory=uuid4)

    @classmethod
    def from_current_audio(
        cls,
        call: DmrCallSnapshot,
        radio_info: WpsdRadioInfo,
        *,
        my_grid: MaidenheadGrid | None = None,
    ) -> StagedDmrQso:
        """Freeze the exact currently active DMR caller, RF pair, and operator grid."""
        identity = call.identity
        return cls(
            origin=DmrStageOrigin.CURRENT_AUDIO,
            identity=identity,
            callsign=identity.callsign,
            slot=identity.slot,
            target=identity.target,
            talkgroup=_talkgroup_from_target(identity.target),
            source=identity.source,
            started_at=identity.started_at,
            ended_at=call.ended_at,
            name=None,
            country=None,
            talker_alias=call.talker_alias,
            duration_s=call.duration_s,
            packet_loss_percent=call.packet_loss_percent,
            ber_percent=call.ber_percent,
            radio_rx_hz=radio_info.radio_rx_hz,
            radio_tx_hz=radio_info.radio_tx_hz,
            my_grid=my_grid,
        )

    @classmethod
    def from_history(
        cls,
        record: WpsdDmrHistoryRecord,
        radio_info: WpsdRadioInfo,
        *,
        my_grid: MaidenheadGrid | None = None,
    ) -> StagedDmrQso:
        """Freeze one completed WPSD history row, RF pair, and operator grid."""
        return cls(
            origin=DmrStageOrigin.HISTORY,
            identity=record.identity,
            callsign=record.callsign,
            slot=record.slot,
            target=record.target,
            talkgroup=record.talkgroup,
            source=record.source,
            started_at=None,
            ended_at=record.occurred_at,
            name=record.name,
            country=record.country,
            talker_alias=None,
            duration_s=record.duration_s,
            packet_loss_percent=record.packet_loss_percent,
            ber_percent=None,
            radio_rx_hz=radio_info.radio_rx_hz,
            radio_tx_hz=radio_info.radio_tx_hz,
            my_grid=my_grid,
        )


def _talkgroup_from_target(target: str) -> int | None:
    match = _TALKGROUP.search(target)
    if match is None:
        return None
    return int(match.group("talkgroup"))


@dataclass(frozen=True, slots=True)
class DmrSelectionState:
    """Immutable history-selection and staging state for the DMR panel."""

    history: tuple[WpsdDmrHistoryRecord, ...]
    selected_identity: WpsdDmrHistoryIdentity | None = None
    staged_qso: StagedDmrQso | None = None

    @property
    def selected_index(self) -> int | None:
        """Return the selected caller's current history index."""
        if self.selected_identity is None:
            return None
        for index, record in enumerate(self.history):
            if record.identity == self.selected_identity:
                return index
        return None

    @property
    def selected_record(self) -> WpsdDmrHistoryRecord | None:
        """Return the selected history record by stable identity."""
        index = self.selected_index
        if index is None:
            return None
        return self.history[index]


class DmrSelectionController:
    """Preserve caller selection while keeping staged QSO values immutable."""

    def __init__(self, history: tuple[WpsdDmrHistoryRecord, ...] = ()) -> None:
        self._history = history
        self._selected_identity: WpsdDmrHistoryIdentity | None = None
        self._staged_qso: StagedDmrQso | None = None

    @property
    def state(self) -> DmrSelectionState:
        """Return the current immutable selection/staging state."""
        return DmrSelectionState(
            history=self._history,
            selected_identity=self._selected_identity,
            staged_qso=self._staged_qso,
        )

    def replace_history(
        self,
        history: tuple[WpsdDmrHistoryRecord, ...],
    ) -> DmrSelectionState:
        """Replace history while preserving any still-present selected identity."""
        self._history = history
        selected = self._selected_identity
        if selected is not None and not any(
            record.identity == selected for record in history
        ):
            self._selected_identity = None
        return self.state

    def select_identity(self, identity: WpsdDmrHistoryIdentity) -> DmrSelectionState:
        """Select one present history identity without changing existing staging."""
        if any(record.identity == identity for record in self._history):
            self._selected_identity = identity
        else:
            self._selected_identity = None
        return self.state

    def select_next(self) -> DmrSelectionState:
        """Move toward older entries without wrapping."""
        if not self._history:
            self._selected_identity = None
            return self.state

        current_index = self.state.selected_index
        target_index = (
            0
            if current_index is None
            else min(current_index + 1, len(self._history) - 1)
        )
        self._selected_identity = self._history[target_index].identity
        return self.state

    def select_previous(self) -> DmrSelectionState:
        """Move toward newer entries without wrapping."""
        if not self._history:
            self._selected_identity = None
            return self.state

        current_index = self.state.selected_index
        target_index = 0 if current_index is None else max(0, current_index - 1)
        self._selected_identity = self._history[target_index].identity
        return self.state

    def clear_selection(self) -> DmrSelectionState:
        """Clear only the highlighted history row, leaving staging untouched."""
        self._selected_identity = None
        return self.state

    def stage_selected(
        self,
        radio_info: WpsdRadioInfo | None,
        *,
        my_grid: MaidenheadGrid | None = None,
    ) -> DmrSelectionState:
        """Stage the selected completed caller when RF information is available."""
        record = self.state.selected_record
        if record is not None and radio_info is not None:
            self._staged_qso = StagedDmrQso.from_history(
                record,
                radio_info,
                my_grid=my_grid,
            )
        return self.state

    def stage_current(
        self,
        call: DmrCallSnapshot | None,
        radio_info: WpsdRadioInfo | None,
        *,
        my_grid: MaidenheadGrid | None = None,
    ) -> DmrSelectionState:
        """Stage the exact active caller when both caller and RF pair are known."""
        if call is not None and radio_info is not None:
            self._staged_qso = StagedDmrQso.from_current_audio(
                call,
                radio_info,
                my_grid=my_grid,
            )
        return self.state

    def cancel_staging(self) -> DmrSelectionState:
        """Explicitly discard the currently staged DMR QSO."""
        self._staged_qso = None
        return self.state

    def complete_commit(self, stage_id: UUID) -> DmrSelectionState:
        """Clear only the staging token that actually completed persistence."""
        staged = self._staged_qso
        if staged is not None and staged.stage_id == stage_id:
            self._staged_qso = None
        return self.state
