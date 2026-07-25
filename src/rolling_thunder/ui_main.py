"""Full-screen Raspberry Pi dashboard entry point."""

from pathlib import Path

from rolling_thunder.application_runtime import ApplicationRuntime
from rolling_thunder.config import ConfigurationError, load_config
from rolling_thunder.dashboard_state import build_dashboard_state
from rolling_thunder.main import DEFAULT_CONFIG_PATH
from rolling_thunder.radio import RadioConnectionError

_REFRESH_MS = 250
_BACKGROUND = "#080808"
_PANEL_BACKGROUND = "#101010"
_SECONDARY_BACKGROUND = "#151515"
_BORDER = "#303030"
_BRIGHT = "#ffffff"
_DISABLED = "#777777"
_SUCCESS = "#42ff72"
_FAILURE = "#ff3b3b"
_MUTED = "#a8a8a8"


def _indicator_color(value: str) -> str:
    """Return the visual color for a compact operator-state indicator."""
    normalized = value.upper()
    if normalized in {"DISABLED", "UNAVAILABLE", "OFF"}:
        return _DISABLED
    if normalized in {"COMMITTED", "SUCCESS"}:
        return _SUCCESS
    if normalized in {"FAILED", "FAILURE", "ERROR"}:
        return _FAILURE
    return _BRIGHT


