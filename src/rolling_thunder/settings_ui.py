"""Tkinter Settings-page widgets with no application or network I/O."""

from __future__ import annotations

from typing import Any

from rolling_thunder.power_control import PowerAction, PowerConfirmationState
from rolling_thunder.settings_panel import DashboardSettingsState
from rolling_thunder.settings_selection import SettingId, SettingsOption, SettingsSelection

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
_VISIBLE_ROWS = 4


def _settings_window(selected: SettingsOption) -> tuple[SettingsOption, ...]:
    """Return the four-row automatic viewport containing the selection."""
    order = SettingsSelection.ORDER
    index = order.index(selected)
    start = min(max(index - _VISIBLE_ROWS + 1, 0), len(order) - _VISIBLE_ROWS)
    return order[start : start + _VISIBLE_ROWS]


def _power_presentation(
    setting: SettingsOption,
    state: PowerConfirmationState,
) -> tuple[str, str]:
    """Return truthful power value and bounded selected-row instruction."""
    expected = PowerAction.REBOOT if setting is SettingsOption.REBOOT else PowerAction.SHUTDOWN
    if state.last_error:
        reason = " ".join(state.last_error.split())[:96]
        failed_action = state.action or expected
        return f"{failed_action.name} FAILED", reason
    if state.pending and state.action is expected:
        return f"{expected.name} PENDING", "Waiting for system SIGTERM"
    if not state.available:
        health = state.health.value.upper() if state.health is not None else "NO TRUSTED INPUT"
        return "UNAVAILABLE", health
    if state.action is expected:
        return "CONFIRM", "B2 CANCEL   B3 CONFIRM"
    return "SELECT", "B2 CANCEL   B3 SELECT"


def _map_zoom_presentation(
    state: DashboardSettingsState,
) -> tuple[str, str, str]:
    """Return title, instruction, and right-side zoom value."""
    map_zoom = state.map_zoom
    if map_zoom is None:
        return "MAP ZOOM", "B2 OUT   B3 IN", "UNAVAILABLE"

    instruction = (
        f"B2 OUT   B3 IN    Range {map_zoom.bounds.minimum}-{map_zoom.bounds.maximum}"
    )
    return "MAP ZOOM", instruction, str(map_zoom.zoom)


def _map_style_presentation(
    state: DashboardSettingsState,
) -> tuple[str, str, str, bool]:
    """Return title, instruction, value, and availability for map style."""
    map_zoom = state.map_zoom
    if map_zoom is None or map_zoom.style is None:
        return "MAP STYLE", "B2 NIGHT   B3 DAY", "UNAVAILABLE", False

    switchable = len(map_zoom.available_styles) > 1
    instruction = (
        "B2 NIGHT   B3 DAY"
        if switchable
        else "Style switch unavailable"
    )
    return "MAP STYLE", instruction, map_zoom.style.value.upper(), True


