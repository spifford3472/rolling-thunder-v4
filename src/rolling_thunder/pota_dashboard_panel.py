"""Bounded read-only presentation model for the future Tkinter POTA panel."""

from dataclasses import dataclass

from rolling_thunder.pota_dashboard_state import PotaDashboardState, PotaSpotRow

_DEFAULT_MAX_ROWS = 6


@dataclass(frozen=True)
class PotaDashboardPanel:
    """Compact values consumed by the lower-left POTA panel widgets."""

    status_line: str
    detail_line: str
    refresh_line: str
    error_line: str
    rows: tuple[PotaSpotRow, ...]
    hidden_row_count: int


def build_pota_dashboard_panel(
    state: PotaDashboardState,
    *,
    max_rows: int = _DEFAULT_MAX_ROWS,
) -> PotaDashboardPanel:
    """Bound one immutable dashboard snapshot for compact read-only rendering."""
    if max_rows < 1:
        raise ValueError("POTA dashboard panel row limit must be positive.")

    visible_rows = state.rows[:max_rows]
    hidden_row_count = max(0, len(state.rows) - len(visible_rows))
    count_text = f"{state.visible_spot_count}/{state.total_spot_count}"
    stale_suffix = " — STALE" if state.is_stale else ""
    status_line = f"{state.status} — {count_text} SPOTS{stale_suffix}"
    refresh_line = f"LAST REFRESH {state.last_refresh}"
    error_line = f"ERROR: {state.error}" if state.error else ""

    return PotaDashboardPanel(
        status_line=status_line,
        detail_line=state.detail,
        refresh_line=refresh_line,
        error_line=error_line,
        rows=visible_rows,
        hidden_row_count=hidden_row_count,
    )
