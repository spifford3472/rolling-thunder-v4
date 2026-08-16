"""Tests for the bounded read-only DMR hotspot panel presentation."""

from datetime import UTC, datetime, timedelta

import pytest

from rolling_thunder.dmr_activity import (
    DmrActivitySource,
    DmrCallIdentity,
    DmrCallSnapshot,
)
from rolling_thunder.dmr_commit import DmrCommitStatus
from rolling_thunder.dmr_monitor import DmrMonitorHealth, DmrMonitorSnapshot
from rolling_thunder.dmr_selection import DmrSelectionController
from rolling_thunder.dmr_ui import build_dmr_viewport
from rolling_thunder.dmr_wpsd import (
    WpsdDmrHistoryIdentity,
    WpsdDmrHistoryRecord,
    WpsdRadioInfo,
)
from rolling_thunder.domain import Contact, RadioMode

NOW = datetime(2026, 8, 16, 0, 7, 22, tzinfo=UTC)


def _radio_info() -> WpsdRadioInfo:
    return WpsdRadioInfo(
        status="IDLE",
        mode="Duplex",
        hotspot_tx_hz=434_537_500,
        hotspot_rx_hz=439_537_500,
    )


def _history_record(index: int, *, callsign: str | None = None) -> WpsdDmrHistoryRecord:
    occurred_at = NOW - timedelta(seconds=index * 20)
    normalized_callsign = callsign or f"K{index}DMR"
    identity = WpsdDmrHistoryIdentity(
        occurred_at=occurred_at,
        callsign=normalized_callsign,
        slot=1 if index % 2 == 0 else 2,
        talkgroup=3100,
        source=DmrActivitySource.NETWORK,
    )
    return WpsdDmrHistoryRecord(
        identity=identity,
        name=f"Operator {index}",
        country="USA",
        callsign_suffix=None,
        target="TG 3100",
        duration_s=5.0 + index,
        packet_loss_percent=0.0,
    )


def _active_call(
    callsign: str = "KC9KPJ",
    *,
    slot: int = 1,
    alias: str | None = "KC9KPJ Michael",
) -> DmrCallSnapshot:
    return DmrCallSnapshot(
        identity=DmrCallIdentity(
            started_at=NOW - timedelta(seconds=14),
            slot=slot,
            source=DmrActivitySource.NETWORK,
            callsign=callsign,
            target="TG 3100",
        ),
        talker_alias=alias,
    )


def _monitor(
    *,
    history: tuple[WpsdDmrHistoryRecord, ...] = (),
    active_calls: tuple[DmrCallSnapshot, ...] = (),
    radio_info: WpsdRadioInfo | None = None,
    health: DmrMonitorHealth = DmrMonitorHealth.HEALTHY,
    live_available: bool = True,
    history_available: bool = True,
    radio_available: bool = True,
    live_error: str | None = None,
    history_error: str | None = None,
    radio_error: str | None = None,
) -> DmrMonitorSnapshot:
    return DmrMonitorSnapshot(
        active_calls=active_calls,
        history=history,
        radio_info=radio_info,
        live_available=live_available,
        history_available=history_available,
        radio_available=radio_available,
        health=health,
        updated_at=NOW,
        live_error=live_error,
        history_error=history_error,
        radio_error=radio_error,
    )


def test_healthy_idle_view_shows_rf_pair_and_bounded_history() -> None:
    history = tuple(_history_record(index) for index in range(20))
    selection = DmrSelectionController(history)

    viewport = build_dmr_viewport(
        _monitor(history=history, radio_info=_radio_info()),
        selection.state,
        DmrCommitStatus(),
    )

    assert viewport.title == "DMR HOTSPOT"
    assert viewport.health_line == "HEALTHY  LIVE OK  HISTORY OK  RF OK"
    assert viewport.rf_line == "RX 434.5375 MHz  TX 439.5375 MHz  DUPLEX"
    assert viewport.current_audio_idle
    assert len(viewport.history_cards) == 4
    assert viewport.hidden_above_count == 0
    assert viewport.hidden_below_count == 16
    assert viewport.history_cards[0].callsign_line == "K0DMR - Operator 0"


def test_current_audio_supports_both_slots_and_marks_staged_call() -> None:
    slot_two = _active_call("W3GSI", slot=2, alias="W3GSI Raymond")
    slot_one = _active_call()
    selection = DmrSelectionController()
    selection.stage_current(slot_two, _radio_info(), my_grid="EM79xm")

    viewport = build_dmr_viewport(
        _monitor(
            active_calls=(slot_two, slot_one),
            radio_info=_radio_info(),
        ),
        selection.state,
        DmrCommitStatus(),
    )

    assert not viewport.current_audio_idle
    assert [card.callsign_line for card in viewport.current_audio_cards] == [
        "KC9KPJ",
        "W3GSI",
    ]
    assert viewport.current_audio_cards[0].staged is False
    assert viewport.current_audio_cards[1].staged is True
    assert viewport.current_audio_cards[1].alias_line == "W3GSI Raymond"
    assert viewport.current_audio_cards[1].detail_line == "TS2  TG 3100  NETWORK"


