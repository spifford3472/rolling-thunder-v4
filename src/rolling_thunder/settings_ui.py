"""Tkinter Settings-page widgets with no application or network I/O."""

from __future__ import annotations

from typing import Any

from rolling_thunder.settings_panel import DashboardSettingsState

_BACKGROUND = "#151515"
_PANEL_BACKGROUND = "#101010"
_BORDER = "#303030"
_BRIGHT = "#ffffff"
_MUTED = "#a8a8a8"
_DISABLED = "#777777"
_HEALTHY = "#66ccff"


class SettingsWidgets:
    """Render map zoom and the Context Button #1 radar-image switch."""

    def __init__(self, parent: Any) -> None:
        import tkinter as tk

        self._tk = tk
        self.frame = tk.Frame(parent, bg=_BACKGROUND)
        self.frame.grid(row=1, column=0, sticky="nsew")
        self.frame.grid_columnconfigure(0, weight=1)
        self.frame.grid_rowconfigure(0, weight=1)
        self.frame.grid_remove()

        content = tk.Frame(self.frame, bg=_BACKGROUND)
        content.grid(row=0, column=0, sticky="new", padx=18, pady=(12, 4))
        content.grid_columnconfigure(0, weight=1)

        self._zoom_text = tk.StringVar(value="MAP ZOOM\nDISABLED")
        tk.Label(
            content,
            textvariable=self._zoom_text,
            bg=_BACKGROUND,
            fg=_BRIGHT,
            font=("DejaVu Sans Mono", 26, "bold"),
            justify="left",
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", pady=(0, 18))

        radar_card = tk.Frame(
            content,
            bg=_PANEL_BACKGROUND,
            highlightthickness=2,
            highlightbackground=_BORDER,
        )
        radar_card.grid(row=1, column=0, sticky="ew", pady=(2, 0))
        radar_card.grid_columnconfigure(0, weight=1)

        tk.Label(
            radar_card,
            text="RADAR Image",
            bg=_PANEL_BACKGROUND,
            fg=_BRIGHT,
            font=("DejaVu Sans", 28, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=(18, 8), pady=(13, 0))

        tk.Label(
            radar_card,
            text="Context Button #1",
            bg=_PANEL_BACKGROUND,
            fg=_MUTED,
            font=("DejaVu Sans", 15),
            anchor="w",
        ).grid(row=1, column=0, sticky="w", padx=(18, 8), pady=(0, 13))

        self._switch = tk.Canvas(
            radar_card,
            width=92,
            height=46,
            bg=_PANEL_BACKGROUND,
            highlightthickness=0,
        )
        self._switch.grid(row=0, column=1, rowspan=2, padx=(8, 18), pady=10)
        self._draw_switch(enabled=False, available=False)

    def show(self) -> None:
        """Show the Settings viewport."""
        self.frame.grid()

    def hide(self) -> None:
        """Hide the Settings viewport."""
        self.frame.grid_remove()

    def update(self, state: DashboardSettingsState) -> None:
        """Update immutable Settings state without application I/O."""
        if state.map_zoom is None:
            self._zoom_text.set("MAP ZOOM\nDISABLED")
        else:
            self._zoom_text.set("\n".join(state.map_zoom.lines))
        self._draw_switch(
            enabled=state.radar_image_enabled,
            available=state.radar_available,
        )

    def _draw_switch(self, *, enabled: bool, available: bool) -> None:
        canvas = self._switch
        canvas.delete("all")
        track = _HEALTHY if enabled and available else _DISABLED
        knob = _BRIGHT if available else _MUTED

        # Three overlapping shapes form a small pill switch on old Tk versions.
        canvas.create_oval(4, 7, 38, 41, fill=track, outline=track)
        canvas.create_oval(54, 7, 88, 41, fill=track, outline=track)
        canvas.create_rectangle(21, 7, 71, 41, fill=track, outline=track)

        knob_left = 51 if enabled and available else 7
        canvas.create_oval(
            knob_left,
            10,
            knob_left + 28,
            38,
            fill=knob,
            outline=knob,
        )
