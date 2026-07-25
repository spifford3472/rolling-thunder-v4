"""Full-screen Raspberry Pi dashboard entry point."""

from pathlib import Path
from typing import Any

from rolling_thunder.application_runtime import ApplicationRuntime
from rolling_thunder.config import ConfigurationError, load_config
from rolling_thunder.dashboard_state import build_dashboard_state
from rolling_thunder.main import DEFAULT_CONFIG_PATH
from rolling_thunder.radio import RadioConnectionError

_REFRESH_MS = 250


def _value_row(parent: Any, tk: Any, label: str, row: int) -> Any:
    tk.Label(
        parent,
        text=label,
        bg="#101010",
        fg="#9aa0a6",
        font=("DejaVu Sans", 15, "bold"),
        anchor="w",
    ).grid(row=row, column=0, sticky="w", padx=(18, 8), pady=5)
    value = tk.StringVar(value="—")
    tk.Label(
        parent,
        textvariable=value,
        bg="#101010",
        fg="white",
        font=("DejaVu Sans", 20, "bold"),
        anchor="e",
    ).grid(row=row, column=1, sticky="ew", padx=(8, 18), pady=5)
    return value


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
    root.configure(bg="#080808")
    root.attributes("-fullscreen", True)
    root.grid_columnconfigure(0, weight=2, uniform="dashboard")
    root.grid_columnconfigure(1, weight=3, uniform="dashboard")
    root.grid_rowconfigure(0, weight=1)
    root.grid_rowconfigure(1, weight=0)

    left = tk.Frame(root, bg="#101010", highlightthickness=1, highlightbackground="#303030")
    left.grid(row=0, column=0, sticky="nsew")
    left.grid_columnconfigure(0, weight=0)
    left.grid_columnconfigure(1, weight=1)
    left.grid_rowconfigure(9, weight=1)

    tk.Label(
        left,
        text="LOGGER",
        bg="#1b1b1b",
        fg="#ffffff",
        font=("DejaVu Sans", 24, "bold"),
        anchor="w",
        padx=18,
        pady=12,
    ).grid(row=0, column=0, columnspan=2, sticky="ew")

    fields = {
        "pending_callsign": _value_row(left, tk, "Pending Callsign", 1),
        "voice_state": _value_row(left, tk, "Voice", 2),
        "radio_state": _value_row(left, tk, "Radio", 3),
        "frequency": _value_row(left, tk, "Frequency", 4),
        "band": _value_row(left, tk, "Band", 5),
        "mode": _value_row(left, tk, "Mode", 6),
        "commit_state": _value_row(left, tk, "Commit", 7),
        "last_result": _value_row(left, tk, "Last Result", 8),
    }

    context = tk.Frame(left, bg="#151515", highlightthickness=1, highlightbackground="#303030")
    context.grid(row=9, column=0, columnspan=2, sticky="nsew", padx=12, pady=12)
    tk.Label(
        context,
        text="CONTEXT",
        bg="#1b1b1b",
        fg="white",
        font=("DejaVu Sans", 20, "bold"),
        anchor="w",
        padx=14,
        pady=10,
    ).pack(fill="x")
    tk.Label(
        context,
        text="POTA   DX   REPEATERS   AI   SETTINGS\n\nContext services arrive in later milestones.",
        bg="#151515",
        fg="#b8b8b8",
        font=("DejaVu Sans", 16),
        justify="left",
        anchor="nw",
        padx=14,
        pady=14,
    ).pack(fill="both", expand=True)

    situational = tk.Frame(root, bg="#0d1418", highlightthickness=1, highlightbackground="#303030")
    situational.grid(row=0, column=1, sticky="nsew")
    tk.Label(
        situational,
        text="SITUATIONAL AREA",
        bg="#142027",
        fg="white",
        font=("DejaVu Sans", 24, "bold"),
        anchor="w",
        padx=20,
        pady=12,
    ).pack(fill="x")
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
        fg="#ffffff",
        font=("DejaVu Sans", 16, "bold"),
        anchor="w",
        padx=18,
        pady=10,
    )
    ticker.grid(row=1, column=0, columnspan=2, sticky="ew")

    def refresh() -> None:
        view = build_dashboard_state(runtime.latest_radio_state)
        for name, variable in fields.items():
            variable.set(getattr(view, name))
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
