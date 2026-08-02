"""Tkinter presentation adapter for optional POTA enrichment state."""

from __future__ import annotations

import tkinter as tk
from base64 import b64encode
from dataclasses import dataclass
from math import cos, radians

from rolling_thunder.pota_detail_overlay import PotaDetailOverlayState
from rolling_thunder.pota_enrichment import ParkDetailStatus, StateOutline

_BACKGROUND = "#0d1418"
_CARD_BACKGROUND = "#101010"
_MAP_FILL = "#183540"
_MAP_OUTLINE = "#7fd4ff"
_BORDER = "#4a5c66"
_BRIGHT = "#ffffff"
_MUTED = "#a8b4ba"
_FAILURE = "#ff7070"
_MARKER = "#ff4040"
_BADGE = "#203b49"


def format_enriched_callsign(callsign: str, name: str | None) -> str:
    """Return the large POTA-card heading with an optional QRZ name."""
    normalized_name = " ".join(name.split()) if name else ""
    return f"{callsign} - {normalized_name}" if normalized_name else callsign


def weather_symbol(weather_code: int, *, is_day: bool) -> str:
    """Map an Open-Meteo WMO code to one familiar Unicode weather symbol."""
    if weather_code == 0:
        return "☀" if is_day else "☾"
    if weather_code in {1, 2}:
        return "⛅"
    if weather_code in {3, 45, 48}:
        return "☁"
    if weather_code in {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82}:
        return "☂"
    if weather_code in {71, 73, 75, 77, 85, 86}:
        return "❄"
    if weather_code in {95, 96, 99}:
        return "⚡"
    return "☁"


@dataclass(frozen=True)
class _PhotoIdentity:
    callsign: str
    byte_count: int


