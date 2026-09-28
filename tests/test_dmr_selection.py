"""Tests for stable DMR history selection and immutable staging."""

from datetime import UTC, datetime, timedelta

from rolling_thunder.dmr_activity import (
    DmrActivitySource,
    DmrCallIdentity,
    DmrCallSnapshot,
)
from rolling_thunder.dmr_selection import DmrSelectionController, DmrStageOrigin
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


def _history_record(
    callsign: str,
    *,
    seconds: int,
    name: str = "Operator",
) -> WpsdDmrHistoryRecord:
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
        name=name,
        country="USA",
        callsign_suffix=None,
        target="TG 3100",
        duration_s=14.2,
        packet_loss_percent=0.0,
    )


def _active_call() -> DmrCallSnapshot:
    return DmrCallSnapshot(
        identity=DmrCallIdentity(
            started_at=datetime(2026, 8, 16, 0, 7, 8, 120_000, tzinfo=UTC),
            slot=1,
            source=DmrActivitySource.NETWORK,
            callsign="KC9KPJ",
            target="TG 3100",
        ),
        talker_alias="KC9KPJ Michael",
    )


def test_selection_survives_new_history_insertion_by_identity() -> None:
    first = _history_record("KC9KPJ", seconds=0)
    second = _history_record("W3GSI", seconds=-22)
    controller = DmrSelectionController((first, second))

    controller.select_identity(second.identity)
    inserted = _history_record("N9NEW", seconds=15)
    state = controller.replace_history((inserted, first, second))

    assert state.selected_identity == second.identity
    assert state.selected_index == 2
    assert state.selected_record == second


def test_selection_clears_when_identity_falls_out_but_staging_survives() -> None:
    first = _history_record("KC9KPJ", seconds=0)
    second = _history_record("W3GSI", seconds=-22)
    controller = DmrSelectionController((first, second))

    controller.select_identity(second.identity)
    staged = controller.stage_selected(_radio_info()).staged_qso
    assert staged is not None

    state = controller.replace_history((first,))

    assert state.selected_identity is None
    assert state.staged_qso == staged


def test_stage_selected_freezes_history_and_rf_values() -> None:
    record = _history_record("KC9KPJ", seconds=0, name="Michael")
    controller = DmrSelectionController((record,))
    controller.select_identity(record.identity)

    staged = controller.stage_selected(_radio_info()).staged_qso

    assert staged is not None
    assert staged.origin is DmrStageOrigin.HISTORY
    assert staged.identity == record.identity
    assert staged.callsign == "KC9KPJ"
    assert staged.slot == 1
    assert staged.talkgroup == 3100
    assert staged.started_at is None
    assert staged.ended_at == record.occurred_at
    assert staged.name == "Michael"
    assert staged.duration_s == 14.2
    assert staged.radio_rx_hz == 434_537_500
    assert staged.radio_tx_hz == 439_537_500


def test_stage_current_freezes_exact_live_start_alias_and_rf_pair() -> None:
    controller = DmrSelectionController()
    call = _active_call()

    staged = controller.stage_current(call, _radio_info()).staged_qso

    assert staged is not None
    assert staged.origin is DmrStageOrigin.CURRENT_AUDIO
    assert staged.identity == call.identity
    assert staged.callsign == "KC9KPJ"
    assert staged.started_at == call.identity.started_at
    assert staged.ended_at is None
    assert staged.talker_alias == "KC9KPJ Michael"
    assert staged.talkgroup == 3100
    assert staged.radio_rx_hz == 434_537_500
    assert staged.radio_tx_hz == 439_537_500


def test_invalid_stage_request_does_not_erase_existing_staging() -> None:
    record = _history_record("KC9KPJ", seconds=0)
    controller = DmrSelectionController((record,))
    controller.select_identity(record.identity)
    staged = controller.stage_selected(_radio_info()).staged_qso
    assert staged is not None

    controller.clear_selection()
    assert controller.stage_selected(_radio_info()).staged_qso == staged
    assert controller.stage_current(None, _radio_info()).staged_qso == staged
    assert controller.stage_current(_active_call(), None).staged_qso == staged


def test_new_staging_replaces_old_staging_with_new_token() -> None:
    record = _history_record("KC9KPJ", seconds=0)
    controller = DmrSelectionController((record,))
    controller.select_identity(record.identity)
    history_stage = controller.stage_selected(_radio_info()).staged_qso
    assert history_stage is not None

    current_stage = controller.stage_current(_active_call(), _radio_info()).staged_qso

    assert current_stage is not None
    assert current_stage.origin is DmrStageOrigin.CURRENT_AUDIO
    assert current_stage.stage_id != history_stage.stage_id


def test_old_async_commit_cannot_clear_newer_staging() -> None:
    record = _history_record("KC9KPJ", seconds=0)
    controller = DmrSelectionController((record,))
    controller.select_identity(record.identity)
    old_stage = controller.stage_selected(_radio_info()).staged_qso
    assert old_stage is not None

    new_stage = controller.stage_current(_active_call(), _radio_info()).staged_qso
    assert new_stage is not None

    assert controller.complete_commit(old_stage.stage_id).staged_qso == new_stage
    assert controller.complete_commit(new_stage.stage_id).staged_qso is None


def test_encoder_navigation_starts_at_newest_and_does_not_wrap() -> None:
    newest = _history_record("KC9KPJ", seconds=0)
    older = _history_record("W3GSI", seconds=-22)
    oldest = _history_record("KR4MFP", seconds=-77)
    controller = DmrSelectionController((newest, older, oldest))

    assert controller.select_next().selected_record == newest
    assert controller.select_next().selected_record == older
    assert controller.select_next().selected_record == oldest
    assert controller.select_next().selected_record == oldest
    assert controller.select_previous().selected_record == older
