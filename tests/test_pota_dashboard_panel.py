"""Tests for bounded read-only POTA panel presentation."""

import pytest

from rolling_thunder.pota_dashboard_panel import build_pota_dashboard_panel
from rolling_thunder.pota_dashboard_state import PotaDashboardState, PotaSpotRow


def row(index: int) -> PotaSpotRow:
    return PotaSpotRow(
        activator=f"W8{index}",
        park_reference=f"US-{index:04d}",
        park_name=f"Park {index}",
        frequency="14.250 MHz",
        mode="USB",
        spotted_at="2026-07-26 12:30 UTC",
        comments="",
        is_selected=False,
    )


def state(*, rows: tuple[PotaSpotRow, ...] = (), stale: bool = False) -> PotaDashboardState:
    return PotaDashboardState(
        status="STALE" if stale else "READY",
        detail="SHOWING SPOTS",
        availability="UNAVAILABLE" if stale else "AVAILABLE",
        is_stale=stale,
        last_refresh="2026-07-26 12:30 UTC",
        error="request timed out" if stale else "",
        total_spot_count=len(rows),
        visible_spot_count=len(rows),
        rows=rows,
    )


def test_panel_exposes_compact_status_and_refresh_text() -> None:
    panel = build_pota_dashboard_panel(state(rows=(row(1), row(2))))

    assert panel.status_line == "READY — 2/2 SPOTS"
    assert panel.detail_line == "SHOWING SPOTS"
    assert panel.refresh_line == "LAST REFRESH 2026-07-26 12:30 UTC"
    assert panel.error_line == ""


def test_panel_marks_stale_data_and_surfaces_error() -> None:
    panel = build_pota_dashboard_panel(state(rows=(row(1),), stale=True))

    assert panel.status_line == "STALE — 1/1 SPOTS — STALE"
    assert panel.error_line == "ERROR: request timed out"


def test_panel_bounds_rows_and_reports_hidden_count() -> None:
    rows = tuple(row(index) for index in range(1, 9))

    panel = build_pota_dashboard_panel(state(rows=rows), max_rows=6)

    assert panel.rows == rows[:6]
    assert panel.hidden_row_count == 2


def test_panel_preserves_empty_and_disabled_snapshots() -> None:
    disabled = PotaDashboardState(
        status="DISABLED",
        detail="POTA SPOTS DISABLED",
        availability="DISABLED",
        is_stale=False,
        last_refresh="—",
        error="",
        total_spot_count=0,
        visible_spot_count=0,
        rows=(),
    )

    panel = build_pota_dashboard_panel(disabled)

    assert panel.status_line == "DISABLED — 0/0 SPOTS"
    assert panel.rows == ()
    assert panel.hidden_row_count == 0


@pytest.mark.parametrize("max_rows", [0, -1])
def test_panel_requires_positive_row_limit(max_rows: int) -> None:
    with pytest.raises(ValueError, match="row limit must be positive"):
        build_pota_dashboard_panel(state(), max_rows=max_rows)