class PotaDetailOverlayWidgets:
    """Render park location and operator profile over the situational panel."""

    def __init__(self, parent: tk.Misc) -> None:
        self._photo: tk.PhotoImage | None = None
        self._photo_identity: _PhotoIdentity | None = None
        self._current_state = PotaDetailOverlayState(visible=False)

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
            pady=16,
            wraplength=1000,
        ).grid(row=0, column=0, sticky="ew")

        content = tk.Frame(self._frame, bg=_BACKGROUND)
        content.grid(row=1, column=0, sticky="nsew", padx=24, pady=(0, 12))
        content.grid_columnconfigure(0, weight=13, uniform="detail")
        content.grid_columnconfigure(1, weight=7, uniform="detail")
        content.grid_rowconfigure(0, weight=1)

        map_frame = tk.Frame(
            content,
            bg=_CARD_BACKGROUND,
            highlightthickness=2,
            highlightbackground=_BORDER,
        )
        map_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        map_frame.grid_columnconfigure(0, weight=1)
        map_frame.grid_rowconfigure(0, weight=1)

        self._map_canvas = tk.Canvas(
            map_frame,
            bg=_CARD_BACKGROUND,
            highlightthickness=0,
        )
        self._map_canvas.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        self._map_canvas.bind("<Configure>", lambda _event: self._redraw_map())

        profile_frame = tk.Frame(
            content,
            bg=_CARD_BACKGROUND,
            highlightthickness=2,
            highlightbackground=_BORDER,
        )
        profile_frame.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        profile_frame.grid_columnconfigure(0, weight=1)
        profile_frame.grid_rowconfigure(0, weight=1)

        self._profile_image_label = tk.Label(
            profile_frame,
            bg=_BADGE,
            fg=_BRIGHT,
            font=("DejaVu Sans", 42, "bold"),
            anchor="center",
            justify="center",
            text="—",
            wraplength=360,
        )
        self._profile_image_label.grid(
            row=0,
            column=0,
            sticky="nsew",
            padx=10,
            pady=10,
        )

        self._profile_callsign_text = tk.StringVar(value="")
        tk.Label(
            profile_frame,
            textvariable=self._profile_callsign_text,
            bg=_CARD_BACKGROUND,
            fg=_BRIGHT,
            font=("DejaVu Sans", 30, "bold"),
            anchor="center",
            pady=4,
        ).grid(row=1, column=0, sticky="ew")

        self._profile_name_text = tk.StringVar(value="")
        tk.Label(
            profile_frame,
            textvariable=self._profile_name_text,
            bg=_CARD_BACKGROUND,
            fg=_MUTED,
            font=("DejaVu Sans", 23, "bold"),
            anchor="center",
            justify="center",
            wraplength=360,
            padx=8,
            pady=8,
        ).grid(row=2, column=0, sticky="ew")

        weather_row = tk.Frame(self._frame, bg=_BACKGROUND)
        weather_row.grid(row=2, column=0, sticky="ew", padx=24, pady=(4, 20))
        weather_row.grid_columnconfigure(0, weight=1, uniform="weather")
        weather_row.grid_columnconfigure(1, weight=0)
        weather_row.grid_columnconfigure(2, weight=1, uniform="weather")

        self._temperature_text = tk.StringVar(value="Temperature: —")
        tk.Label(
            weather_row,
            textvariable=self._temperature_text,
            bg=_BACKGROUND,
            fg=_BRIGHT,
            font=("DejaVu Sans", 32, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew")

        self._weather_symbol_text = tk.StringVar(value="—")
        tk.Label(
            weather_row,
            textvariable=self._weather_symbol_text,
            bg=_BACKGROUND,
            fg=_BRIGHT,
            font=("DejaVu Sans", 54, "bold"),
            anchor="center",
            padx=28,
        ).grid(row=0, column=1, sticky="ns")

        self._local_time_text = tk.StringVar(value="Local Time: —")
        tk.Label(
            weather_row,
            textvariable=self._local_time_text,
            bg=_BACKGROUND,
            fg=_BRIGHT,
            font=("DejaVu Sans", 32, "bold"),
            anchor="e",
        ).grid(row=0, column=2, sticky="ew")

    def update(self, state: PotaDetailOverlayState) -> None:
        """Show or hide the overlay using only immutable cached state."""
        self._current_state = state
        snapshot = state.snapshot
        if not state.visible or snapshot is None:
            self.hide()
            return

        self._frame.place(relx=0, rely=0, relwidth=1, relheight=1)
        self._frame.lift()
        self._title_text.set(
            f"{snapshot.park_name}    {snapshot.park_reference}"
        )
        self._update_profile(state)
        self._redraw_map()

        if snapshot.status is ParkDetailStatus.LOADING:
            self._temperature_text.set("Temperature: LOADING…")
            self._weather_symbol_text.set("…")
            self._local_time_text.set("Local Time: LOADING…")
            return

        weather = snapshot.weather
        if weather is None:
            self._temperature_text.set("Temperature: NOT AVAILABLE")
            self._weather_symbol_text.set("—")
            self._local_time_text.set("Local Time: NOT AVAILABLE")
        else:
            self._temperature_text.set(
                f"Temperature: {weather.temperature_f:.0f}°F / "
                f"{weather.temperature_c:.0f}°C"
            )
            self._weather_symbol_text.set(
                weather_symbol(weather.weather_code, is_day=weather.is_day)
            )
            self._local_time_text.set(f"Local Time: {weather.local_time}")

    def hide(self) -> None:
        """Remove the overlay and release its Tk image reference."""
        self._frame.place_forget()
        self._photo = None
        self._photo_identity = None
        self._profile_image_label.configure(
            image="",
            text="—",
            bg=_BADGE,
            fg=_BRIGHT,
        )
        self._profile_callsign_text.set("")
        self._profile_name_text.set("")
        self._map_canvas.delete("all")

    def _update_profile(self, state: PotaDetailOverlayState) -> None:
        callsign = state.activator or "—"
        profile = state.profile
        self._profile_callsign_text.set(callsign)
        self._profile_name_text.set(profile.name if profile and profile.name else "")

        photo_png = profile.photo_png if profile is not None else None
        if photo_png is None:
            self._photo = None
            self._photo_identity = None
            self._profile_image_label.configure(
                image="",
                text=callsign,
                bg=_BADGE,
                fg=_BRIGHT,
            )
            return

        identity = _PhotoIdentity(callsign=callsign, byte_count=len(photo_png))
        photo = self._photo
        if identity != self._photo_identity or photo is None:
            encoded = b64encode(photo_png).decode("ascii")
            photo = tk.PhotoImage(data=encoded, format="png")
            self._photo = photo
            self._photo_identity = identity
        self._profile_image_label.configure(
            image=photo,
            text="",
            bg=_CARD_BACKGROUND,
            fg=_BRIGHT,
        )

    def _redraw_map(self) -> None:
        canvas = self._map_canvas
        canvas.delete("all")
        state = self._current_state
        snapshot = state.snapshot
        park = state.park
        if not state.visible or snapshot is None or park is None:
            return

        width = max(canvas.winfo_width(), 20)
        height = max(canvas.winfo_height(), 20)
        outline = snapshot.outline
        if outline is None or park.latitude is None or park.longitude is None:
            message = (
                "MAP LOADING…"
                if snapshot.status is ParkDetailStatus.LOADING
                else "MAP NOT AVAILABLE"
            )
            canvas.create_text(
                width / 2,
                height / 2,
                text=message,
                fill=_MUTED if "LOADING" in message else _FAILURE,
                font=("DejaVu Sans", 30, "bold"),
            )
            return

        normalized_rings = self._normalize_rings(outline, park.longitude)
        if not normalized_rings:
            canvas.create_text(
                width / 2,
                height / 2,
                text="MAP NOT AVAILABLE",
                fill=_FAILURE,
                font=("DejaVu Sans", 30, "bold"),
            )
            return

        all_points = [point for ring in normalized_rings for point in ring]
        mean_latitude = sum(point[1] for point in all_points) / len(all_points)
        longitude_scale = max(cos(radians(mean_latitude)), 0.2)
        projected_rings = [
            [(longitude * longitude_scale, latitude) for longitude, latitude in ring]
            for ring in normalized_rings
        ]
        marker_x = park.longitude * longitude_scale
        marker_y = park.latitude
        xs = [point[0] for ring in projected_rings for point in ring]
        ys = [point[1] for ring in projected_rings for point in ring]
        xs.append(marker_x)
        ys.append(marker_y)
        minimum_x, maximum_x = min(xs), max(xs)
        minimum_y, maximum_y = min(ys), max(ys)
        span_x = max(maximum_x - minimum_x, 0.001)
        span_y = max(maximum_y - minimum_y, 0.001)
        padding = 34.0
        scale = min(
            max((width - 2 * padding) / span_x, 1.0),
            max((height - 2 * padding) / span_y, 1.0),
        )

        def screen(point_x: float, point_y: float) -> tuple[float, float]:
            x = padding + (point_x - minimum_x) * scale
            y = height - padding - (point_y - minimum_y) * scale
            return x, y

        for ring in projected_rings:
            coordinates: list[float] = []
            for point_x, point_y in ring:
                x, y = screen(point_x, point_y)
                coordinates.extend((x, y))
            if len(coordinates) >= 6:
                canvas.create_polygon(
                    coordinates,
                    fill=_MAP_FILL,
                    outline=_MAP_OUTLINE,
                    width=3,
                )

        pin_x, pin_y = screen(marker_x, marker_y)
        canvas.create_line(
            pin_x,
            pin_y - 18,
            pin_x,
            pin_y + 13,
            fill=_MARKER,
            width=5,
        )
        canvas.create_oval(
            pin_x - 10,
            pin_y - 26,
            pin_x + 10,
            pin_y - 6,
            fill=_MARKER,
            outline=_BRIGHT,
            width=3,
        )
        canvas.create_text(
            16,
            14,
            text=f"{outline.state_name.upper()} ({outline.state_code})",
            fill=_BRIGHT,
            font=("DejaVu Sans", 24, "bold"),
            anchor="nw",
        )
        canvas.create_text(
            pin_x,
            min(pin_y + 32, height - 14),
            text=snapshot.park_reference,
            fill=_BRIGHT,
            font=("DejaVu Sans", 18, "bold"),
            anchor="n",
        )

    @staticmethod
    def _normalize_rings(
        outline: StateOutline,
        center_longitude: float,
    ) -> list[list[tuple[float, float]]]:
        normalized: list[list[tuple[float, float]]] = []
        for ring in outline.rings:
            points: list[tuple[float, float]] = []
            for longitude, latitude in ring:
                adjusted = longitude
                while adjusted - center_longitude > 180:
                    adjusted -= 360
                while adjusted - center_longitude < -180:
                    adjusted += 360
                points.append((adjusted, latitude))
            if len(points) >= 3:
                normalized.append(points)
        return normalized