def test_selected_history_is_kept_inside_four_row_window() -> None:
    history = tuple(_history_record(index) for index in range(10))
    selection = DmrSelectionController(history)
    selection.select_identity(history[7].identity)

    viewport = build_dmr_viewport(
        _monitor(history=history, radio_info=_radio_info()),
        selection.state,
        DmrCommitStatus(),
    )

    assert len(viewport.history_cards) == 4
    assert viewport.hidden_above_count == 4
    assert viewport.hidden_below_count == 2
    assert viewport.history_cards[-1].selected
    assert viewport.history_cards[-1].callsign_line.startswith("K7DMR")


def test_staged_history_row_and_footer_are_explicit() -> None:
    history = (_history_record(0, callsign="KC9KPJ"),)
    selection = DmrSelectionController(history)
    selection.select_identity(history[0].identity)
    selection.stage_selected(_radio_info(), my_grid="EM79xm")

    viewport = build_dmr_viewport(
        _monitor(history=history, radio_info=_radio_info()),
        selection.state,
        DmrCommitStatus(),
    )

    assert viewport.history_cards[0].selected
    assert viewport.history_cards[0].staged
    assert "STAGED KC9KPJ" in viewport.stage_line
    assert "TS1 TG3100" in viewport.stage_line
    assert "BTN2 COMMIT" in viewport.stage_line
    assert "BACK CANCEL" in viewport.stage_line


def test_unstaged_footer_explains_physical_controls() -> None:
    viewport = build_dmr_viewport(
        _monitor(radio_info=_radio_info()),
        DmrSelectionController().state,
        DmrCommitStatus(),
    )

    assert viewport.stage_line == (
        "BTN1 STAGE CURRENT  •  ENCODER SELECT  •  PRESS STAGE HISTORY"
    )


def test_degraded_sources_surface_each_error_without_hiding_cached_rf() -> None:
    viewport = build_dmr_viewport(
        _monitor(
            radio_info=_radio_info(),
            health=DmrMonitorHealth.DEGRADED,
            live_available=False,
            history_available=False,
            live_error="ssh disconnected",
            history_error="WPSD timeout",
        ),
        DmrSelectionController().state,
        DmrCommitStatus(),
    )

    assert viewport.health_line == "DEGRADED  LIVE DOWN  HISTORY DOWN  RF OK"
    assert viewport.error_line == "LIVE: ssh disconnected  |  HISTORY: WPSD timeout"
    assert viewport.rf_line == "RX 434.5375 MHz  TX 439.5375 MHz  DUPLEX"


def test_unavailable_rf_is_truthful() -> None:
    viewport = build_dmr_viewport(
        _monitor(
            radio_info=None,
            health=DmrMonitorHealth.DEGRADED,
            radio_available=False,
            radio_error="radioinfo unavailable",
        ),
        DmrSelectionController().state,
        DmrCommitStatus(),
    )

    assert viewport.rf_line == "RF INFORMATION UNAVAILABLE"
    assert "RF DOWN" in viewport.health_line
    assert "RF: radioinfo unavailable" in viewport.error_line


def test_commit_status_distinguishes_active_failure_and_success() -> None:
    selection = DmrSelectionController().state
    monitor = _monitor(radio_info=_radio_info())

    committing = build_dmr_viewport(
        monitor,
        selection,
        DmrCommitStatus(committing=True),
    )
    failed = build_dmr_viewport(
        monitor,
        selection,
        DmrCommitStatus(last_error="disk full"),
    )
    contact = Contact(
        callsign="KC9KPJ",
        frequency_hz=439_537_500,
        mode=RadioMode.DMR,
        started_at=NOW,
        rst_sent="59",
        rst_received="59",
    )
    succeeded = build_dmr_viewport(
        monitor,
        selection,
        DmrCommitStatus(committed_contact=contact),
    )

    assert committing.commit_line == "COMMITTING STAGED DMR QSO"
    assert failed.commit_line == "COMMIT FAILED: disk full"
    assert succeeded.commit_line == "LOGGED KC9KPJ"


def test_history_row_limit_must_be_positive() -> None:
    with pytest.raises(ValueError, match="positive"):
        build_dmr_viewport(
            _monitor(radio_info=_radio_info()),
            DmrSelectionController().state,
            DmrCommitStatus(),
            max_history_rows=0,
        )
