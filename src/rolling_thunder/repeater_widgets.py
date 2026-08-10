"""Tkinter repeater-panel widgets with no storage, GPS, CAT, or radio I/O."""

from __future__ import annotations

from typing import Any

from rolling_thunder.repeater_ui import RepeaterViewport

_BACKGROUND = "#151515"
_PANEL_BACKGROUND = "#101010"
_SELECTED_BACKGROUND = "#2a3f4b"
_BORDER = "#303030"
_BRIGHT = "#ffffff"
_MUTED = "#a8a8a8"
_INACTIVE = "#ff3b3b"
_BODY_FONT_SIZE = 27
_SELECTED_BORDER_PX = 5
_NORMAL_BORDER_PX = 2
_OUTER_PAD_PX = 6
_VISIBLE_CARD_COUNT = 3


class RepeaterWidgets:
    """Render the bounded six-meter repeater viewport from immutable state."""

    def __init__(self, parent: Any) -> None:
        import tkinter as tk

        self._tk = tk
        self.frame = tk.Frame(parent, bg=_BACKGROUND)
        self.frame.grid(row=1, column=0, sticky="nsew")
        self.frame.grid_columnconfigure(0, weight=1)
        self.frame.grid_rowconfigure(1, weight=1)
        self.frame.grid_remove()

        self._more_above = tk.StringVar(value="")
        tk.Label(
            self.frame,
            textvariable=self._more_above,
            bg=_BACKGROUND,
            fg=_BRIGHT,
            font=("DejaVu Sans", _BODY_FONT_SIZE, "bold"),
            anchor="center",
        ).grid(row=0, column=0, sticky="ew", pady=(0, 2))

        self._status = tk.StringVar(value="")
        self._status_label = tk.Label(
            self.frame,
            textvariable=self._status,
            bg=_BACKGROUND,
            fg=_MUTED,
            font=("DejaVu Sans", _BODY_FONT_SIZE, "bold"),
            justify="left",
            anchor="nw",
            wraplength=680,
        )
        self._status_label.grid(row=1, column=0, sticky="nsew", padx=4, pady=4)

        self._cards = tk.Frame(self.frame, bg=_BACKGROUND)
        self._cards.grid(row=1, column=0, sticky="nsew")
        self._cards.grid_columnconfigure(0, weight=1)
        self._cards.grid_remove()

        self._card_frames: list[Any] = []
        self._card_labels: list[tuple[Any, Any, Any, Any]] = []
        self._card_texts: list[tuple[Any, Any, Any, Any]] = []
        for index in range(_VISIBLE_CARD_COUNT):
            card = tk.Frame(
                self._cards,
                bg=_PANEL_BACKGROUND,
                highlightthickness=_SELECTED_BORDER_PX,
                highlightbackground=_BACKGROUND,
                highlightcolor=_BACKGROUND,
            )
            card.grid(row=index, column=0, sticky="ew", padx=2, pady=5)
            card.grid_columnconfigure(0, weight=1)

            variables = tuple(tk.StringVar(value="") for _ in range(4))
            labels = []
            for row, variable in enumerate(variables):
                label = tk.Label(
                    card,
                    textvariable=variable,
                    bg=_PANEL_BACKGROUND,
                    fg=_BRIGHT,
                    font=("DejaVu Sans", _BODY_FONT_SIZE, "bold"),
                    anchor="w",
                    justify="left",
                    padx=12,
                    pady=1,
                    wraplength=680,
                )
                label.grid(row=row, column=0, sticky="ew")
                labels.append(label)

            self._card_frames.append(card)
            self._card_labels.append(tuple(labels))
            self._card_texts.append(variables)
            card.grid_remove()

        self._more_below = tk.StringVar(value="")
        tk.Label(
            self.frame,
            textvariable=self._more_below,
            bg=_BACKGROUND,
            fg=_BRIGHT,
            font=("DejaVu Sans", _BODY_FONT_SIZE, "bold"),
            anchor="center",
        ).grid(row=2, column=0, sticky="ew", pady=(2, 0))

        self._footer = tk.StringVar(value="")
        self._footer_label = tk.Label(
            self.frame,
            textvariable=self._footer,
            bg=_BACKGROUND,
            fg=_MUTED,
            font=("DejaVu Sans", 23, "bold"),
            anchor="w",
            justify="left",
            wraplength=680,
        )
        self._footer_label.grid(row=3, column=0, sticky="ew", padx=4, pady=(4, 0))

    def show(self) -> None:
        self.frame.grid()

    def hide(self) -> None:
        self.frame.grid_remove()

    def update(self, viewport: RepeaterViewport) -> None:
        """Render one immutable repeater viewport without application I/O."""
        width = max(480, self.frame.winfo_width() - 36)
        self._status_label.configure(wraplength=width)
        self._footer_label.configure(wraplength=width)
        for labels in self._card_labels:
            for label in labels:
                label.configure(wraplength=width)

        self._more_above.set("▲ MORE ▲" if viewport.hidden_above_count else "")
        self._more_below.set("▼ MORE ▼" if viewport.hidden_below_count else "")
        self._footer.set(viewport.footer_line)

        if not viewport.has_cards:
            self._cards.grid_remove()
            self._status_label.grid()
            self._status.set("\n".join((viewport.detail_line, viewport.status_line)))
            for card in self._card_frames:
                card.grid_remove()
            return

        self._status_label.grid_remove()
        self._cards.grid()
        for index, frame in enumerate(self._card_frames):
            if index >= len(viewport.cards):
                frame.grid_remove()
                continue

            card = viewport.cards[index]
            frame.grid()
            for variable, value in zip(
                self._card_texts[index],
                (card.line1, card.line2, card.line3, card.line4),
                strict=True,
            ):
                variable.set(value)

            background = _SELECTED_BACKGROUND if card.selected else _PANEL_BACKGROUND
            border_width = _SELECTED_BORDER_PX if card.selected else _NORMAL_BORDER_PX
            padding = _OUTER_PAD_PX - border_width
            if not card.active:
                border_color = _INACTIVE
            elif card.selected:
                border_color = _BRIGHT
            else:
                border_color = _BORDER
            frame.configure(
                bg=background,
                highlightbackground=border_color,
                highlightcolor=border_color,
                highlightthickness=border_width,
                padx=padding,
                pady=padding,
            )
            for label in self._card_labels[index]:
                label.configure(bg=background)
