"""Tkinter adapter for the immutable DMR hotspot viewport."""

from __future__ import annotations

from typing import Any

from rolling_thunder.dmr_ui import DmrViewport

_BACKGROUND = "#151515"
_CARD_BACKGROUND = "#101010"
_SELECTED_BACKGROUND = "#2a3f4b"
_BORDER = "#303030"
_BRIGHT = "#ffffff"
_MUTED = "#a8a8a8"
_SUCCESS = "#42ff72"
_WARNING = "#ffd24a"
_FAILURE = "#ff7070"

_MAX_AUDIO_CARDS = 2
_MAX_HISTORY_CARDS = 4


class DmrWidgets:
    """Render one bounded DMR viewport without performing network or storage work."""

    def __init__(self, parent: Any) -> None:
        import tkinter as tk

        self._frame = tk.Frame(parent, bg=_BACKGROUND)
        self._frame.grid(row=1, column=0, sticky="nsew")
        self._frame.grid_columnconfigure(0, weight=1)

        self._health = tk.StringVar(value="STARTING")
        self._health_label = tk.Label(
            self._frame,
            textvariable=self._health,
            bg=_BACKGROUND,
            fg=_MUTED,
            font=("DejaVu Sans", 15, "bold"),
            anchor="w",
        )
        self._health_label.grid(row=0, column=0, sticky="ew", padx=6, pady=(0, 1))

        self._rf = tk.StringVar(value="RF INFORMATION UNAVAILABLE")
        tk.Label(
            self._frame,
            textvariable=self._rf,
            bg=_BACKGROUND,
            fg=_BRIGHT,
            font=("DejaVu Sans", 15, "bold"),
            anchor="w",
        ).grid(row=1, column=0, sticky="ew", padx=6, pady=(0, 1))

        self._error = tk.StringVar(value="")
        self._error_label = tk.Label(
            self._frame,
            textvariable=self._error,
            bg=_BACKGROUND,
            fg=_FAILURE,
            font=("DejaVu Sans", 12, "bold"),
            anchor="w",
            justify="left",
            wraplength=500,
        )
        self._error_label.grid(row=2, column=0, sticky="ew", padx=6, pady=(0, 2))

        tk.Label(
            self._frame,
            text="CURRENT AUDIO",
            bg=_BACKGROUND,
            fg=_MUTED,
            font=("DejaVu Sans", 13, "bold"),
            anchor="w",
        ).grid(row=3, column=0, sticky="ew", padx=6, pady=(1, 1))

        self._audio_idle = tk.StringVar(value="IDLE — NO ACTIVE DMR AUDIO")
        self._audio_idle_label = tk.Label(
            self._frame,
            textvariable=self._audio_idle,
            bg=_CARD_BACKGROUND,
            fg=_MUTED,
            font=("DejaVu Sans", 16, "bold"),
            anchor="center",
            pady=5,
        )
        self._audio_idle_label.grid(row=4, column=0, sticky="ew", padx=4, pady=1)

        self._audio_frames: list[Any] = []
        self._audio_vars: list[tuple[Any, Any, Any]] = []
        for card_index in range(_MAX_AUDIO_CARDS):
            frame = tk.Frame(
                self._frame,
                bg=_CARD_BACKGROUND,
                highlightthickness=2,
                highlightbackground=_BORDER,
            )
            frame.grid(row=4 + card_index, column=0, sticky="ew", padx=4, pady=1)
            frame.grid_columnconfigure(0, weight=1)

            callsign = tk.StringVar(value="")
            detail = tk.StringVar(value="")
            alias = tk.StringVar(value="")
            tk.Label(
                frame,
                textvariable=callsign,
                bg=_CARD_BACKGROUND,
                fg=_BRIGHT,
                font=("DejaVu Sans", 22, "bold"),
                anchor="w",
            ).grid(row=0, column=0, sticky="ew", padx=8, pady=(2, 0))
            tk.Label(
                frame,
                textvariable=detail,
                bg=_CARD_BACKGROUND,
                fg=_BRIGHT,
                font=("DejaVu Sans", 13, "bold"),
                anchor="w",
            ).grid(row=1, column=0, sticky="ew", padx=8, pady=0)
            tk.Label(
                frame,
                textvariable=alias,
                bg=_CARD_BACKGROUND,
                fg=_MUTED,
                font=("DejaVu Sans", 12),
                anchor="w",
            ).grid(row=2, column=0, sticky="ew", padx=8, pady=(0, 2))
            self._audio_frames.append(frame)
            self._audio_vars.append((callsign, detail, alias))
            frame.grid_remove()

        tk.Label(
            self._frame,
            text="RECENT CALLERS",
            bg=_BACKGROUND,
            fg=_MUTED,
            font=("DejaVu Sans", 13, "bold"),
            anchor="w",
        ).grid(row=6, column=0, sticky="ew", padx=6, pady=(3, 1))

        self._history_frames: list[Any] = []
        self._history_vars: list[tuple[Any, Any]] = []
        for card_index in range(_MAX_HISTORY_CARDS):
            frame = tk.Frame(
                self._frame,
                bg=_CARD_BACKGROUND,
                highlightthickness=2,
                highlightbackground=_BORDER,
            )
            frame.grid(row=7 + card_index, column=0, sticky="ew", padx=4, pady=1)
            frame.grid_columnconfigure(0, weight=1)

            callsign = tk.StringVar(value="")
            detail = tk.StringVar(value="")
            tk.Label(
                frame,
                textvariable=callsign,
                bg=_CARD_BACKGROUND,
                fg=_BRIGHT,
                font=("DejaVu Sans", 16, "bold"),
                anchor="w",
            ).grid(row=0, column=0, sticky="ew", padx=8, pady=(1, 0))
            tk.Label(
                frame,
                textvariable=detail,
                bg=_CARD_BACKGROUND,
                fg=_MUTED,
                font=("DejaVu Sans Mono", 11, "bold"),
                anchor="w",
            ).grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 1))
            self._history_frames.append(frame)
            self._history_vars.append((callsign, detail))
            frame.grid_remove()

        self._more = tk.StringVar(value="")
        tk.Label(
            self._frame,
            textvariable=self._more,
            bg=_BACKGROUND,
            fg=_MUTED,
            font=("DejaVu Sans", 11, "bold"),
            anchor="center",
        ).grid(row=11, column=0, sticky="ew", padx=6, pady=(1, 0))

        self._stage = tk.StringVar(value="")
        tk.Label(
            self._frame,
            textvariable=self._stage,
            bg=_BACKGROUND,
            fg=_WARNING,
            font=("DejaVu Sans", 12, "bold"),
            anchor="w",
            justify="left",
            wraplength=500,
        ).grid(row=12, column=0, sticky="ew", padx=6, pady=(2, 0))

        self._commit = tk.StringVar(value="")
        self._commit_label = tk.Label(
            self._frame,
            textvariable=self._commit,
            bg=_BACKGROUND,
            fg=_MUTED,
            font=("DejaVu Sans", 12, "bold"),
            anchor="w",
            justify="left",
            wraplength=500,
        )
        self._commit_label.grid(row=13, column=0, sticky="ew", padx=6, pady=(1, 0))
        self.hide()

    def show(self) -> None:
        """Show the DMR context body."""
        self._frame.grid()

    def hide(self) -> None:
        """Hide the DMR context body without destroying its retained state."""
        self._frame.grid_remove()

    def update(self, viewport: DmrViewport) -> None:
        """Render one immutable viewport snapshot using only local widget operations."""
        self._health.set(viewport.health_line)
        self._health_label.configure(fg=self._health_color(viewport.health_line))
        self._rf.set(viewport.rf_line)
        self._error.set(viewport.error_line)
        if viewport.error_line:
            self._error_label.grid()
        else:
            self._error_label.grid_remove()

        self._audio_idle_label.grid_remove()
        for index, frame in enumerate(self._audio_frames):
            if index >= len(viewport.current_audio_cards):
                frame.grid_remove()
                continue
            audio_card = viewport.current_audio_cards[index]
            callsign, detail, alias = self._audio_vars[index]
            callsign.set(audio_card.callsign_line)
            detail.set(audio_card.detail_line)
            alias.set(audio_card.alias_line)
            frame.configure(
                highlightbackground=_SUCCESS if audio_card.staged else _BORDER,
                bg=_CARD_BACKGROUND,
            )
            frame.grid()
        if viewport.current_audio_idle:
            self._audio_idle_label.grid()

        for index, frame in enumerate(self._history_frames):
            if index >= len(viewport.history_cards):
                frame.grid_remove()
                continue
            history_card = viewport.history_cards[index]
            callsign, detail = self._history_vars[index]
            callsign.set(history_card.callsign_line)
            detail.set(history_card.detail_line)
            background = (
                _SELECTED_BACKGROUND if history_card.selected else _CARD_BACKGROUND
            )
            frame.configure(
                bg=background,
                highlightbackground=(
                    _SUCCESS
                    if history_card.staged
                    else (_BRIGHT if history_card.selected else _BORDER)
                ),
            )
            for child in frame.winfo_children():
                child.configure(bg=background)
            frame.grid()

        markers: list[str] = []
        if viewport.hidden_above_count:
            markers.append(f"▲ {viewport.hidden_above_count} NEWER")
        if viewport.hidden_below_count:
            markers.append(f"▼ {viewport.hidden_below_count} OLDER")
        self._more.set("     ".join(markers))
        self._stage.set(viewport.stage_line)
        self._commit.set(viewport.commit_line)
        self._commit_label.configure(fg=self._commit_color(viewport.commit_line))

    @staticmethod
    def _health_color(health_line: str) -> str:
        normalized = health_line.upper()
        if normalized.startswith("HEALTHY"):
            return _SUCCESS
        if normalized.startswith(("DEGRADED", "STARTING")):
            return _WARNING
        return _FAILURE

    @staticmethod
    def _commit_color(commit_line: str) -> str:
        normalized = commit_line.upper()
        if normalized.startswith("LOGGED"):
            return _SUCCESS
        if normalized.startswith("COMMIT FAILED"):
            return _FAILURE
        if normalized.startswith("COMMITTING"):
            return _WARNING
        return _MUTED
