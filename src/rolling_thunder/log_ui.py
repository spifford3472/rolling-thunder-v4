"""Tkinter adapter for immutable Rolling Thunder Log panel snapshots."""

from __future__ import annotations

from typing import Any

from rolling_thunder.domain import SynchronizationState
from rolling_thunder.log_panel import LogPanelSnapshot

_BACKGROUND = "#151515"
_CARD_BACKGROUND = "#101010"
_BORDER = "#303030"
_BRIGHT = "#ffffff"
_MUTED = "#a8a8a8"
_SUCCESS = "#42ff72"
_WARNING = "#ffd24a"
_FAILURE = "#ff7070"


class LogWidgets:
    """Render latest local contacts without performing storage or network work."""

    def __init__(self, parent: Any) -> None:
        import tkinter as tk

        self._frame = tk.Frame(parent, bg=_BACKGROUND)
        self._frame.grid(row=1, column=0, sticky="nsew")
        self._frame.grid_columnconfigure(0, weight=1)

        self._summary = tk.StringVar(value="UNSYNCED 0 / TOTAL 0")
        tk.Label(
            self._frame,
            textvariable=self._summary,
            bg=_BACKGROUND,
            fg=_BRIGHT,
            font=("DejaVu Sans", 25, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=8, pady=(0, 2))

        self._status = tk.StringVar(value="READY")
        self._status_label = tk.Label(
            self._frame,
            textvariable=self._status,
            bg=_BACKGROUND,
            fg=_MUTED,
            font=("DejaVu Sans", 18, "bold"),
            anchor="w",
        )
        self._status_label.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 5))

        header = tk.Frame(self._frame, bg=_CARD_BACKGROUND)
        header.grid(row=2, column=0, sticky="ew", padx=4)
        widths = (15, 14, 7, 7, 9)
        for column, (title, width) in enumerate(
            zip(("UTC", "CALL", "BAND", "CTRY", "SYNC"), widths, strict=True)
        ):
            header.grid_columnconfigure(column, weight=1 if column in {0, 1} else 0)
            tk.Label(
                header,
                text=title,
                width=width,
                bg=_CARD_BACKGROUND,
                fg=_MUTED,
                font=("DejaVu Sans Mono", 15, "bold"),
                anchor="w",
            ).grid(row=0, column=column, sticky="ew", padx=2, pady=2)

        self._row_vars: list[tuple[Any, Any, Any, Any, Any]] = []
        self._row_labels: list[Any] = []
        for row_index in range(10):
            row_frame = tk.Frame(
                self._frame,
                bg=_CARD_BACKGROUND,
                highlightthickness=1,
                highlightbackground=_BORDER,
            )
            row_frame.grid(row=row_index + 3, column=0, sticky="ew", padx=4, pady=1)
            values = (
                tk.StringVar(value=""),
                tk.StringVar(value=""),
                tk.StringVar(value=""),
                tk.StringVar(value=""),
                tk.StringVar(value=""),
            )
            self._row_vars.append(values)
            status_label = None
            for column, (variable, width) in enumerate(zip(values, widths, strict=True)):
                row_frame.grid_columnconfigure(column, weight=1 if column in {0, 1} else 0)
                label = tk.Label(
                    row_frame,
                    textvariable=variable,
                    width=width,
                    bg=_CARD_BACKGROUND,
                    fg=_BRIGHT,
                    font=("DejaVu Sans Mono", 15, "bold"),
                    anchor="w",
                )
                label.grid(row=0, column=column, sticky="ew", padx=2, pady=2)
                if column == 4:
                    status_label = label
            assert status_label is not None
            self._row_labels.append(status_label)

        self._hint = tk.StringVar(value="BUTTON 1: SYNC UNSYNCED")
        tk.Label(
            self._frame,
            textvariable=self._hint,
            bg=_BACKGROUND,
            fg=_MUTED,
            font=("DejaVu Sans", 16, "bold"),
            anchor="w",
        ).grid(row=13, column=0, sticky="ew", padx=8, pady=(5, 0))
        self.hide()

    def show(self) -> None:
        self._frame.grid()

    def hide(self) -> None:
        self._frame.grid_remove()

    def update(self, snapshot: LogPanelSnapshot) -> None:
        """Update rows from one immutable background-produced snapshot."""
        self._summary.set(snapshot.summary_text)
        self._status.set(snapshot.status_text)
        self._status_label.configure(fg=self._panel_status_color(snapshot))
        for index, variables in enumerate(self._row_vars):
            if index >= len(snapshot.rows):
                for variable in variables:
                    variable.set("")
                self._row_labels[index].configure(fg=_BRIGHT)
                continue
            row = snapshot.rows[index]
            timestamp, callsign, band, country, status = variables
            timestamp.set(row.started_at.strftime("%m-%d %H:%MZ"))
            callsign.set(row.callsign)
            band.set(row.band)
            country.set(row.country)
            status.set(row.status_text)
            self._row_labels[index].configure(
                fg={
                    SynchronizationState.SYNCHRONIZED: _SUCCESS,
                    SynchronizationState.PENDING: _WARNING,
                    SynchronizationState.FAILED: _FAILURE,
                }[row.synchronization_state]
            )

    @staticmethod
    def _panel_status_color(snapshot: LogPanelSnapshot) -> str:
        if snapshot.syncing:
            return _WARNING
        if "ERROR" in snapshot.status_text or "FAILED" in snapshot.status_text:
            return _FAILURE
        if snapshot.unsynchronized_count:
            return _WARNING
        if snapshot.total_count:
            return _SUCCESS
        return _MUTED
