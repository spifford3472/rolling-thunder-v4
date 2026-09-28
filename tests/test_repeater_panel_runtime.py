"""Tests for startup-only repeater source/persistence composition."""

from datetime import UTC, datetime
from pathlib import Path

from rolling_thunder.domain import GPSFixState, GPSPosition
from rolling_thunder.gps import GPSConnectionState, GPSState
from rolling_thunder.repeater_csv import EXPECTED_REPEATER_CSV_HEADERS
from rolling_thunder.repeater_panel import RepeaterDisplayFilter
from rolling_thunder.repeater_panel_runtime import RepeaterPanelRuntime

NOW = datetime(2026, 8, 9, 21, 30, tzinfo=UTC)


def gps_state() -> GPSState:
    return GPSState(
        connection_state=GPSConnectionState.CONNECTED,
        position=GPSPosition(
            fix_state=GPSFixState.THREE_DIMENSIONAL,
            latitude=39.5,
            longitude=-84.0,
            updated_at=NOW,
        ),
        updated_at=NOW,
    )


def write_source(path: Path) -> None:
    header = ",".join(EXPECTED_REPEATER_CSV_HEADERS)
    row = "K1AAA Alpha,Analogue,52.01,51.01,25,100.0,100.0,39.5,-84.0,6,Yes"
    path.write_text(f"{header}\n{row}\n", encoding="utf-8")


def test_confirmed_background_result_updates_effective_active_without_csv_write(tmp_path: Path) -> None:
    source = tmp_path / "6m_repeaters.csv"
    write_source(source)
    before = source.read_bytes()
    runtime = RepeaterPanelRuntime.build(
        database_path=tmp_path / "rolling-thunder.db",
        gps_state=gps_state,
        source_path=source,
        clock=lambda: NOW,
        worker_launcher=lambda worker: worker(),
    )
    runtime.panel.toggle_filter()
    assert runtime.panel.display_filter is RepeaterDisplayFilter.ALL
    runtime.panel.select_next()
    staged = runtime.panel.stage_selected().staged_action
    assert staged is not None
    assert runtime.persistence is not None

    assert runtime.persistence.start_persist(staged) is True
    runtime.synchronize_completed_persistence()

    state = runtime.panel.state
    assert len(state.rows) == 1
    assert state.rows[0].effective_active is False
    assert source.read_bytes() == before


def test_missing_local_source_is_truthfully_unavailable_without_crashing_panel(tmp_path: Path) -> None:
    runtime = RepeaterPanelRuntime.build(
        database_path=tmp_path / "rolling-thunder.db",
        gps_state=gps_state,
        source_path=tmp_path / "missing.csv",
        clock=lambda: NOW,
        worker_launcher=lambda worker: worker(),
    )

    state = runtime.panel.state

    assert state.rows == ()
    assert state.source_error is not None
    assert "REPEATER DATA UNAVAILABLE" in state.source_error
