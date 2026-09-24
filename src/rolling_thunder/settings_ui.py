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
_SETTINGS_PRIMARY_FONT_SIZE = 28
_SETTINGS_ZOOM_FONT_SIZE = 36
_SETTINGS_CARD_FONT_SIZE = 30
_SETTINGS_SECONDARY_FONT_SIZE = 18
_SETTINGS_INSTRUCTION_FONT_SIZE = 20



def _zoom_presentation(
    state: DashboardSettingsState,
) -> tuple[str, str, str, str]:
    """Return compact Settings zoom text split by visual importance."""
    map_zoom = state.map_zoom
    if map_zoom is None:
        return "MAP ZOOM", "DISABLED", "", _DISABLED

    lines = map_zoom.lines
    instructions = "\n".join(lines[2:])
    return lines[0], lines[1], instructions, _HEALTHY


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

        self._zoom_title_text = tk.StringVar(value="MAP ZOOM")
        tk.Label(
            content,
            textvariable=self._zoom_title_text,
            bg=_BACKGROUND,
            fg=_BRIGHT,
            font=("DejaVu Sans Mono", _SETTINGS_PRIMARY_FONT_SIZE, "bold"),
            justify="left",
            anchor="w",
        ).grid(row=0, column=0, sticky="ew")

        self._zoom_value_text = tk.StringVar(value="DISABLED")
        self._zoom_value_label = tk.Label(
            content,
            textvariable=self._zoom_value_text,
            bg=_BACKGROUND,
            fg=_DISABLED,
            font=("DejaVu Sans Mono", _SETTINGS_ZOOM_FONT_SIZE, "bold"),
            justify="left",
            anchor="w",
        )
        self._zoom_value_label.grid(row=1, column=0, sticky="ew", pady=(0, 4))

        self._zoom_instruction_text = tk.StringVar(value="")
        tk.Label(
            content,
            textvariable=self._zoom_instruction_text,
            bg=_BACKGROUND,
            fg=_MUTED,
            font=("DejaVu Sans Mono", _SETTINGS_INSTRUCTION_FONT_SIZE),
            justify="left",
            anchor="w",
        ).grid(row=2, column=0, sticky="ew", pady=(0, 18))

        radar_card = tk.Frame(
            content,
            bg=_PANEL_BACKGROUND,
            highlightthickness=2,
            highlightbackground=_BORDER,
        )
        radar_card.grid(row=3, column=0, sticky="ew", pady=(2, 0))
        radar_card.grid_columnconfigure(0, weight=1)

        tk.Label(
            radar_card,
            text="RADAR Image",
            bg=_PANEL_BACKGROUND,
            fg=_BRIGHT,
            font=("DejaVu Sans", _SETTINGS_CARD_FONT_SIZE, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=(18, 8), pady=(18, 0))

        tk.Label(
            radar_card,
            text="Context Button #1",
            bg=_PANEL_BACKGROUND,
            fg=_MUTED,
            font=("DejaVu Sans", _SETTINGS_SECONDARY_FONT_SIZE),
            anchor="w",
        ).grid(row=1, column=0, sticky="w", padx=(18, 8), pady=(0, 18))

        self._switch = tk.Canvas(
            radar_card,
            width=112,
            height=56,
            bg=_PANEL_BACKGROUND,
            highlightthickness=0,
        )
        self._switch.grid(row=0, column=1, rowspan=2, padx=(8, 18), pady=14)
        self._draw_switch(enabled=False, available=False)

    def show(self) -> None:
        """Show the Settings viewport."""
        self.frame.grid()

    def hide(self) -> None:
        """Hide the Settings viewport."""
        self.frame.grid_remove()

    def update(self, state: DashboardSettingsState) -> None:
        """Update immutable Settings state without application I/O."""
        title, value, instructions, value_color = _zoom_presentation(state)
        self._zoom_title_text.set(title)
        self._zoom_value_text.set(value)
        self._zoom_instruction_text.set(instructions)
        self._zoom_value_label.configure(fg=value_color)
        self._draw_switch(
            enabled=state.radar_image_enabled,
            available=state.radar_available,
        )

    def _draw_switch(self, *, enabled: bool, available: bool) -> None:
        canvas = self._switch
        canvas.delete("all")
        track = _HEALTHY if enabled and available else _DISABLED
        knob = _BRIGHT if available else _MUTED

        # Three overlapping shapes form a pill switch on old Tk versions.
        canvas.create_oval(4, 9, 44, 49, fill=track, outline=track)
        canvas.create_oval(68, 9, 108, 49, fill=track, outline=track)
        canvas.create_rectangle(24, 9, 88, 49, fill=track, outline=track)

        knob_left = 65 if enabled and available else 8
        canvas.create_oval(
            knob_left,
            12,
            knob_left + 34,
            46,
            fill=knob,
            outline=knob,
        )
