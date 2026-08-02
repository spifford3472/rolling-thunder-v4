"""Tkinter presentation adapter for optional POTA enrichment state."""

from __future__ import annotations

import tkinter as tk
from base64 import b64encode
from dataclasses import dataclass

from rolling_thunder.pota_detail_overlay import PotaDetailOverlayState
from rolling_thunder.pota_enrichment import ParkDetailStatus

_BACKGROUND = "#0d1418"
_CARD_BACKGROUND = "#101010"
_BORDER = "#4a5c66"
_BRIGHT = "#ffffff"
_MUTED = "#a8b4ba"
_FAILURE = "#ff7070"

_RAIN_CODES = frozenset({51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82})
_SNOW_CODES = frozenset({71, 73, 75, 77, 85, 86})
_THUNDERSTORM_CODES = frozenset({95, 96, 99})
_CLOUD_CODES = frozenset({3, 45, 48})


def format_enriched_callsign(callsign: str, name: str | None) -> str:
    """Return the large POTA-card heading with an optional QRZ name."""
    normalized_name = " ".join(name.split()) if name else ""
    return f"{callsign} - {normalized_name}" if normalized_name else callsign


def weather_symbol(weather_code: int, *, is_day: bool) -> str:
    """Map an Open-Meteo WMO code to one familiar weather symbol."""
    if weather_code in {0, 1}:
        return "☀" if is_day else "☾"
    if weather_code == 2:
        return "⛅" if is_day else "☁"
    if weather_code in _CLOUD_CODES:
        return "☁"
    if weather_code in _RAIN_CODES:
        return "☂"
    if weather_code in _SNOW_CODES:
        return "❄"
    if weather_code in _THUNDERSTORM_CODES:
        return "⚡"
    return "☁"


@dataclass(frozen=True)
class _ImageIdentity:
    park_reference: str
    source_url: str
    byte_count: int


