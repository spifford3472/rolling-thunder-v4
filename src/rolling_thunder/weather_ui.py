"""Tkinter adapter for immutable weather-panel presentation."""

from __future__ import annotations

from typing import Any

from rolling_thunder.weather_panel import WeatherPanelPresentation, WeatherPanelStatus

_BACKGROUND = "#151515"
_CARD_BACKGROUND = "#101010"
_BORDER = "#303030"
_BRIGHT = "#ffffff"
_MUTED = "#a8a8a8"
_HEALTHY = "#66ccff"
_WARNING = "#ffd24a"
_FAILURE = "#ff7070"
_DISABLED = "#777777"


def weather_status_color(status: WeatherPanelStatus) -> str:
    """Return the approved live/yellow/gray/red weather status color."""
    if status is WeatherPanelStatus.LIVE:
        return _HEALTHY
    if status in {WeatherPanelStatus.RETAINED, WeatherPanelStatus.STALE}:
        return _WARNING
    if status is WeatherPanelStatus.ERROR:
        return _FAILURE
    return _DISABLED


class WeatherWidgets:
    """Render weather presentation without network, storage, or provider work."""

    def __init__(self, parent: Any) -> None:
        import tkinter as tk

        self._tk = tk
        self._frame = tk.Frame(parent, bg=_BACKGROUND)
        self._frame.grid(row=1, column=0, sticky="nsew")
        self._frame.grid_columnconfigure(0, weight=1)
        self._frame.grid_rowconfigure(2, weight=1)

        self._status_text = tk.StringVar(value="UNAVAILABLE")
        self._status_label = tk.Label(
            self._frame,
            textvariable=self._status_text,
            bg=_BACKGROUND,
            fg=_DISABLED,
            font=("DejaVu Sans", 28, "bold"),
            anchor="center",
        )
        self._status_label.grid(row=0, column=0, sticky="ew", pady=(0, 6))

        current = tk.Frame(
            self._frame,
            bg=_CARD_BACKGROUND,
            highlightthickness=2,
            highlightbackground=_BORDER,
        )
        current.grid(row=1, column=0, sticky="ew", padx=4, pady=4)
        current.grid_columnconfigure(1, weight=1)

        self._icon_text = tk.StringVar(value="?")
        tk.Label(
            current,
            textvariable=self._icon_text,
            bg=_CARD_BACKGROUND,
            fg=_BRIGHT,
            font=("DejaVu Sans", 70, "bold"),
            anchor="center",
            width=2,
        ).grid(row=0, column=0, rowspan=3, sticky="ns", padx=(10, 12), pady=6)

        self._temperature_text = tk.StringVar(value="--°F / --°C")
        tk.Label(
            current,
            textvariable=self._temperature_text,
            bg=_CARD_BACKGROUND,
            fg=_BRIGHT,
            font=("DejaVu Sans", 48, "bold"),
            anchor="w",
        ).grid(row=0, column=1, sticky="ew", padx=(0, 10), pady=(8, 0))

        self._condition_text = tk.StringVar(value="Unavailable")
        tk.Label(
            current,
            textvariable=self._condition_text,
            bg=_CARD_BACKGROUND,
            fg=_BRIGHT,
            font=("DejaVu Sans", 28, "bold"),
            anchor="w",
        ).grid(row=1, column=1, sticky="ew", padx=(0, 10))

        self._solar_text = tk.StringVar(value="SUNRISE --:--   SUNSET --:--")
        tk.Label(
            current,
            textvariable=self._solar_text,
            bg=_CARD_BACKGROUND,
            fg=_MUTED,
            font=("DejaVu Sans", 22, "bold"),
            anchor="w",
        ).grid(row=2, column=1, sticky="ew", padx=(0, 10), pady=(0, 8))

        hourly = tk.Frame(self._frame, bg=_BACKGROUND)
        hourly.grid(row=2, column=0, sticky="nsew", padx=4, pady=(8, 4))
        for column in range(3):
            hourly.grid_columnconfigure(column, weight=1, uniform="hourly")
        hourly.grid_rowconfigure(0, weight=1)

        self._hourly_texts: list[tuple[Any, Any, Any]] = []
        for column in range(3):
            card = tk.Frame(
                hourly,
                bg=_CARD_BACKGROUND,
                highlightthickness=2,
                highlightbackground=_BORDER,
            )
            card.grid(row=0, column=column, sticky="nsew", padx=4, pady=2)
            card.grid_columnconfigure(0, weight=1)

            time_text = tk.StringVar(value="--:--")
            temp_text = tk.StringVar(value="--°F\n--°C")
            precip_text = tk.StringVar(value="RAIN --%")

            tk.Label(
                card,
                textvariable=time_text,
                bg=_CARD_BACKGROUND,
                fg=_MUTED,
                font=("DejaVu Sans", 21, "bold"),
                anchor="center",
            ).grid(row=0, column=0, sticky="ew", pady=(8, 2))

            tk.Label(
                card,
                textvariable=temp_text,
                bg=_CARD_BACKGROUND,
                fg=_BRIGHT,
                font=("DejaVu Sans", 29, "bold"),
                anchor="center",
                justify="center",
            ).grid(row=1, column=0, sticky="nsew", pady=2)

            tk.Label(
                card,
                textvariable=precip_text,
                bg=_CARD_BACKGROUND,
                fg=_MUTED,
                font=("DejaVu Sans", 20, "bold"),
                anchor="center",
            ).grid(row=2, column=0, sticky="ew", pady=(2, 8))

            self._hourly_texts.append((time_text, temp_text, precip_text))

        self._attribution_text = tk.StringVar(value="")
        tk.Label(
            self._frame,
            textvariable=self._attribution_text,
            bg=_BACKGROUND,
            fg=_MUTED,
            font=("DejaVu Sans", 13),
            anchor="w",
        ).grid(row=3, column=0, sticky="ew", padx=6, pady=(4, 0))

        self.hide()

    def show(self) -> None:
        """Show the weather viewport."""
        self._frame.grid()

    def hide(self) -> None:
        """Hide the weather viewport."""
        self._frame.grid_remove()

    def update(self, presentation: WeatherPanelPresentation) -> None:
        """Refresh widgets from one immutable presentation."""
        color = weather_status_color(presentation.status)
        self._status_text.set(presentation.detail)
        self._status_label.configure(fg=color)
        self._icon_text.set(presentation.icon)
        self._temperature_text.set(
            f"{presentation.temperature_f} / {presentation.temperature_c}"
        )
        self._condition_text.set(
            f"{presentation.condition}   HUMIDITY {presentation.humidity}"
        )
        self._solar_text.set(
            f"SUNRISE {presentation.sunrise}   SUNSET {presentation.sunset}"
        )
        for variables, hourly in zip(self._hourly_texts, presentation.hourly, strict=True):
            time_text, temp_text, precip_text = variables
            time_text.set(hourly.time)
            temp_text.set(f"{hourly.temperature_f}\n{hourly.temperature_c}")
            precip_text.set(f"RAIN {hourly.precipitation}")
        self._attribution_text.set(presentation.attribution)
