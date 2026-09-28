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
_SETTINGS_CARD_FONT_SIZE = 30
_SETTINGS_SECONDARY_FONT_SIZE = 18
_SETTINGS_VALUE_FONT_SIZE = 36


def _map_zoom_presentation(
    state: DashboardSettingsState,
) -> tuple[str, str, str]:
    """Return title, instruction, and right-side zoom value."""
    map_zoom = state.map_zoom
    if map_zoom is None:
        return "MAP ZOOM", "Turn encoder: OUT / IN", "DISABLED"

    instruction = (
        f"Turn encoder: OUT / IN    "
        f"Range {map_zoom.bounds.minimum}-{map_zoom.bounds.maximum}"
    )
    return "MAP ZOOM", instruction, str(map_zoom.zoom)


def _map_style_presentation(
    state: DashboardSettingsState,
) -> tuple[str, str, str, bool]:
    """Return title, instruction, value, and availability for map style."""
    map_zoom = state.map_zoom
    if map_zoom is None or map_zoom.style is None:
        return "MAP STYLE", "Context Button #2", "UNAVAILABLE", False

    switchable = len(map_zoom.available_styles) > 1
    instruction = (
        "Context Button #2: DAY / NIGHT"
        if switchable
        else "Style switch unavailable"
    )
    return "MAP STYLE", instruction, map_zoom.style.value.upper(), True


class SettingsWidgets:
    """Render visually consistent map zoom, map style, and radar controls."""

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

        zoom_card = self._create_card(content, row=0)
        self._zoom_title_text = tk.StringVar(value="MAP ZOOM")
        self._zoom_instruction_text = tk.StringVar(value="Turn encoder: OUT / IN")
        self._zoom_value_text = tk.StringVar(value="DISABLED")
        self._create_card_text(
            zoom_card,
            title_variable=self._zoom_title_text,
            instruction_variable=self._zoom_instruction_text,
        )
        self._zoom_value_label = tk.Label(
            zoom_card,
            textvariable=self._zoom_value_text,
            bg=_PANEL_BACKGROUND,
            fg=_DISABLED,
            font=("DejaVu Sans Mono", _SETTINGS_VALUE_FONT_SIZE, "bold"),
            anchor="e",
            justify="right",
        )
        self._zoom_value_label.grid(
            row=0,
            column=1,
            rowspan=2,
            sticky="e",
            padx=(12, 18),
            pady=14,
        )

        style_card = self._create_card(content, row=1)
        self._style_title_text = tk.StringVar(value="MAP STYLE")
        self._style_instruction_text = tk.StringVar(value="Context Button #2")
        self._style_value_text = tk.StringVar(value="UNAVAILABLE")
        self._create_card_text(
            style_card,
            title_variable=self._style_title_text,
            instruction_variable=self._style_instruction_text,
        )
        self._style_value_label = tk.Label(
            style_card,
            textvariable=self._style_value_text,
            bg=_PANEL_BACKGROUND,
            fg=_DISABLED,
            font=("DejaVu Sans Mono", _SETTINGS_VALUE_FONT_SIZE, "bold"),
            anchor="e",
            justify="right",
        )
        self._style_value_label.grid(
            row=0,
            column=1,
            rowspan=2,
            sticky="e",
            padx=(12, 18),
            pady=14,
        )

        radar_card = self._create_card(content, row=2)
        radar_title = tk.StringVar(value="RADAR IMAGE")
        radar_instruction = tk.StringVar(value="Context Button #1")
        self._create_card_text(
            radar_card,
            title_variable=radar_title,
            instruction_variable=radar_instruction,
        )

        self._switch = tk.Canvas(
            radar_card,
            width=112,
            height=56,
            bg=_PANEL_BACKGROUND,
            highlightthickness=0,
        )
        self._switch.grid(
            row=0,
            column=1,
            rowspan=2,
            sticky="e",
            padx=(12, 18),
            pady=14,
        )
        self._draw_switch(enabled=False, available=False)

    def _create_card(self, parent: Any, *, row: int) -> Any:
        card = self._tk.Frame(
            parent,
            bg=_PANEL_BACKGROUND,
            highlightthickness=2,
            highlightbackground=_BORDER,
        )
        card.grid(row=row, column=0, sticky="ew", pady=(2, 8))
        card.grid_columnconfigure(0, weight=1)
        return card

    def _create_card_text(
        self,
        card: Any,
        *,
        title_variable: Any,
        instruction_variable: Any,
    ) -> None:
        self._tk.Label(
            card,
            textvariable=title_variable,
            bg=_PANEL_BACKGROUND,
            fg=_BRIGHT,
            font=("DejaVu Sans", _SETTINGS_CARD_FONT_SIZE, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=(18, 8), pady=(16, 0))

        self._tk.Label(
            card,
            textvariable=instruction_variable,
            bg=_PANEL_BACKGROUND,
            fg=_MUTED,
            font=("DejaVu Sans", _SETTINGS_SECONDARY_FONT_SIZE),
            anchor="w",
        ).grid(row=1, column=0, sticky="w", padx=(18, 8), pady=(0, 16))

    def show(self) -> None:
        """Show the Settings viewport."""
        self.frame.grid()

    def hide(self) -> None:
        """Hide the Settings viewport."""
        self.frame.grid_remove()

    def update(self, state: DashboardSettingsState) -> None:
        """Update immutable Settings state without application I/O."""
        zoom_title, zoom_instruction, zoom_value = _map_zoom_presentation(state)
        self._zoom_title_text.set(zoom_title)
        self._zoom_instruction_text.set(zoom_instruction)
        self._zoom_value_text.set(zoom_value)
        self._zoom_value_label.configure(
            fg=_HEALTHY if state.map_zoom is not None else _DISABLED
        )

        (
            style_title,
            style_instruction,
            style_value,
            style_available,
        ) = _map_style_presentation(state)
        self._style_title_text.set(style_title)
        self._style_instruction_text.set(style_instruction)
        self._style_value_text.set(style_value)
        self._style_value_label.configure(
            fg=_HEALTHY if style_available else _DISABLED
        )

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
