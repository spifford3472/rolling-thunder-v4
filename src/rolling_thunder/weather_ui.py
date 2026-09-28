"""Tkinter adapter for immutable weather-panel presentation."""

from __future__ import annotations

from typing import Any

from rolling_thunder.weather_alert_panel import (
    WeatherAlertPanelPresentation,
    WeatherAlertPanelStatus,
)
from rolling_thunder.weather_alert_viewport import (
    WeatherAlertViewportPresentation,
)
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


def weather_alert_status_color(
    status: WeatherAlertPanelStatus,
) -> str:
    """Return readable alert status color without implying false applicability."""
    if status is WeatherAlertPanelStatus.ACTIVE:
        return _FAILURE
    if status is WeatherAlertPanelStatus.NO_ACTIVE:
        return _HEALTHY
    if status is WeatherAlertPanelStatus.RETAINED:
        return _WARNING
    return _DISABLED


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
        self._frame.grid_rowconfigure(3, weight=2, minsize=320)

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
                font=("DejaVu Sans", 26, "bold"),
                anchor="center",
            ).grid(row=0, column=0, sticky="ew", pady=(8, 2))

            tk.Label(
                card,
                textvariable=temp_text,
                bg=_CARD_BACKGROUND,
                fg=_BRIGHT,
                font=("DejaVu Sans", 36, "bold"),
                anchor="center",
                justify="center",
            ).grid(row=1, column=0, sticky="nsew", pady=2)

            tk.Label(
                card,
                textvariable=precip_text,
                bg=_CARD_BACKGROUND,
                fg=_MUTED,
                font=("DejaVu Sans", 25, "bold"),
                anchor="center",
            ).grid(row=2, column=0, sticky="ew", pady=(2, 8))

            self._hourly_texts.append((time_text, temp_text, precip_text))

        alerts = tk.Frame(
            self._frame,
            bg=_CARD_BACKGROUND,
            highlightthickness=2,
            highlightbackground=_BORDER,
        )
        alerts.grid(
            row=3,
            column=0,
            sticky="nsew",
            padx=4,
            pady=(6, 4),
        )
        alerts.grid_columnconfigure(0, weight=1)

        tk.Label(
            alerts,
            text="WEATHER ALERTS",
            bg=_CARD_BACKGROUND,
            fg=_BRIGHT,
            font=("DejaVu Sans", 22, "bold"),
            anchor="w",
        ).grid(
            row=0,
            column=0,
            sticky="ew",
            padx=10,
            pady=(6, 0),
        )

        self._alert_status_text = tk.StringVar(
            value="WEATHER ALERTS UNAVAILABLE"
        )
        self._alert_status_label = tk.Label(
            alerts,
            textvariable=self._alert_status_text,
            bg=_CARD_BACKGROUND,
            fg=_DISABLED,
            font=("DejaVu Sans", 28, "bold"),
            anchor="w",
        )
        self._alert_status_label.grid(
            row=1,
            column=0,
            sticky="ew",
            padx=10,
            pady=(1, 1),
        )

        self._alert_primary_text = tk.StringVar(value="")
        tk.Label(
            alerts,
            textvariable=self._alert_primary_text,
            bg=_CARD_BACKGROUND,
            fg=_BRIGHT,
            font=("DejaVu Sans", 34, "bold"),
            justify="left",
            anchor="w",
            wraplength=650,
        ).grid(
            row=2,
            column=0,
            sticky="ew",
            padx=10,
            pady=(1, 1),
        )

        self._alert_secondary_text = tk.StringVar(value="")
        tk.Label(
            alerts,
            textvariable=self._alert_secondary_text,
            bg=_CARD_BACKGROUND,
            fg=_MUTED,
            font=("DejaVu Sans", 28, "bold"),
            justify="left",
            anchor="w",
            wraplength=650,
        ).grid(
            row=3,
            column=0,
            sticky="nsew",
            padx=10,
            pady=(1, 2),
        )
        alerts.grid_rowconfigure(3, weight=1)

        self._alert_scroll_text = tk.StringVar(value="")
        tk.Label(
            alerts,
            textvariable=self._alert_scroll_text,
            bg=_CARD_BACKGROUND,
            fg=_WARNING,
            font=("DejaVu Sans", 20, "bold"),
            justify="left",
            anchor="w",
        ).grid(
            row=4,
            column=0,
            sticky="ew",
            padx=10,
            pady=(1, 6),
        )

        self._attribution_text = tk.StringVar(value="")
        tk.Label(
            self._frame,
            textvariable=self._attribution_text,
            bg=_BACKGROUND,
            fg=_MUTED,
            font=("DejaVu Sans", 13),
            anchor="w",
        ).grid(row=4, column=0, sticky="ew", padx=6, pady=(4, 0))

        self.hide()

    def show(self) -> None:
        """Show the weather viewport."""
        self._frame.grid()

    def hide(self) -> None:
        """Hide the weather viewport."""
        self._frame.grid_remove()

    def update(
        self,
        presentation: WeatherPanelPresentation,
        alert_presentation: WeatherAlertPanelPresentation,
        alert_viewport: WeatherAlertViewportPresentation,
    ) -> None:
        """Refresh weather and alert widgets from immutable presentations."""
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
        alert_color = weather_alert_status_color(
            alert_presentation.status
        )
        self._alert_status_text.set(
            alert_presentation.status_line
        )
        self._alert_status_label.configure(
            fg=alert_color
        )

        if alert_presentation.items:
            item = alert_presentation.items[0]
            more_count = (
                alert_presentation.active_count
                - len(alert_presentation.items)
            )
            more_text = (
                f"  +{more_count} MORE"
                if more_count > 0
                else ""
            )

            self._alert_primary_text.set(
                f"{item.event} • {item.severity} "
                f"• UNTIL {item.expires}{more_text}"
            )
            self._alert_secondary_text.set(alert_viewport.text)
        elif (
            alert_presentation.status
            is WeatherAlertPanelStatus.NO_ACTIVE
        ):
            self._alert_primary_text.set(
                "VERIFIED CURRENT LOCATION"
            )
            self._alert_secondary_text.set("")
        elif (
            alert_presentation.status
            is WeatherAlertPanelStatus.RETAINED
        ):
            self._alert_primary_text.set(
                "NO KNOWN ACTIVE ALERTS "
                "IN LAST VERIFIED SNAPSHOT"
            )
            self._alert_secondary_text.set("")
        else:
            self._alert_primary_text.set("")
            self._alert_secondary_text.set("")

        directions = []
        if alert_viewport.can_scroll_up:
            directions.append("▲")
        if alert_viewport.can_scroll_down:
            directions.append("▼")
        self._alert_scroll_text.set(
            f"ROTATE TO SCROLL ALERT  {' '.join(directions)}"
            if alert_presentation.items and alert_viewport.overflowing
            else ""
        )

        attributions = tuple(
            value
            for value in (
                presentation.attribution,
                alert_presentation.attribution,
            )
            if value
        )
        self._attribution_text.set(
            " • ".join(dict.fromkeys(attributions))
        )