def run_dashboard(config_path: Path = DEFAULT_CONFIG_PATH) -> int:
    """Load configuration and run the persistent dashboard until closed."""
    try:
        import tkinter as tk
    except ImportError as error:
        raise RuntimeError(
            "Tkinter is required for the Pi dashboard. Install python3-tk."
        ) from error

    try:
        config = load_config(config_path)
    except ConfigurationError as error:
        print(f"Rolling Thunder configuration error: {error}")
        return 2

    runtime = ApplicationRuntime.from_config(config)
    try:
        runtime.start()
    except (RadioConnectionError, RuntimeError, ValueError) as error:
        print(f"Rolling Thunder startup error: {error}")
        return 3

    root = tk.Tk()
    root.title("Rolling Thunder v4")
    root.configure(bg=_BACKGROUND)
    root.attributes("-fullscreen", True)
    root.grid_columnconfigure(0, weight=2, uniform="dashboard")
    root.grid_columnconfigure(1, weight=3, uniform="dashboard")
    root.grid_rowconfigure(0, weight=1)
    root.grid_rowconfigure(1, weight=0)

    left = tk.Frame(
        root,
        bg=_PANEL_BACKGROUND,
        highlightthickness=1,
        highlightbackground=_BORDER,
    )
    left.grid(row=0, column=0, sticky="nsew")
    left.grid_columnconfigure(0, weight=1)
    left.grid_rowconfigure(0, weight=1, uniform="left-column")
    left.grid_rowconfigure(1, weight=2, uniform="left-column")

    logger = tk.Frame(left, bg=_PANEL_BACKGROUND)
    logger.grid(row=0, column=0, sticky="nsew", padx=14, pady=(8, 4))
    logger.grid_columnconfigure(0, weight=1)
    logger.grid_columnconfigure(1, weight=1)
    logger.grid_rowconfigure(0, weight=4)
    logger.grid_rowconfigure(1, weight=2)
    logger.grid_rowconfigure(3, weight=2)
    logger.grid_rowconfigure(4, weight=1)
    logger.grid_rowconfigure(6, weight=2)

    callsign_text = tk.StringVar(value="CALLSIGN: —")
    tk.Label(
        logger,
        textvariable=callsign_text,
        bg=_PANEL_BACKGROUND,
        fg=_BRIGHT,
        font=("DejaVu Sans", 58, "bold"),
        anchor="center",
    ).grid(row=0, column=0, columnspan=2, sticky="nsew", pady=0)

    voice_text = tk.StringVar(value="VOICE")
    voice_label = tk.Label(
        logger,
        textvariable=voice_text,
        bg=_PANEL_BACKGROUND,
        fg=_DISABLED,
        font=("DejaVu Sans", 36, "bold"),
        anchor="center",
    )
    voice_label.grid(row=1, column=0, sticky="nsew", padx=8, pady=0)

    commit_text = tk.StringVar(value="COMMIT")
    commit_label = tk.Label(
        logger,
        textvariable=commit_text,
        bg=_PANEL_BACKGROUND,
        fg=_DISABLED,
        font=("DejaVu Sans", 36, "bold"),
        anchor="center",
    )
    commit_label.grid(row=1, column=1, sticky="nsew", padx=8, pady=0)

    tk.Frame(logger, bg=_BORDER, height=3).grid(
        row=2,
        column=0,
        columnspan=2,
        sticky="ew",
        pady=(2, 2),
    )

    frequency_text = tk.StringVar(value="---.--- MHz")
    tk.Label(
        logger,
        textvariable=frequency_text,
        bg=_PANEL_BACKGROUND,
        fg=_BRIGHT,
        font=("DejaVu Sans", 44, "bold"),
        anchor="center",
    ).grid(row=3, column=0, columnspan=2, sticky="nsew", pady=0)

    band_text = tk.StringVar(value="--")
    tk.Label(
        logger,
        textvariable=band_text,
        bg=_PANEL_BACKGROUND,
        fg=_BRIGHT,
        font=("DejaVu Sans", 30, "bold"),
        anchor="w",
    ).grid(row=4, column=0, sticky="ew", padx=(10, 5), pady=0)

    mode_text = tk.StringVar(value="--")
    tk.Label(
        logger,
        textvariable=mode_text,
        bg=_PANEL_BACKGROUND,
        fg=_BRIGHT,
        font=("DejaVu Sans", 30, "bold"),
        anchor="e",
    ).grid(row=4, column=1, sticky="ew", padx=(5, 10), pady=0)

    tk.Frame(logger, bg=_BORDER, height=2).grid(
        row=5,
        column=0,
        columnspan=2,
        sticky="ew",
        pady=(2, 1),
    )

    last_result_text = tk.StringVar(value="Last Result: —")
    tk.Label(
        logger,
        textvariable=last_result_text,
        bg=_PANEL_BACKGROUND,
        fg=_MUTED,
        font=("DejaVu Sans", 42, "bold"),
        anchor="w",
    ).grid(row=6, column=0, columnspan=2, sticky="nsew", padx=6, pady=0)

    context = tk.Frame(
        left,
        bg=_SECONDARY_BACKGROUND,
        highlightthickness=1,
        highlightbackground=_BORDER,
    )
    context.grid(row=1, column=0, sticky="nsew", padx=12, pady=(4, 12))
    tk.Label(
        context,
        text="POTA   DX   REPEATERS   AI   SETTINGS\n\nContext services arrive in later milestones.",
        bg=_SECONDARY_BACKGROUND,
        fg="#b8b8b8",
        font=("DejaVu Sans", 16),
        justify="left",
        anchor="nw",
        padx=14,
        pady=14,
    ).pack(fill="both", expand=True)

    situational = tk.Frame(
        root,
        bg="#0d1418",
        highlightthickness=1,
        highlightbackground=_BORDER,
    )
    situational.grid(row=0, column=1, sticky="nsew")
    tk.Label(
        situational,
        text="MAP / FUTURE CARDS\n\nReserved for mapping and operating intelligence.",
        bg="#0d1418",
        fg="#83939c",
        font=("DejaVu Sans", 22, "bold"),
        justify="center",
    ).pack(fill="both", expand=True)

    ticker_text = tk.StringVar(value="STARTING ROLLING THUNDER")
    ticker = tk.Label(
        root,
        textvariable=ticker_text,
        bg="#202020",
        fg=_BRIGHT,
        font=("DejaVu Sans", 16, "bold"),
        anchor="w",
        padx=18,
        pady=10,
    )
    ticker.grid(row=1, column=0, columnspan=2, sticky="ew")

    def refresh() -> None:
        view = build_dashboard_state(runtime.latest_radio_state)
        callsign_text.set(f"CALLSIGN: {view.pending_callsign}")
        voice_text.set("VOICE")
        voice_label.configure(fg=_indicator_color(view.voice_state))
        commit_text.set("COMMIT")
        commit_label.configure(fg=_indicator_color(view.commit_state))
        frequency_text.set(view.frequency)
        band_text.set(view.band.replace(" ", ""))
        mode_text.set(view.mode)
        last_result = view.last_result if view.last_result != "—" else "—"
        last_result_text.set(f"Last Result: {last_result[:18]}")
        ticker_text.set(view.ticker)
        root.after(_REFRESH_MS, refresh)

    def close() -> None:
        runtime.stop()
        root.destroy()

    root.bind("<Escape>", lambda _event: close())
    root.protocol("WM_DELETE_WINDOW", close)
    refresh()
    root.mainloop()
    return 0


def main() -> int:
    """Console-script wrapper for the full-screen dashboard."""
    return run_dashboard()


if __name__ == "__main__":
    raise SystemExit(main())
