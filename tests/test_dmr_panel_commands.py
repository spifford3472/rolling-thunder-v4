"""Tests for DMR physical-control command routing."""

from datetime import UTC, datetime, timedelta

from rolling_thunder.dmr_activity import (
    DmrActivitySource,
    DmrCallIdentity,
    DmrCallSnapshot,
)
from rolling_thunder.dmr_monitor import DmrMonitorSnapshot
from rolling_thunder.dmr_panel_commands import DmrPanelCommandController
from rolling_thunder.dmr_selection import (
    DmrSelectionController,
    DmrStageOrigin,
    StagedDmrQso,
)
from rolling_thunder.dmr_wpsd import (
    WpsdDmrHistoryIdentity,
    WpsdDmrHistoryRecord,
    WpsdRadioInfo,
)


def _radio_info() -> WpsdRadioInfo:
    return WpsdRadioInfo(
        status="IDLE",
        mode="Duplex",
        hotspot_tx_hz=434_537_500,
        hotspot_rx_hz=439_537_500,
    )


def _history_record(callsign: str, *, seconds: int) -> WpsdDmrHistoryRecord:
    occurred_at = datetime(2026, 8, 16, 0, 7, 22, tzinfo=UTC) + timedelta(
        seconds=seconds
    )
    return WpsdDmrHistoryRecord(
        identity=WpsdDmrHistoryIdentity(
            occurred_at=occurred_at,
            callsign=callsign,
            slot=1,
            talkgroup=3100,
            source=DmrActivitySource.NETWORK,
        ),
        name="Operator",
        country="USA",
        callsign_suffix=None,
        target="TG 3100",
        duration_s=5.0,
        packet_loss_percent=0.0,
    )


def _active_call(callsign: str = "KC9KPJ", *, slot: int = 1) -> DmrCallSnapshot:
    return DmrCallSnapshot(
        identity=DmrCallIdentity(
            started_at=datetime(2026, 8, 16, 0, 7, 8, tzinfo=UTC),
            slot=slot,
            source=DmrActivitySource.NETWORK,
            callsign=callsign,
            target="TG 3100",
        ),
        talker_alias=f"{callsign} Operator",
    )


class MutableMonitor:
    def __init__(self, snapshot: DmrMonitorSnapshot) -> None:
        self.snapshot = snapshot

    @property
    def latest_state(self) -> DmrMonitorSnapshot:
        return self.snapshot


class RecordingCommit:
    def __init__(self) -> None:
        self.accept = True
        self.calls: list[StagedDmrQso] = []

    def start_commit(self, staged_qso: StagedDmrQso) -> bool:
        self.calls.append(staged_qso)
        return self.accept


def _snapshot(
    *,
    history: tuple[WpsdDmrHistoryRecord, ...] = (),
    active_calls: tuple[DmrCallSnapshot, ...] = (),
    radio_info: WpsdRadioInfo | None = None,
) -> DmrMonitorSnapshot:
    return DmrMonitorSnapshot(
        history=history,
        active_calls=active_calls,
        radio_info=radio_info,
    )


def test_primary_stages_current_audio_with_exact_snapshot_values() -> None:
    monitor = MutableMonitor(
        _snapshot(active_calls=(_active_call(),), radio_info=_radio_info())
    )
    controller = DmrPanelCommandController(
        monitor,
        DmrSelectionController(),
        my_grid_provider=lambda: "EM79xm",
    )

    assert controller.primary()
    staged = controller.state.staged_qso
    assert staged is not None
    assert staged.origin is DmrStageOrigin.CURRENT_AUDIO
    assert staged.callsign == "KC9KPJ"
    assert staged.radio_rx_hz == 434_537_500
    assert staged.radio_tx_hz == 439_537_500
    assert staged.my_grid == "EM79xm"


def test_primary_without_current_audio_preserves_existing_stage() -> None:
    record = _history_record("W3GSI", seconds=0)
    monitor = MutableMonitor(_snapshot(history=(record,), radio_info=_radio_info()))
    selection = DmrSelectionController((record,))
    selection.select_identity(record.identity)
    staged = selection.stage_selected(_radio_info()).staged_qso
    assert staged is not None
    controller = DmrPanelCommandController(monitor, selection)

    assert not controller.primary()
    assert controller.state.staged_qso == staged


