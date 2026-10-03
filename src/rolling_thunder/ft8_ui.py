"""Presentation model for the mobile-readable FT8 CQ browser."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from rolling_thunder.ft8.domain import FT8CQActivity

FT8_BROWSER_HEADERS = ("CALL", "SNR", "AUDIO", "GRID")
FT8_POTA_TREE_GLYPH = "🌲"


class FT8CallPresentation(StrEnum):
    """Lifecycle presentation independent of Tk colors."""

    WHITE = "white"
    GRAY = "gray"
    YELLOW = "yellow"


@dataclass(frozen=True, slots=True)
class FT8BrowserRow:
    callsign: str
    call_text: str
    pota_cq: bool
    snr_text: str
    audio_text: str
    grid_text: str
    selected: bool
    call_presentation: FT8CallPresentation


@dataclass(frozen=True, slots=True)
class FT8BrowserViewport:
    headers: tuple[str, str, str, str]
    rows: tuple[FT8BrowserRow, ...]
    hidden_above: int = 0
    hidden_below: int = 0


def build_ft8_browser_viewport(
    activity: tuple[FT8CQActivity, ...],
    *,
    selected_callsign: str | None,
    visible_rows: int = 5,
) -> FT8BrowserViewport:
    """Build a stable-order viewport that always keeps selection visible."""
    if visible_rows < 1:
        raise ValueError("visible_rows must be at least 1")

    start = 0
    if len(activity) > visible_rows and selected_callsign is not None:
        callsigns = tuple(item.callsign for item in activity)
        try:
            selected_index = callsigns.index(selected_callsign)
        except ValueError:
            selected_index = 0
        start = max(0, selected_index - visible_rows + 1)

    visible = activity[start : start + visible_rows]
    rows = tuple(
        _row(item, selected=item.callsign == selected_callsign)
        for item in visible
    )
    return FT8BrowserViewport(
        headers=FT8_BROWSER_HEADERS,
        rows=rows,
        hidden_above=start,
        hidden_below=max(0, len(activity) - (start + len(visible))),
    )


def _row(activity: FT8CQActivity, *, selected: bool) -> FT8BrowserRow:
    if activity.active_non_cq:
        presentation = FT8CallPresentation.YELLOW
    elif activity.cq_count >= 3:
        presentation = FT8CallPresentation.GRAY
    else:
        presentation = FT8CallPresentation.WHITE

    return FT8BrowserRow(
        callsign=activity.callsign,
        call_text=activity.callsign,
        pota_cq=activity.pota_cq,
        snr_text=f"{activity.snr_db:+d}",
        audio_text=str(activity.audio_frequency_hz),
        grid_text=activity.grid or "------",
        selected=selected,
        call_presentation=presentation,
    )
