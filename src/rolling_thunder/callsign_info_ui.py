"""Pure callsign-info presentation plus Tk overlay rendering."""

from __future__ import annotations

from base64 import b64encode
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from rolling_thunder.callsign_info import CallsignInfoResponse
from rolling_thunder.live_map import GeoPoint
from rolling_thunder.live_map_service import LiveMapSnapshot
from rolling_thunder.maidenhead import maidenhead_grid_center
from rolling_thunder.map_tiles import MapTileKey, web_mercator_world_pixel

_BACKGROUND = "#080c0f"
_PANEL = "#10191e"
_BORDER = "#45606d"
_BRIGHT = "#ffffff"
_MUTED = "#a8b4ba"
_ACCENT = "#66ccff"
_WEATHER = "#ffd24a"
_FIRST = "#42ff72"


@dataclass(frozen=True, slots=True)
class CallsignInfoPresentation:
    callsign: str
    name: str | None
    license_line: str | None
    identity_lines: tuple[str, ...]
    local_time_text: str
    weather_temperature: str | None
    weather_condition: str | None
    weather_attribution: str | None
    history_heading: str
    history_line: str | None
    target: GeoPoint | None
    pin_visible: bool
    location_note: str | None
    map_zoom: int


def build_callsign_info_presentation(
    response: CallsignInfoResponse,
    *,
    pota_latitude: float | None = None,
    pota_longitude: float | None = None,
    local_time: datetime | None = None,
) -> CallsignInfoPresentation:
    """Build glance-readable overlay text without I/O or timezone guessing."""
    profile = response.profile
    identity: list[str] = []
    name = profile.name if profile is not None else None
    license_line: str | None = None
    if profile is not None:
        if profile.license_class:
            license_line = f"License: {profile.license_class}"
            if profile.license_expiration_date:
                license_line += f"  Exp {profile.license_expiration_date}"
        for value in (profile.address1, profile.address2):
            if value and value not in identity:
                identity.append(value)
        region = ", ".join(
            value for value in (profile.state, profile.country) if value
        )
        if region and region not in identity:
            identity.append(region)
        if profile.grid:
            identity.append(f"Grid {profile.grid.upper()}")
        if profile.birth_year is not None:
            identity.append(f"Born: {profile.birth_year}")

    clock = local_time or datetime.now().astimezone()
    local_time_text = f"LOCAL {clock.strftime('%H:%M')}"

    target: GeoPoint | None = None
    pin_visible = False
    location_note: str | None = None
    if pota_latitude is not None and pota_longitude is not None:
        target = GeoPoint(pota_latitude, pota_longitude)
        pin_visible = True
        zoom = 7
    elif (
        profile is not None
        and profile.latitude is not None
        and profile.longitude is not None
    ):
        target = GeoPoint(profile.latitude, profile.longitude)
        source = (profile.coordinate_source or "").casefold()
        pin_visible = source not in {"state", "dxcc"}
        if source in {"state", "dxcc"}:
            location_note = "COUNTRY / REGION VIEW"
        elif source in {"grid", "zip"}:
            location_note = "APPROX LOCATION"
        zoom = callsign_map_zoom(profile.country, profile.state)
    elif profile is not None and profile.grid:
        try:
            grid_latitude, grid_longitude = maidenhead_grid_center(profile.grid)
        except ValueError:
            zoom = 5
        else:
            target = GeoPoint(grid_latitude, grid_longitude)
            source = (profile.coordinate_source or "").casefold()
            pin_visible = source not in {"state", "dxcc"}
            location_note = (
                "COUNTRY / REGION VIEW"
                if source in {"state", "dxcc"}
                else "APPROX GRID CENTER"
            )
            zoom = callsign_map_zoom(profile.country, profile.state)
    else:
        zoom = 5

    weather_temp = None
    weather_condition = None
    weather_attribution = None
    if response.weather is not None:
        weather_temp = f"{response.weather.temperature_f}°F"
        weather_condition = response.weather.condition
        weather_attribution = response.weather.attribution

    previous = response.last_qso
    if not previous.exists:
        history_heading = "FIRST CONTACT"
        history_line = None
    else:
        history_heading = "LAST CONTACT"
        parts: list[str] = []
        if previous.occurred_at is not None:
            parts.append(previous.occurred_at.astimezone().strftime("%b %d, %Y %H:%M"))
        if previous.station_location:
            label = f"From: {previous.station_location}"
            if previous.mobile is True:
                label += " — MOBILE"
            parts.append(label)
        if previous.pota_reference:
            parts.append(f"Their POTA: {previous.pota_reference}")
        if previous.my_pota_reference:
            parts.append(f"My POTA: {previous.my_pota_reference}")
        if previous.comments:
            parts.append(f"Comment: {previous.comments}")
        elif previous.notes:
            parts.append(f"Comment: {previous.notes}")
        history_line = "    ".join(parts) or None

    return CallsignInfoPresentation(
        callsign=response.callsign,
        name=name,
        license_line=license_line,
        identity_lines=tuple(identity),
        local_time_text=local_time_text,
        weather_temperature=weather_temp,
        weather_condition=weather_condition,
        weather_attribution=weather_attribution,
        history_heading=history_heading,
        history_line=history_line,
        target=target,
        pin_visible=pin_visible,
        location_note=location_note,
        map_zoom=zoom,
    )