class SettingsWidgets:
    """Render visually consistent map, radar, and callsign-info controls."""

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
        self._cards: dict[SettingId, Any] = {}
        self._titles: dict[SettingId, Any] = {}
        self._instructions: dict[SettingId, Any] = {}

        zoom_card = self._create_card(content, row=0)
        self._zoom_title_text = tk.StringVar(value="MAP ZOOM")
        self._zoom_instruction_text = tk.StringVar(value="B2 OUT   B3 IN")
        self._zoom_value_text = tk.StringVar(value="UNAVAILABLE")
        self._create_card_text(
            zoom_card,
            title_variable=self._zoom_title_text,
            instruction_variable=self._zoom_instruction_text,
        )
        self._remember(SettingId.MAP_ZOOM, zoom_card, self._zoom_title_text, self._zoom_instruction_text)
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

        style_card = self._create_card(content, row=3)
        self._style_title_text = tk.StringVar(value="MAP STYLE")
        self._style_instruction_text = tk.StringVar(value="B2 NIGHT   B3 DAY")
        self._style_value_text = tk.StringVar(value="UNAVAILABLE")
        self._create_card_text(
            style_card,
            title_variable=self._style_title_text,
            instruction_variable=self._style_instruction_text,
        )
        self._remember(SettingId.MAP_STYLE, style_card, self._style_title_text, self._style_instruction_text)
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

        radar_card = self._create_card(content, row=1)
        radar_title = tk.StringVar(value="RADAR IMAGE")
        radar_instruction = tk.StringVar(value="B2 OFF   B3 ON")
        self._create_card_text(
            radar_card,
            title_variable=radar_title,
            instruction_variable=radar_instruction,
        )
        self._remember(SettingId.RADAR, radar_card, radar_title, radar_instruction)

        self._radar_switch = tk.Canvas(
            radar_card,
            width=112,
            height=56,
            bg=_PANEL_BACKGROUND,
            highlightthickness=0,
        )
        self._radar_switch.grid(
            row=0,
            column=1,
            rowspan=2,
            sticky="e",
            padx=(12, 18),
            pady=14,
        )
        self._draw_switch(self._radar_switch, enabled=False, available=False)

        callsign_card = self._create_card(content, row=2)
        callsign_title = tk.StringVar(value="CALLSIGN INFO")
        callsign_instruction = tk.StringVar(value="B2 OFF   B3 ON")
        self._create_card_text(
            callsign_card,
            title_variable=callsign_title,
            instruction_variable=callsign_instruction,
        )
        self._remember(SettingId.CALLSIGN_INFO, callsign_card, callsign_title, callsign_instruction)
        self._callsign_switch = tk.Canvas(
            callsign_card,
            width=112,
            height=56,
            bg=_PANEL_BACKGROUND,
            highlightthickness=0,
        )
        self._callsign_switch.grid(
            row=0,
            column=1,
            rowspan=2,
            sticky="e",
            padx=(12, 18),
            pady=14,
        )
        self._draw_switch(self._callsign_switch, enabled=False, available=False)

        self._power_values: dict[SettingId, Any] = {}
        for row, setting, title in (
            (4, SettingId.REBOOT, "REBOOT"),
            (5, SettingId.SHUTDOWN, "SHUTDOWN"),
        ):
            card = self._create_card(content, row=row)
            title_text = tk.StringVar(value=title)
            instruction = tk.StringVar(value="Power input unavailable")
            value = tk.StringVar(value="UNAVAILABLE")
            self._create_card_text(card, title_variable=title_text, instruction_variable=instruction)
            tk.Label(
                card, textvariable=value, bg=_PANEL_BACKGROUND, fg=_MUTED,
                font=("DejaVu Sans Mono", _SETTINGS_VALUE_FONT_SIZE, "bold"), anchor="e",
            ).grid(row=0, column=1, rowspan=2, sticky="e", padx=(12, 18), pady=8)
            self._remember(setting, card, title_text, instruction)
            self._power_values[setting] = value

        self._rows_text = tk.StringVar(value="ROWS 1-4 OF 6  •  MORE BELOW")
        self._rows_label = tk.Label(
            content,
            textvariable=self._rows_text,
            bg=_BACKGROUND,
            fg=_MUTED,
            font=("DejaVu Sans", _SETTINGS_SECONDARY_FONT_SIZE, "bold"),
            anchor="center",
        )
        self._rows_label.grid(row=6, column=0, sticky="ew", pady=(0, 2))

    def _remember(self, setting: SettingId, card: Any, title: Any, instruction: Any) -> None:
        self._cards[setting] = card
        self._titles[setting] = title
        self._instructions[setting] = instruction

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
        ).grid(row=0, column=0, sticky="w", padx=(18, 8), pady=(8, 0))

        self._tk.Label(
            card,
            textvariable=instruction_variable,
            bg=_PANEL_BACKGROUND,
            fg=_MUTED,
            font=("DejaVu Sans", _SETTINGS_SECONDARY_FONT_SIZE),
            anchor="w",
        ).grid(row=1, column=0, sticky="w", padx=(18, 8), pady=(0, 8))

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
            self._radar_switch,
            enabled=state.radar_image_enabled,
            available=state.radar_available,
        )
        self._draw_switch(
            self._callsign_switch,
            enabled=state.callsign_info_enabled,
            available=state.callsign_info_available,
        )

        base_titles = {
            SettingId.MAP_ZOOM: "MAP ZOOM",
            SettingId.RADAR: "RADAR IMAGE",
            SettingId.CALLSIGN_INFO: "CALLSIGN INFO",
            SettingId.MAP_STYLE: "MAP STYLE",
            SettingId.REBOOT: "REBOOT",
            SettingId.SHUTDOWN: "SHUTDOWN",
        }
        selected = state.selection.selected
        visible = _settings_window(selected)
        first = SettingsSelection.ORDER.index(visible[0]) + 1
        last = first + len(visible) - 1
        markers: list[str] = []
        if first > 1:
            markers.append("MORE ABOVE")
        if last < len(SettingsSelection.ORDER):
            markers.append("MORE BELOW")
        suffix = f"  •  {' / '.join(markers)}" if markers else "  •  ALL ROWS SHOWN"
        self._rows_text.set(f"ROWS {first}-{last} OF {len(SettingsSelection.ORDER)}{suffix}")
        for setting, card in self._cards.items():
            if setting in visible:
                card.grid()
            else:
                card.grid_remove()
            is_selected = setting is selected
            self._titles[setting].set(("> " if is_selected else "  ") + base_titles[setting])
            card.configure(highlightbackground=_HEALTHY if is_selected else _BORDER)

        instructions = {
            SettingId.MAP_ZOOM: "B2 OUT   B3 IN",
            SettingId.RADAR: "B2 OFF   B3 ON" if state.radar_available else "UNAVAILABLE",
            SettingId.CALLSIGN_INFO: "B2 OFF   B3 ON" if state.callsign_info_available else "UNAVAILABLE",
            SettingId.MAP_STYLE: "B2 NIGHT   B3 DAY",
            SettingId.REBOOT: "",
            SettingId.SHUTDOWN: "",
        }
        for instruction in self._instructions.values():
            instruction.set("")
        self._instructions[selected].set(instructions[selected])

        confirmation = state.power_confirmation
        for setting in (SettingId.REBOOT, SettingId.SHUTDOWN):
            value, reason = _power_presentation(setting, confirmation)
            self._power_values[setting].set(value)
            if setting is selected:
                self._instructions[setting].set(reason)

    def _draw_switch(self, canvas: Any, *, enabled: bool, available: bool) -> None:
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
        canvas.create_text(
            56,
            28,
            text=("UNAVAILABLE" if not available else ("ON" if enabled else "OFF")),
            fill=_BRIGHT,
            font=("DejaVu Sans", 11, "bold"),
        )
