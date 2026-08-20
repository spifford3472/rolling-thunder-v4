"""Tkinter adapter for the vehicle bottom status icon strip and message ticker."""

from __future__ import annotations

from typing import Any

from rolling_thunder.status_monitor import StatusState
from rolling_thunder.status_strip import (
    STATUS_ITEM_ORDER,
    StatusItemId,
    StatusStripSnapshot,
)

STATUS_BAR_HEIGHT_PX = 76
STATUS_ICON_CELL_WIDTH_PX = 76
STATUS_ICON_CANVAS_PX = 68
STATUS_ICON_ORDER = STATUS_ITEM_ORDER

_BACKGROUND = "#202020"
_BORDER = "#3a3a3a"
_HEALTHY = "#42ff72"
_UNAVAILABLE = "#ff3b3b"
_STARTING = "#8a8a8a"


def status_color(state: StatusState) -> str:
    """Return the stable icon color for one health state."""
    return {
        StatusState.STARTING: _STARTING,
        StatusState.HEALTHY: _HEALTHY,
        StatusState.UNAVAILABLE: _UNAVAILABLE,
    }[state]


class StatusBarWidgets:
    """Render equal-width programmatic status icons plus the existing text ticker."""

    def __init__(self, parent: Any) -> None:
        import tkinter as tk

        self.frame = tk.Frame(
            parent,
            bg=_BACKGROUND,
            height=STATUS_BAR_HEIGHT_PX,
        )
        self.frame.grid_propagate(False)
        self.frame.grid_columnconfigure(0, weight=0)
        self.frame.grid_columnconfigure(1, weight=1)
        self.frame.grid_rowconfigure(0, weight=1)

        icon_width = STATUS_ICON_CELL_WIDTH_PX * len(STATUS_ICON_ORDER)
        icon_frame = tk.Frame(
            self.frame,
            bg=_BACKGROUND,
            width=icon_width,
            height=STATUS_BAR_HEIGHT_PX,
        )
        icon_frame.grid(row=0, column=0, sticky="nsw")
        icon_frame.grid_propagate(False)
        icon_frame.grid_rowconfigure(0, weight=1)

        self._canvases: dict[StatusItemId, Any] = {}
        for column, item_id in enumerate(STATUS_ICON_ORDER):
            icon_frame.grid_columnconfigure(
                column,
                weight=1,
                uniform="vehicle-status-icon",
                minsize=STATUS_ICON_CELL_WIDTH_PX,
            )
            cell = tk.Frame(
                icon_frame,
                bg=_BACKGROUND,
                width=STATUS_ICON_CELL_WIDTH_PX,
                height=STATUS_BAR_HEIGHT_PX,
            )
            cell.grid(row=0, column=column, sticky="nsew")
            cell.grid_propagate(False)
            canvas = tk.Canvas(
                cell,
                width=STATUS_ICON_CANVAS_PX,
                height=STATUS_ICON_CANVAS_PX,
                bg=_BACKGROUND,
                highlightthickness=1,
                highlightbackground=_BORDER,
            )
            canvas.place(relx=0.5, rely=0.5, anchor="center")
            self._canvases[item_id] = canvas

        self._ticker_text = tk.StringVar(value="STARTING ROLLING THUNDER")
        self._ticker = tk.Label(
            self.frame,
            textvariable=self._ticker_text,
            bg=_BACKGROUND,
            fg="#ffffff",
            font=("DejaVu Sans", 18, "bold"),
            anchor="w",
            padx=16,
        )
        self._ticker.grid(row=0, column=1, sticky="nsew")
        self._last_snapshot: StatusStripSnapshot | None = None

    def set_message(self, text: str, *, foreground: str) -> None:
        """Update the existing transient/routine ticker region."""
        self._ticker_text.set(text)
        self._ticker.configure(fg=foreground)

    def update_statuses(self, snapshot: StatusStripSnapshot) -> None:
        """Redraw only when one of the four immutable status cells changes."""
        if snapshot == self._last_snapshot:
            return
        self._last_snapshot = snapshot
        states = {item.item_id: item.state for item in snapshot.items}
        for item_id in STATUS_ICON_ORDER:
            self._draw_icon(
                self._canvases[item_id],
                item_id,
                status_color(states[item_id]),
            )

    @staticmethod
    def _draw_icon(canvas: Any, item_id: StatusItemId, color: str) -> None:
        canvas.delete("all")
        if item_id is StatusItemId.HF_RADIO:
            StatusBarWidgets._draw_radio(canvas, color)
        elif item_id is StatusItemId.INTERNET:
            StatusBarWidgets._draw_internet(canvas, color)
        elif item_id is StatusItemId.FORGE:
            StatusBarWidgets._draw_forge(canvas, color)
        else:
            StatusBarWidgets._draw_microphone(canvas, color)

    @staticmethod
    def _draw_radio(canvas: Any, color: str) -> None:
        canvas.create_line(15, 19, 25, 8, width=4, fill=color)
        canvas.create_rectangle(10, 19, 58, 53, width=4, outline=color)
        canvas.create_rectangle(17, 27, 40, 38, width=3, outline=color)
        canvas.create_oval(45, 27, 53, 35, width=3, outline=color)
        canvas.create_line(18, 46, 50, 46, width=3, fill=color)

    @staticmethod
    def _draw_internet(canvas: Any, color: str) -> None:
        canvas.create_oval(9, 9, 59, 59, width=4, outline=color)
        canvas.create_oval(22, 9, 46, 59, width=3, outline=color)
        canvas.create_line(10, 34, 58, 34, width=3, fill=color)
        canvas.create_arc(10, 18, 58, 50, start=0, extent=180, style="arc", width=3, outline=color)
        canvas.create_arc(10, 18, 58, 50, start=180, extent=180, style="arc", width=3, outline=color)

    @staticmethod
    def _draw_forge(canvas: Any, color: str) -> None:
        for top in (11, 28, 45):
            canvas.create_rectangle(10, top, 58, top + 12, width=3, outline=color)
            canvas.create_oval(15, top + 4, 19, top + 8, fill=color, outline=color)
            canvas.create_line(26, top + 6, 50, top + 6, width=3, fill=color)

    @staticmethod
    def _draw_microphone(canvas: Any, color: str) -> None:
        canvas.create_oval(24, 8, 44, 39, width=4, outline=color)
        canvas.create_line(24, 23, 24, 31, width=4, fill=color)
        canvas.create_line(44, 23, 44, 31, width=4, fill=color)
        canvas.create_arc(17, 24, 51, 51, start=180, extent=180, style="arc", width=4, outline=color)
        canvas.create_line(34, 51, 34, 59, width=4, fill=color)
        canvas.create_line(23, 59, 45, 59, width=4, fill=color)