class PotaDetailOverlayWidgets:
    """Render park detail state over the reserved situational panel."""

    def __init__(self, parent: tk.Misc) -> None:
        self._photo: tk.PhotoImage | None = None
        self._image_identity: _ImageIdentity | None = None

        self._frame = tk.Frame(
            parent,
            bg=_BACKGROUND,
            highlightthickness=4,
            highlightbackground=_BORDER,
        )
        self._frame.grid_columnconfigure(0, weight=1)
        self._frame.grid_rowconfigure(1, weight=1)

        self._title_text = tk.StringVar(value="PARK NAME: —")
        tk.Label(
            self._frame,
            textvariable=self._title_text,
            bg=_BACKGROUND,
            fg=_BRIGHT,
            font=("DejaVu Sans", 38, "bold"),
            anchor="w",
            justify="left",
            padx=24,
            pady=18,
            wraplength=1000,
        ).grid(row=0, column=0, sticky="ew")

        self._image_frame = tk.Frame(
            self._frame,
            bg=_CARD_BACKGROUND,
            highlightthickness=2,
            highlightbackground=_BORDER,
        )
        self._image_frame.grid(
            row=1,
            column=0,
            sticky="nsew",
            padx=24,
            pady=(0, 10),
        )
        self._image_frame.grid_columnconfigure(0, weight=1)
        self._image_frame.grid_rowconfigure(0, weight=1)

        self._image_label = tk.Label(
            self._image_frame,
            bg=_CARD_BACKGROUND,
            fg=_MUTED,
            font=("DejaVu Sans", 34, "bold"),
            anchor="center",
            justify="center",
            text="LOADING…",
        )
        self._image_label.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)

        self._attribution_text = tk.StringVar(value="")
        tk.Label(
            self._image_frame,
            textvariable=self._attribution_text,
            bg=_CARD_BACKGROUND,
            fg=_MUTED,
            font=("DejaVu Sans", 16),
            anchor="center",
            justify="center",
            wraplength=1000,
            padx=12,
            pady=6,
        ).grid(row=1, column=0, sticky="ew")

        weather_row = tk.Frame(self._frame, bg=_BACKGROUND)
        weather_row.grid(row=2, column=0, sticky="ew", padx=24, pady=(10, 22))
        weather_row.grid_columnconfigure(0, weight=3)
        weather_row.grid_columnconfigure(1, weight=1)
        weather_row.grid_columnconfigure(2, weight=2)

        self._temperature_text = tk.StringVar(value="Temperature: —")
        tk.Label(
            weather_row,
            textvariable=self._temperature_text,
            bg=_BACKGROUND,
            fg=_BRIGHT,
            font=("DejaVu Sans", 34, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew")

        self._weather_icon_text = tk.StringVar(value="—")
        tk.Label(
            weather_row,
            textvariable=self._weather_icon_text,
            bg=_BACKGROUND,
            fg=_BRIGHT,
            font=("DejaVu Sans", 58, "bold"),
            anchor="center",
        ).grid(row=0, column=1, sticky="ew", padx=16)

        self._local_time_text = tk.StringVar(value="Local Time: —")
        tk.Label(
            weather_row,
            textvariable=self._local_time_text,
            bg=_BACKGROUND,
            fg=_BRIGHT,
            font=("DejaVu Sans", 34, "bold"),
            anchor="e",
        ).grid(row=0, column=2, sticky="ew")

    def update(self, state: PotaDetailOverlayState) -> None:
        """Show or hide the overlay using only immutable cached state."""
        snapshot = state.snapshot
        if not state.visible or snapshot is None:
            self.hide()
            return

        self._frame.place(relx=0, rely=0, relwidth=1, relheight=1)
        self._frame.lift()
        self._title_text.set(f"PARK NAME: {snapshot.park_name}")

        if snapshot.status is ParkDetailStatus.LOADING:
            self._show_text_image("LOADING…", _MUTED)
            self._temperature_text.set("Temperature: LOADING…")
            self._weather_icon_text.set("…")
            self._local_time_text.set("Local Time: LOADING…")
            return

        if snapshot.image is None:
            self._show_text_image("NOT AVAILABLE", _FAILURE)
        else:
            identity = _ImageIdentity(
                park_reference=snapshot.park_reference,
                source_url=snapshot.image.source_url,
                byte_count=len(snapshot.image.png_bytes),
            )
            photo = self._photo
            if identity != self._image_identity or photo is None:
                encoded = b64encode(snapshot.image.png_bytes).decode("ascii")
                photo = tk.PhotoImage(data=encoded, format="png")
                self._photo = photo
                self._image_identity = identity
            assert photo is not None
            self._image_label.configure(
                image=photo,
                text="",
                fg=_BRIGHT,
            )
            self._attribution_text.set(
                f"{snapshot.image.attribution} · {snapshot.image.license_name}"
            )

        weather = snapshot.weather
        if weather is None:
            self._temperature_text.set("Temperature: NOT AVAILABLE")
            self._weather_icon_text.set("—")
            self._local_time_text.set("Local Time: NOT AVAILABLE")
        else:
            self._temperature_text.set(
                "Temperature: "
                f"{weather.temperature_f:.0f}°F / {weather.temperature_c:.0f}°C"
            )
            self._weather_icon_text.set(
                weather_symbol(weather.weather_code, is_day=weather.is_day)
            )
            self._local_time_text.set(f"Local Time: {weather.local_time}")

    def hide(self) -> None:
        """Remove the overlay and release its Tk image reference."""
        self._frame.place_forget()
        self._photo = None
        self._image_identity = None
        self._image_label.configure(image="", text="LOADING…", fg=_MUTED)
        self._attribution_text.set("")
        self._weather_icon_text.set("—")

    def _show_text_image(self, text: str, foreground: str) -> None:
        self._photo = None
        self._image_identity = None
        self._image_label.configure(image="", text=text, fg=foreground)
        self._attribution_text.set("")