def callsign_map_zoom(country: str | None, state: str | None) -> int:
    """Return conservative regional/country framing for the small contact map."""
    normalized_country = (country or "").casefold()
    normalized_state = (state or "").strip().upper()
    if normalized_country in {"united states", "usa", "united states of america"}:
        if normalized_state == "AK":
            return 4
        if normalized_state == "HI":
            return 6
        return 6
    if normalized_country in {
        "canada",
        "australia",
        "brazil",
        "china",
        "russia",
        "russian federation",
    }:
        return 4
    if normalized_country in {"india", "argentina", "mexico", "south africa"}:
        return 5
    return 5


class CallsignInfoOverlayWidgets:
    """Lower-right overlay; consumes only immutable presentation/map snapshots."""

    def __init__(self, parent: Any) -> None:
        import tkinter as tk

        self._tk = tk
        self.frame = tk.Frame(
            parent,
            bg=_BACKGROUND,
            highlightthickness=3,
            highlightbackground=_BORDER,
        )
        self.frame.place(
            relx=1.0,
            rely=1.0,
            anchor="se",
            relwidth=0.80,
            relheight=0.72,
            x=-12,
            y=-12,
        )
        self.frame.place_forget()
        self.frame.grid_columnconfigure(0, weight=1)
        self.frame.grid_columnconfigure(1, weight=3)
        self.frame.grid_rowconfigure(0, weight=5)
        self.frame.grid_rowconfigure(1, weight=3)
        self.frame.grid_rowconfigure(2, weight=1)

        self._map = tk.Canvas(
            self.frame,
            bg="#17242a",
            highlightthickness=0,
        )
        self._map.grid(row=0, column=0, columnspan=2, sticky="nsew")
        self._map_photos: dict[MapTileKey, Any] = {}
        self._map_photo_cache: dict[MapTileKey, tuple[bytes, Any]] = {}

        self._weather_temp = tk.StringVar(value="")
        self._weather_condition = tk.StringVar(value="")
        self._weather_attribution = tk.StringVar(value="")
        weather = tk.Frame(self.frame, bg=_PANEL)
        weather.grid(row=1, column=0, sticky="nsew", padx=(0, 2), pady=(2, 0))
        tk.Label(
            weather,
            text="WEATHER",
            bg=_PANEL,
            fg=_MUTED,
            font=("DejaVu Sans", 28, "bold"),
        ).pack(anchor="w", padx=12, pady=(8, 0))
        tk.Label(
            weather,
            textvariable=self._weather_temp,
            bg=_PANEL,
            fg=_WEATHER,
            font=("DejaVu Sans Mono", 88, "bold"),
        ).pack(anchor="w", padx=12)
        tk.Label(
            weather,
            textvariable=self._weather_condition,
            bg=_PANEL,
            fg=_BRIGHT,
            font=("DejaVu Sans", 34, "bold"),
        ).pack(anchor="w", padx=12)
        tk.Label(
            weather,
            textvariable=self._weather_attribution,
            bg=_PANEL,
            fg=_MUTED,
            font=("DejaVu Sans", 12),
        ).pack(anchor="w", padx=12, pady=(4, 0))

        details = tk.Frame(self.frame, bg=_PANEL)
        details.grid(row=1, column=1, sticky="nsew", padx=(2, 0), pady=(2, 0))
        self._name = tk.StringVar(value="")
        self._license = tk.StringVar(value="")
        self._identity = tk.StringVar(value="")
        tk.Label(
            details,
            textvariable=self._name,
            bg=_PANEL,
            fg=_BRIGHT,
            font=("DejaVu Sans", 40, "bold"),
            anchor="w",
        ).pack(fill="x", padx=12, pady=(7, 0))
        tk.Label(
            details,
            textvariable=self._license,
            bg=_PANEL,
            fg=_BRIGHT,
            font=("DejaVu Sans", 30, "bold"),
            anchor="w",
        ).pack(fill="x", padx=12)
        tk.Label(
            details,
            textvariable=self._identity,
            bg=_PANEL,
            fg=_BRIGHT,
            font=("DejaVu Sans", 30),
            justify="left",
            anchor="w",
        ).pack(fill="x", padx=12)

        history = tk.Frame(self.frame, bg=_PANEL)
        history.grid(
            row=2,
            column=0,
            columnspan=2,
            sticky="nsew",
            pady=(2, 0),
        )
        self._history_heading = tk.StringVar(value="")
        self._history = tk.StringVar(value="")
        self._history_label = tk.Label(
            history,
            textvariable=self._history_heading,
            bg=_PANEL,
            fg=_ACCENT,
            font=("DejaVu Sans", 32, "bold"),
            anchor="w",
        )
        self._history_label.pack(fill="x", padx=14, pady=(5, 0))
        tk.Label(
            history,
            textvariable=self._history,
            bg=_PANEL,
            fg=_BRIGHT,
            font=("DejaVu Sans", 30),
            justify="left",
            anchor="w",
        ).pack(fill="x", padx=14, pady=(0, 5))

    @property
    def map_size(self) -> tuple[int, int]:
        return max(1, self._map.winfo_width()), max(1, self._map.winfo_height())

    def hide(self) -> None:
        self.frame.place_forget()

    def show(
        self,
        presentation: CallsignInfoPresentation,
        map_snapshot: LiveMapSnapshot | None,
    ) -> None:
        self._name.set(
            f"{presentation.callsign} — {presentation.name}"
            if presentation.name
            else presentation.callsign
        )
        self._license.set(presentation.license_line or "")
        self._identity.set("\n".join(presentation.identity_lines))
        self._weather_temp.set(presentation.weather_temperature or "")
        self._weather_condition.set(presentation.weather_condition or "")
        self._weather_attribution.set(presentation.weather_attribution or "")
        self._history_heading.set(presentation.history_heading)
        self._history_label.configure(
            fg=_FIRST if presentation.history_heading == "FIRST CONTACT" else _ACCENT
        )
        self._history.set(presentation.history_line or "")
        self._draw_map(
            map_snapshot,
            presentation.target,
            pin_visible=presentation.pin_visible,
            location_note=presentation.location_note,
            local_time_text=presentation.local_time_text,
        )
        self.frame.place(
            relx=1.0,
            rely=1.0,
            anchor="se",
            relwidth=0.80,
            relheight=0.72,
            x=-12,
            y=-12,
        )
        self.frame.lift()

    def _draw_map(
        self,
        snapshot: LiveMapSnapshot | None,
        target: GeoPoint | None,
        *,
        pin_visible: bool,
        location_note: str | None,
        local_time_text: str,
    ) -> None:
        canvas = self._map
        canvas.delete("all")
        self._map_photos.clear()
        width, height = self.map_size
        if snapshot is not None and snapshot.viewport is not None:
            for tile in snapshot.tiles:
                placement = tile.placement
                if tile.png is None:
                    canvas.create_rectangle(
                        placement.x_px,
                        placement.y_px,
                        placement.x_px + 256,
                        placement.y_px + 256,
                        fill="#17242a",
                        outline="#26363d",
                    )
                    continue
                cached = self._map_photo_cache.get(placement.key)
                if cached is not None and cached[0] == tile.png:
                    photo = cached[1]
                else:
                    photo = self._tk.PhotoImage(
                        data=b64encode(tile.png).decode("ascii")
                    )
                    self._map_photo_cache[placement.key] = (tile.png, photo)
                self._map_photos[placement.key] = photo
                canvas.create_image(
                    placement.x_px,
                    placement.y_px,
                    image=photo,
                    anchor="nw",
                )
            if target is not None and pin_visible:
                target_x, target_y = web_mercator_world_pixel(
                    target,
                    snapshot.viewport.zoom,
                )
                center_x, center_y = web_mercator_world_pixel(
                    snapshot.viewport.center,
                    snapshot.viewport.zoom,
                )
                x = width / 2 + target_x - center_x
                y = height / 2 + target_y - center_y
                canvas.create_oval(
                    x - 18,
                    y - 18,
                    x + 18,
                    y + 18,
                    fill="#ff4d4d",
                    outline="#ffffff",
                    width=4,
                )
        if location_note:
            canvas.create_text(
                10,
                10,
                text=location_note,
                fill=_BRIGHT,
                font=("DejaVu Sans", 20, "bold"),
                anchor="nw",
            )

        canvas.create_text(
            width - 12,
            10,
            text=local_time_text,
            fill="#000000",
            font=("DejaVu Sans", 24, "bold"),
            anchor="ne",
        )

        visible_keys = set(self._map_photos)
        if len(self._map_photo_cache) > 64:
            for key in tuple(self._map_photo_cache):
                if key not in visible_keys:
                    self._map_photo_cache.pop(key, None)
                if len(self._map_photo_cache) <= 64:
                    break

        if not canvas.find_all():
            canvas.create_text(
                width / 2,
                height / 2,
                text="MAP UNAVAILABLE",
                fill=_MUTED,
                font=("DejaVu Sans", 28, "bold"),
            )