def test_encoder_navigation_tracks_identity_when_new_history_arrives() -> None:
    newest = _history_record("KC9KPJ", seconds=0)
    older = _history_record("W3GSI", seconds=-20)
    monitor = MutableMonitor(
        _snapshot(history=(newest, older), radio_info=_radio_info())
    )
    controller = DmrPanelCommandController(monitor, DmrSelectionController())

    assert controller.move_next()
    assert controller.move_next()
    assert controller.state.selected_identity == older.identity

    inserted = _history_record("N9NEW", seconds=10)
    monitor.snapshot = _snapshot(
        history=(inserted, newest, older),
        radio_info=_radio_info(),
    )

    assert controller.refresh().selected_identity == older.identity
    assert controller.state.selected_index == 2
    assert controller.move_previous()
    assert controller.state.selected_identity == newest.identity


def test_encoder_press_stages_selected_history_caller_and_grid() -> None:
    record = _history_record("KR4MFP", seconds=0)
    monitor = MutableMonitor(_snapshot(history=(record,), radio_info=_radio_info()))
    selection = DmrSelectionController()
    grid = "EM79xm"
    controller = DmrPanelCommandController(
        monitor,
        selection,
        my_grid_provider=lambda: grid,
    )

    assert controller.move_next()
    assert controller.activate_selection()
    staged = controller.state.staged_qso
    assert staged is not None
    assert staged.origin is DmrStageOrigin.HISTORY
    assert staged.callsign == "KR4MFP"
    assert staged.my_grid == "EM79xm"

    grid = "EM89lx"
    assert controller.state.staged_qso.my_grid == "EM79xm"


def test_secondary_submits_exact_stage_only_once_without_restage() -> None:
    record = _history_record("KC9KPJ", seconds=0)
    monitor = MutableMonitor(_snapshot(history=(record,), radio_info=_radio_info()))
    selection = DmrSelectionController()
    commit = RecordingCommit()
    controller = DmrPanelCommandController(monitor, selection, commit)

    assert controller.move_next()
    assert controller.activate_selection()
    staged = controller.state.staged_qso
    assert staged is not None

    assert controller.secondary()
    assert not controller.secondary()
    assert commit.calls == [staged]
    assert controller.state.staged_qso == staged


def test_rejected_commit_can_be_attempted_again() -> None:
    record = _history_record("KC9KPJ", seconds=0)
    monitor = MutableMonitor(_snapshot(history=(record,), radio_info=_radio_info()))
    commit = RecordingCommit()
    controller = DmrPanelCommandController(
        monitor,
        DmrSelectionController(),
        commit,
    )

    assert controller.move_next()
    assert controller.activate_selection()
    commit.accept = False
    assert not controller.secondary()
    commit.accept = True
    assert controller.secondary()
    assert len(commit.calls) == 2


def test_async_failed_commit_releases_same_stage_for_retry() -> None:
    record = _history_record("KC9KPJ", seconds=0)
    monitor = MutableMonitor(_snapshot(history=(record,), radio_info=_radio_info()))
    commit = RecordingCommit()
    controller = DmrPanelCommandController(
        monitor,
        DmrSelectionController(),
        commit,
    )

    assert controller.move_next()
    assert controller.activate_selection()
    staged = controller.state.staged_qso
    assert staged is not None
    assert controller.secondary()
    assert not controller.secondary()

    state = controller.fail_commit(staged.stage_id)
    assert state.staged_qso == staged
    assert controller.secondary()
    assert commit.calls == [staged, staged]


def test_success_completion_does_not_clear_newer_restage() -> None:
    history = _history_record("W3GSI", seconds=0)
    monitor = MutableMonitor(_snapshot(history=(history,), radio_info=_radio_info()))
    selection = DmrSelectionController()
    commit = RecordingCommit()
    controller = DmrPanelCommandController(monitor, selection, commit)

    assert controller.move_next()
    assert controller.activate_selection()
    old_stage = controller.state.staged_qso
    assert old_stage is not None
    assert controller.secondary()

    monitor.snapshot = _snapshot(
        history=(history,),
        active_calls=(_active_call("KC9KPJ"),),
        radio_info=_radio_info(),
    )
    assert controller.primary()
    new_stage = controller.state.staged_qso
    assert new_stage is not None
    assert new_stage.stage_id != old_stage.stage_id

    controller.complete_commit(old_stage.stage_id)
    assert controller.state.staged_qso == new_stage


def test_back_cancels_stage_before_clearing_selection() -> None:
    record = _history_record("KC9KPJ", seconds=0)
    monitor = MutableMonitor(_snapshot(history=(record,), radio_info=_radio_info()))
    controller = DmrPanelCommandController(monitor, DmrSelectionController())

    assert controller.move_next()
    assert controller.activate_selection()
    assert controller.back()
    assert controller.state.staged_qso is None
    assert controller.state.selected_identity == record.identity
    assert controller.back()
    assert controller.state.selected_identity is None
    assert not controller.back()
