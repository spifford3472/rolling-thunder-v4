"""Dashboard presentation for the parked receive-only WSPR panel."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rolling_thunder.wspr_receive import WsprExtreme, WsprSnapshot

if TYPE_CHECKING:
    import tkinter as tk


def _distance(extreme: WsprExtreme | None) -> str:
    return "—" if extreme is None else f"{extreme.callsign}  {extreme.miles:,.0f} mi"


class WsprWidgets:
    """Render only immutable presentation data on Tk."""

    def __init__(self, parent: tk.Misc, *, background: str, foreground: str) -> None:
        import tkinter as tk

        self._frame = tk.Frame(parent, bg=background, padx=12, pady=6)
        self._frame.grid_columnconfigure(0, weight=1)
        self.visible = False
        self._activity = tk.StringVar(value="")
        self._timer = tk.StringVar(value="")
        self._stats = tk.StringVar(value="")
        self._details = tk.StringVar(value="")
        labels: list[tuple[tk.Label, int, str]] = []
        last_scale = 0.0
        self._frame.grid_propagate(False)
        for row, (text, size, weight) in enumerate((
            (self._activity, 34, "bold"),
            (self._timer, 64, "bold"),
            (self._stats, 32, "normal"),
            (self._details, 27, "normal"),
        )):
            label = tk.Label(
                self._frame, bg=background, fg=foreground, textvariable=text,
                font=("DejaVu Sans", size, weight), justify="left", anchor="w",
            )
            label.grid(row=row, column=0, sticky="ew", pady=3)
            labels.append((label, size, weight))

        def resize(event: tk.Event[tk.Frame]) -> None:
            nonlocal last_scale
            scale = max(0.40, min(1.0, (event.width - 24) / 900, event.height / 510))
            for label, size, weight in labels:
                label.configure(wraplength=max(100, event.width - 24))
                if scale != last_scale:
                    label.configure(font=("DejaVu Sans", round(size * scale), weight))
            last_scale = scale

        self._frame.bind("<Configure>", resize)

    def show(self) -> None:
        self._frame.grid(row=1, column=0, sticky="nsew")
        self.visible = True

    def hide(self) -> None:
        self._frame.grid_remove()
        self.visible = False

    def update(self, state: WsprSnapshot) -> None:
        band = f" · {state.band}" if state.band else ""
        self._set(self._activity, state.detail + band)
        minutes, seconds = divmod(int(state.elapsed_s), 60)
        hours, minutes = divmod(minutes, 60)
        self._set(self._timer, f"{hours:02}:{minutes:02}:{seconds:02}")
        counts = [f"{name}   {count}" for name, count in state.band_totals]
        self._set(self._stats, "\n".join((
            f"{state.decodes_per_hour:,.1f} decodes/hour today",
            "    ".join(counts[:4]),
            "    ".join(counts[4:]),
            f"Closest posted    {_distance(state.closest)}",
            f"Farthest posted   {_distance(state.farthest)}",
        )))
        self._set(self._details, "\n".join((
            f"Upload  {state.upload}",
            f"Receiver grid  {state.grid or '—'}",
            "Running may publish your callsign and grid.",
            "Button 3  Run     Button 2  Stop",
        )))

    @staticmethod
    def _set(variable: tk.StringVar, value: str) -> None:
        if variable.get() != value:
            variable.set(value)
