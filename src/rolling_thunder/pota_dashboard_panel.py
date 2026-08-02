"""Bounded scrolling presentation model for the Tkinter POTA panel."""

from dataclasses import dataclass

from rolling_thunder.pota_dashboard_state import PotaDashboardState, PotaSpotRow

_DEFAULT_MAX_ROWS = 3


@dataclass(frozen=True)
class PotaDashboardPanel:
    """Compact values consumed by the lower-left POTA panel widgets."""

    status_line: str
    detail_line: str
    refresh_line: str
    error_line: str
    rows: tuple[PotaSpotRow, ...]
    hidden_above_count: int
    hidden_below_count: int

    @property
    def hidden_row_count(self) -> int:
        """Return the total number of rows outside the current viewport."""
        return self.hidden_above_count + self.hidden_below_count


def build_pota_dashboard_panel(
    state: PotaDashboardState,
    *,
    max_rows: int = _DEFAULT_MAX_ROWS,
) -> PotaDashboardPanel:
    """Keep the selected row inside a compact scrolling viewport."""
    if max_rows < 1:
        raise ValueError("POTA dashboard panel row limit must be positive.")

    total_rows = len(state.rows)
    selected_index = state.selected_index
    if selected_index is None:
        start_index = 0
    else:
        start_index = max(0, selected_index - max_rows + 1)
        start_index = min(start_index, max(0, total_rows - max_rows))

    end_index = min(total_rows, start_index + max_rows)
    visible_rows = state.rows[start_index:end_index]
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
        hidden_above_count=start_index,
        hidden_below_count=max(0, total_rows - end_index),
    )
