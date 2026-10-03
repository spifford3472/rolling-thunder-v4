"""Tk widgets for the mobile-readable FT8 CQ browser."""

from __future__ import annotations

import tkinter as tk

from rolling_thunder.ft8_ui import (
    FT8BrowserViewport,
    FT8CallPresentation,
)

_BACKGROUND = "#151515"
_ROW_BACKGROUND = "#101010"
_SELECTED_BACKGROUND = "#315f73"
_BORDER = "#303030"
_WHITE = "#ffffff"
_GRAY = "#8f8f8f"
_YELLOW = "#ffd24a"
_MUTED = "#a8a8a8"


class FT8Widgets:
    """Large, glance-readable CQ table for the in-vehicle display."""

    def __init__(self, parent: tk.Misc, *, visible_rows: int = 5) -> None:
        self.visible_rows = visible_rows
        self.frame = tk.Frame(parent, bg=_BACKGROUND)
        self.frame.grid_columnconfigure(0, weight=1)
        self.frame.grid_rowconfigure(2, weight=1)

        self.more_above = tk.StringVar(value="")
        tk.Label(
            self.frame,
            textvariable=self.more_above,
            bg=_BACKGROUND,
            fg=_MUTED,
            font=("DejaVu Sans", 18, "bold"),
            anchor="center",
        ).grid(row=0, column=0, sticky="ew")

        header = tk.Frame(self.frame, bg=_BORDER)
        header.grid(row=1, column=0, sticky="ew", padx=2, pady=(0, 3))
        for column, (label, weight) in enumerate(
            (("CALL", 5), ("SNR", 2), ("AUDIO", 3), ("GRID", 3))
        ):
            header.grid_columnconfigure(column, weight=weight, uniform="ft8")
            tk.Label(
                header,
                text=label,
                bg=_BORDER,
                fg=_WHITE,
                font=("DejaVu Sans", 24, "bold"),
                anchor="center",
                padx=4,
                pady=5,
            ).grid(row=0, column=column, sticky="nsew")

        self.rows_frame = tk.Frame(self.frame, bg=_BACKGROUND)
        self.rows_frame.grid(row=2, column=0, sticky="nsew")
        self.rows_frame.grid_columnconfigure(0, weight=1)

        self._row_frames: list[tk.Frame] = []
        self._row_labels: list[tuple[tk.Label, tk.Label, tk.Label, tk.Label]] = []
        for index in range(visible_rows):
            row = tk.Frame(
                self.rows_frame,
                bg=_ROW_BACKGROUND,
                highlightthickness=2,
                highlightbackground=_BORDER,
            )
            row.grid(row=index, column=0, sticky="ew", padx=2, pady=3)
            values: list[tk.Label] = []
            for column, weight in enumerate((5, 2, 3, 3)):
                row.grid_columnconfigure(column, weight=weight, uniform="ft8")
                label = tk.Label(
                    row,
                    text="",
                    bg=_ROW_BACKGROUND,
                    fg=_WHITE,
                    font=("DejaVu Sans", 27, "bold"),
                    anchor="w" if column == 0 else "center",
                    padx=7,
                    pady=7,
                )
                label.grid(row=0, column=column, sticky="nsew")
                values.append(label)
            self._row_frames.append(row)
            self._row_labels.append((values[0], values[1], values[2], values[3]))
            row.grid_remove()

        self.more_below = tk.StringVar(value="")
        tk.Label(
            self.frame,
            textvariable=self.more_below,
            bg=_BACKGROUND,
            fg=_MUTED,
            font=("DejaVu Sans", 18, "bold"),
            anchor="center",
        ).grid(row=3, column=0, sticky="ew")

        self.footer = tk.StringVar(value="")
        tk.Label(
            self.frame,
            textvariable=self.footer,
            bg=_BACKGROUND,
            fg=_MUTED,
            font=("DejaVu Sans", 20, "bold"),
            anchor="center",
            justify="center",
        ).grid(row=4, column=0, sticky="ew", pady=(4, 0))

        self.frame.grid_remove()

    def show(self) -> None:
        self.frame.grid(row=1, column=0, sticky="nsew", padx=4, pady=2)

    def hide(self) -> None:
        self.frame.grid_remove()

    def update(self, viewport: FT8BrowserViewport, *, transmit_enabled: bool) -> None:
        self.more_above.set("▲ MORE ▲" if viewport.hidden_above else "")
        self.more_below.set("▼ MORE ▼" if viewport.hidden_below else "")

        for index, frame in enumerate(self._row_frames):
            if index >= len(viewport.rows):
                frame.grid_remove()
                continue

            row = viewport.rows[index]
            background = _SELECTED_BACKGROUND if row.selected else _ROW_BACKGROUND
            border = _WHITE if row.selected else _BORDER
            frame.configure(
                bg=background,
                highlightbackground=border,
                highlightcolor=border,
                highlightthickness=4 if row.selected else 2,
            )

            call_color = (
                _WHITE
                if row.selected
                else {
                    FT8CallPresentation.WHITE: _WHITE,
                    FT8CallPresentation.GRAY: _GRAY,
                    FT8CallPresentation.YELLOW: _YELLOW,
                }[row.call_presentation]
            )
            texts = (row.call_text, row.snr_text, row.audio_text, row.grid_text)
            for column, label in enumerate(self._row_labels[index]):
                label.configure(
                    text=texts[column],
                    bg=background,
                    fg=call_color if column == 0 else _WHITE,
                )
            frame.grid()

        if transmit_enabled:
            self.footer.set("BUTTON 1 BAND  •  ROTATE SELECT  •  PRESS ENCODER START")
        else:
            self.footer.set("BUTTON 1 BAND  •  ROTATE SELECT  •  RECEIVE ONLY")
