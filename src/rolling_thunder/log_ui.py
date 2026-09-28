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
_LOG_VISIBLE_CONTACTS = 3
_LOG_SUMMARY_FONT_SIZE = 32
_LOG_STATUS_FONT_SIZE = 26
_LOG_CALLSIGN_FONT_SIZE = 27
_LOG_DETAIL_FONT_SIZE = 23
_LOG_HINT_FONT_SIZE = 23


def format_log_timestamp(snapshot_time: object) -> str:
    """Format one authoritative contact timestamp with visible date and UTC time."""
    from datetime import datetime

    if not isinstance(snapshot_time, datetime):
        raise TypeError("Log timestamp must be a datetime.")
    return snapshot_time.strftime("%m/%d/%y %H:%MZ")


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
            font=("DejaVu Sans", _LOG_SUMMARY_FONT_SIZE, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=8, pady=(0, 2))

        self._status = tk.StringVar(value="READY")
        self._status_label = tk.Label(
            self._frame,
            textvariable=self._status,
            bg=_BACKGROUND,
            fg=_MUTED,
            font=("DejaVu Sans", _LOG_STATUS_FONT_SIZE, "bold"),
            anchor="w",
        )
        self._status_label.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 8))

        self._row_vars: list[tuple[Any, Any, Any, Any, Any]] = []
        self._row_labels: list[Any] = []
        self._row_frames: list[Any] = []
        for row_index in range(_LOG_VISIBLE_CONTACTS):
            row_frame = tk.Frame(
                self._frame,
                bg=_CARD_BACKGROUND,
                highlightthickness=2,
                highlightbackground=_BORDER,
            )
            row_frame.grid(row=row_index + 2, column=0, sticky="ew", padx=4, pady=4)
            row_frame.grid_columnconfigure(0, weight=0)
            row_frame.grid_columnconfigure(1, weight=1)
            row_frame.grid_columnconfigure(2, weight=0)

            values = (
                tk.StringVar(value=""),
                tk.StringVar(value=""),
                tk.StringVar(value=""),
                tk.StringVar(value=""),
                tk.StringVar(value=""),
            )
            self._row_vars.append(values)
            timestamp, callsign, band, country, status = values

            tk.Label(
                row_frame,
                textvariable=timestamp,
                bg=_CARD_BACKGROUND,
                fg=_BRIGHT,
                font=("DejaVu Sans Mono", _LOG_DETAIL_FONT_SIZE, "bold"),
                anchor="w",
            ).grid(row=0, column=0, sticky="w", padx=(12, 8), pady=(8, 0))

            tk.Label(
                row_frame,
                textvariable=callsign,
                bg=_CARD_BACKGROUND,
                fg=_BRIGHT,
                font=("DejaVu Sans", _LOG_CALLSIGN_FONT_SIZE, "bold"),
                anchor="center",
            ).grid(row=0, column=1, sticky="ew", padx=8, pady=(5, 0))

            tk.Label(
                row_frame,
                textvariable=band,
                bg=_CARD_BACKGROUND,
                fg=_BRIGHT,
                font=("DejaVu Sans Mono", _LOG_DETAIL_FONT_SIZE, "bold"),
                anchor="e",
            ).grid(row=0, column=2, sticky="e", padx=(8, 12), pady=(8, 0))

            tk.Label(
                row_frame,
                textvariable=country,
                bg=_CARD_BACKGROUND,
                fg=_MUTED,
                font=("DejaVu Sans", _LOG_DETAIL_FONT_SIZE, "bold"),
                anchor="w",
            ).grid(
                row=1,
                column=0,
                columnspan=2,
                sticky="w",
                padx=12,
                pady=(0, 8),
            )

            status_label = tk.Label(
                row_frame,
                textvariable=status,
                bg=_CARD_BACKGROUND,
                fg=_BRIGHT,
                font=("DejaVu Sans", _LOG_DETAIL_FONT_SIZE, "bold"),
                anchor="e",
            )
            status_label.grid(
                row=1,
                column=2,
                sticky="e",
                padx=(8, 12),
                pady=(0, 8),
            )
            self._row_labels.append(status_label)
            self._row_frames.append(row_frame)

        self._hint = tk.StringVar(value="BUTTON 1: SYNC NOW")
        tk.Label(
            self._frame,
            textvariable=self._hint,
            bg=_BACKGROUND,
            fg=_MUTED,
            font=("DejaVu Sans", _LOG_HINT_FONT_SIZE, "bold"),
            anchor="w",
        ).grid(
            row=_LOG_VISIBLE_CONTACTS + 2,
            column=0,
            sticky="ew",
            padx=8,
            pady=(8, 0),
        )
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
                self._row_frames[index].grid_remove()
                continue
            row = snapshot.rows[index]
            self._row_frames[index].grid()
            timestamp, callsign, band, country, status = variables
            timestamp.set(format_log_timestamp(row.started_at))
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
