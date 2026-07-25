"""Full-screen Raspberry Pi dashboard entry point."""

from pathlib import Path

from rolling_thunder.application_runtime import ApplicationRuntime
from rolling_thunder.callsign_capture import CallsignCaptureState, MockTranscriptController
from rolling_thunder.config import ConfigurationError, load_config
from rolling_thunder.contact_commit_controller import ContactCommitController
from rolling_thunder.dashboard_state import build_dashboard_state
from rolling_thunder.live_callsign_capture import LiveCallsignCaptureController
from rolling_thunder.main import DEFAULT_CONFIG_PATH
from rolling_thunder.radio import RadioConnectionError
from rolling_thunder.speech_recognition import VoskCallsignRecognizer

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


def _callsign_font_size(callsign: str) -> int:
    """Keep common and portable callsigns as large as the panel permits."""
    length = len(callsign)
    if length <= 7:
        return 72
    if length <= 10:
        return 62
    if length <= 13:
        return 52
    return 44


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

    mock_transcripts = MockTranscriptController()
    live_capture: LiveCallsignCaptureController | None = None
    if config.speech.enabled:
        model_path = config.speech.model_path
        if model_path is None:
            print("Rolling Thunder startup error: speech model path is unavailable")
            runtime.stop()
            return 3
        recognizer = VoskCallsignRecognizer(
            model_path=model_path,
            audio_device=config.speech.audio_device,
            duration_s=config.speech.capture_duration_seconds,
            sample_rate=config.speech.sample_rate,
        )
        live_capture = LiveCallsignCaptureController(recognizer)

    def capture_state() -> CallsignCaptureState:
        """Return the active mock or live capture presentation state."""
        if live_capture is not None:
            return live_capture.state
        return mock_transcripts.state

    def start_voice_capture() -> None:
        """Start live recognition or advance the deterministic mock fixture."""
        if live_capture is not None:
            live_capture.start_capture()
        else:
            mock_transcripts.capture_next()

    def discard_capture() -> None:
        """Discard the current pending callsign without logging it."""
        if live_capture is not None:
            live_capture.discard()
        else:
            mock_transcripts.discard()

    def commit_started(callsign: str) -> None:
        if live_capture is not None:
            live_capture.commit_started(callsign)
        else:
            mock_transcripts.commit_started(callsign)

    def commit_succeeded(callsign: str) -> None:
        if live_capture is not None:
            live_capture.commit_succeeded(callsign)
        else:
            mock_transcripts.commit_succeeded(callsign)

    def commit_failed(message: str) -> None:
        if live_capture is not None:
            live_capture.commit_failed(message)
        else:
            mock_transcripts.commit_failed(message)

    contact_commit = ContactCommitController(
        runtime.contact_logging,
        on_started=commit_started,
        on_succeeded=commit_succeeded,
        on_failed=commit_failed,
    )

    def commit_capture() -> None:
        """Start a durable Commit using immutable callsign and radio snapshots."""
        state = capture_state()
        if state.commit_state != "READY" or not state.pending_callsign:
            return
        contact_commit.start_commit(
            state.pending_callsign,
            runtime.latest_radio_state,
        )

    root = tk.Tk()
    root.title("Rolling Thunder v4")
    root.configure(bg=_BACKGROUND, cursor="none")
    root.attributes("-fullscreen", True)
    root.grid_columnconfigure(0, weight=2, uniform="dashboard")
    root.grid_columnconfigure(1, weight=3, uniform="dashboard")
    root.grid_rowconfigure(0, weight=1)
    root.grid_rowconfigure(1, weight=0)

    left = tk.Frame(root, bg=_PANEL_BACKGROUND, highlightthickness=1, highlightbackground=_BORDER)
    left.grid(row=0, column=0, sticky="nsew")
    left.grid_columnconfigure(0, weight=1)
    left.grid_rowconfigure(0, weight=1, uniform="left-column")
    left.grid_rowconfigure(1, weight=2, uniform="left-column")

    logger = tk.Frame(left, bg=_PANEL_BACKGROUND)
    logger.grid(row=0, column=0, sticky="nsew", padx=14, pady=(8, 4))
    logger.grid_columnconfigure(0, weight=1)
    logger.grid_columnconfigure(1, weight=1)
    logger.grid_rowconfigure(1, weight=4)
    logger.grid_rowconfigure(2, weight=2)
    logger.grid_rowconfigure(4, weight=2)
    logger.grid_rowconfigure(5, weight=1)
    logger.grid_rowconfigure(7, weight=2)

    callsign_prompt_text = tk.StringVar(value="CALLSIGN")
    tk.Label(logger, textvariable=callsign_prompt_text, bg=_PANEL_BACKGROUND, fg=_MUTED, font=("DejaVu Sans", 18, "bold"), anchor="center").grid(row=0, column=0, columnspan=2, sticky="ew", pady=0)

    callsign_text = tk.StringVar(value="")
    callsign_label = tk.Label(logger, textvariable=callsign_text, bg=_PANEL_BACKGROUND, fg=_BRIGHT, font=("DejaVu Sans", 72, "bold"), anchor="center")
    callsign_label.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=0)

    voice_text = tk.StringVar(value="VOICE")
    voice_label = tk.Label(logger, textvariable=voice_text, bg=_PANEL_BACKGROUND, fg=_DISABLED, font=("DejaVu Sans", 36, "bold"), anchor="center")
    voice_label.grid(row=2, column=0, sticky="nsew", padx=8, pady=0)

    commit_text = tk.StringVar(value="COMMIT")
    commit_label = tk.Label(logger, textvariable=commit_text, bg=_PANEL_BACKGROUND, fg=_DISABLED, font=("DejaVu Sans", 36, "bold"), anchor="center")
    commit_label.grid(row=2, column=1, sticky="nsew", padx=8, pady=0)

    tk.Frame(logger, bg=_BORDER, height=3).grid(row=3, column=0, columnspan=2, sticky="ew", pady=(2, 2))

    frequency_text = tk.StringVar(value="---.--- MHz")
    tk.Label(logger, textvariable=frequency_text, bg=_PANEL_BACKGROUND, fg=_BRIGHT, font=("DejaVu Sans", 44, "bold"), anchor="center").grid(row=4, column=0, columnspan=2, sticky="nsew", pady=0)

    band_text = tk.StringVar(value="--")
    tk.Label(logger, textvariable=band_text, bg=_PANEL_BACKGROUND, fg=_BRIGHT, font=("DejaVu Sans", 30, "bold"), anchor="w").grid(row=5, column=0, sticky="ew", padx=(10, 5), pady=0)

    mode_text = tk.StringVar(value="--")
    tk.Label(logger, textvariable=mode_text, bg=_PANEL_BACKGROUND, fg=_BRIGHT, font=("DejaVu Sans", 30, "bold"), anchor="e").grid(row=5, column=1, sticky="ew", padx=(5, 10), pady=0)

    tk.Frame(logger, bg=_BORDER, height=2).grid(row=6, column=0, columnspan=2, sticky="ew", pady=(2, 1))

    last_result_text = tk.StringVar(value="Last Result: —")
    tk.Label(logger, textvariable=last_result_text, bg=_PANEL_BACKGROUND, fg=_MUTED, font=("DejaVu Sans", 42, "bold"), anchor="w").grid(row=7, column=0, columnspan=2, sticky="nsew", padx=6, pady=0)

    context = tk.Frame(left, bg=_SECONDARY_BACKGROUND, highlightthickness=1, highlightbackground=_BORDER)
    context.grid(row=1, column=0, sticky="nsew", padx=12, pady=(4, 12))
    tk.Label(context, text="POTA   DX   REPEATERS   AI   SETTINGS\n\nContext services arrive in later milestones.", bg=_SECONDARY_BACKGROUND, fg="#b8b8b8", font=("DejaVu Sans", 16), justify="left", anchor="nw", padx=14, pady=14).pack(fill="both", expand=True)

    situational = tk.Frame(root, bg="#0d1418", highlightthickness=1, highlightbackground=_BORDER)
    situational.grid(row=0, column=1, sticky="nsew")
    tk.Label(situational, text="MAP / FUTURE CARDS\n\nReserved for mapping and operating intelligence.", bg="#0d1418", fg="#83939c", font=("DejaVu Sans", 22, "bold"), justify="center").pack(fill="both", expand=True)

    ticker_text = tk.StringVar(value="STARTING ROLLING THUNDER")
    ticker = tk.Label(root, textvariable=ticker_text, bg="#202020", fg=_BRIGHT, font=("DejaVu Sans", 16, "bold"), anchor="w", padx=18, pady=10)
    ticker.grid(row=1, column=0, columnspan=2, sticky="ew")

    def refresh() -> None:
        view = build_dashboard_state(runtime.latest_radio_state, capture_state())
        pending_callsign = "" if view.pending_callsign == "—" else view.pending_callsign
        voice_state = view.voice_state.upper()
        voice_engaged = voice_state in {"ACTIVE", "CAPTURING", "LISTENING", "RECORDING"}

        callsign_prompt_text.set("" if pending_callsign or voice_engaged else "CALLSIGN")
        callsign_text.set(pending_callsign)
        callsign_label.configure(font=("DejaVu Sans", _callsign_font_size(pending_callsign), "bold"))
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
    root.bind("<v>", lambda _event: start_voice_capture())
    root.bind("<V>", lambda _event: start_voice_capture())
    root.bind("<c>", lambda _event: commit_capture())
    root.bind("<C>", lambda _event: commit_capture())
    root.bind("<d>", lambda _event: discard_capture())
    root.bind("<D>", lambda _event: discard_capture())
    root.protocol("WM_DELETE_WINDOW", close)
    refresh()
    root.mainloop()
    return 0


def main() -> int:
    """Console-script wrapper for the full-screen dashboard."""
    return run_dashboard()


if __name__ == "__main__":
    raise SystemExit(main())
