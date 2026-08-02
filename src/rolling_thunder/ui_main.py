"""Full-screen Raspberry Pi dashboard entry point."""

from __future__ import annotations

from pathlib import Path

from rolling_thunder.active_panel_commands import ActivePanelCommandController
from rolling_thunder.application_runtime import ApplicationRuntime
from rolling_thunder.callsign_capture import CallsignCaptureState, MockTranscriptController
from rolling_thunder.config import ConfigurationError, load_config
from rolling_thunder.contact_commit_controller import ContactCommitController
from rolling_thunder.context_navigation import (
    CONTEXT_DEFINITIONS,
    ContextId,
    ContextNavigationController,
)
from rolling_thunder.control_dispatcher import ControlDispatcher
from rolling_thunder.control_source_factory import build_control_source
from rolling_thunder.control_source_lifecycle import (
    close_control_source,
    open_control_source,
)
from rolling_thunder.dashboard_state import build_dashboard_state
from rolling_thunder.live_callsign_capture import LiveCallsignCaptureController
from rolling_thunder.main import DEFAULT_CONFIG_PATH
from rolling_thunder.operator_commands import OperatorCommandController
from rolling_thunder.physical_controls import (
    ControlAction,
    ControlActionMapper,
    ControlEventGate,
    ControlSource,
)
from rolling_thunder.pota_dashboard_controller import PotaDashboardController
from rolling_thunder.pota_dashboard_filters import PotaDashboardFilterController
from rolling_thunder.pota_dashboard_panel import build_pota_dashboard_panel
from rolling_thunder.pota_tune_execution_controller import (
    PotaTuneIntentExecutor,
)
from rolling_thunder.pota_tune_ui_controller import PotaTuneUiController
from rolling_thunder.radio import RadioConnectionError
from rolling_thunder.runtime_connectivity import build_runtime_connectivity_status
from rolling_thunder.speech_recognition import VoskCallsignRecognizer
from rolling_thunder.station_health import build_station_health

_REFRESH_MS = 250
_BACKGROUND = "#080808"
_PANEL_BACKGROUND = "#101010"
_SECONDARY_BACKGROUND = "#151515"
_CONTEXT_SELECTED = "#2a3f4b"
_BORDER = "#303030"
_BRIGHT = "#ffffff"
_DISABLED = "#777777"
_SUCCESS = "#42ff72"
_FAILURE = "#ff3b3b"
_MUTED = "#a8a8a8"

_HEALTH_READY = "#238636"
_HEALTH_DEGRADED = "#d4a017"
_HEALTH_DISABLED = "#c8c8c8"
_HEALTH_UNAVAILABLE = "#b42318"
_HEALTH_DARK_TEXT = "#080808"

_POTA_HEADER_FONT_SIZE = 52
_POTA_BODY_FONT_SIZE = 32
_POTA_CARD_OUTER_PAD_PX = 6
_POTA_CARD_NORMAL_BORDER_PX = 2
_POTA_CARD_SELECTED_BORDER_PX = 6
_POTA_VISIBLE_CARD_COUNT = 3


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


def _health_color(status: str) -> str:
    """Return the required station-health color for one status."""
    return {
        "READY": _HEALTH_READY,
        "DEGRADED": _HEALTH_DEGRADED,
        "DISABLED": _HEALTH_DISABLED,
        "UNAVAILABLE": _HEALTH_UNAVAILABLE,
    }.get(status.upper(), _MUTED)


def _health_cell_foreground(status: str) -> str:
    """Keep health-cell text readable against its status background."""
    if status.upper() in {"DEGRADED", "DISABLED"}:
        return _HEALTH_DARK_TEXT
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


def run_dashboard(
    config_path: Path = DEFAULT_CONFIG_PATH,
    *,
    pota_tune_executor: PotaTuneIntentExecutor | None = None,
) -> int:
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
            channels=config.speech.channels,
        )
        live_capture = LiveCallsignCaptureController(recognizer)

    capture = live_capture if live_capture is not None else mock_transcripts
    context_navigation = ContextNavigationController()
    pota_dashboard = PotaDashboardController(runtime)
    pota_filters = PotaDashboardFilterController(pota_dashboard)
    pota_tune_ui = PotaTuneUiController(
        pota_dashboard,
        pota_tune_executor or runtime.pota_receive_tune_executor,
    )
    active_panel_commands = ActivePanelCommandController(
        context_navigation,
        pota_dashboard,
        pota_filters,
        pota_tune_ui,
    )

    def capture_state() -> CallsignCaptureState:
        """Return the active capture controller's immutable state."""
        return capture.state

    def commit_started(callsign: str) -> None:
        capture.commit_started(callsign)

    def commit_succeeded(callsign: str) -> None:
        capture.commit_succeeded(callsign)

    def commit_failed(message: str) -> None:
        capture.commit_failed(message)

    contact_commit = ContactCommitController(
        runtime.contact_logging,
        on_started=commit_started,
        on_succeeded=commit_succeeded,
        on_failed=commit_failed,
    )
    operator_commands = OperatorCommandController(
        capture,
        contact_commit,
        context_navigation,
        radio_state=lambda: runtime.latest_radio_state,
        active_panel=active_panel_commands,
    )

    control_source: ControlSource | None = None
    control_dispatcher: ControlDispatcher | None = None
    if config.physical_controls.enabled:
        control_source = build_control_source(config.physical_controls)
        control_start_error = open_control_source(control_source)
        if control_start_error is not None:
            print(f"Rolling Thunder physical controls unavailable: {control_start_error}")

        control_dispatcher = ControlDispatcher(
            control_source,
            ControlActionMapper(config.physical_controls.mappings),
            ControlEventGate(config.physical_controls.repeat_suppression_s),
            operator_commands,
        )

    root = tk.Tk()
    root.title("Rolling Thunder v4")
    root.configure(bg=_BACKGROUND, cursor="none")
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
    logger.grid_rowconfigure(1, weight=4)
    logger.grid_rowconfigure(2, weight=2)
    logger.grid_rowconfigure(4, weight=2)
    logger.grid_rowconfigure(5, weight=1)
    logger.grid_rowconfigure(7, weight=2)

    callsign_prompt_text = tk.StringVar(value="CALLSIGN")
    tk.Label(
        logger,
        textvariable=callsign_prompt_text,
        bg=_PANEL_BACKGROUND,
        fg=_MUTED,
        font=("DejaVu Sans", 18, "bold"),
        anchor="center",
    ).grid(row=0, column=0, columnspan=2, sticky="ew", pady=0)

    callsign_text = tk.StringVar(value="")
    callsign_label = tk.Label(
        logger,
        textvariable=callsign_text,
        bg=_PANEL_BACKGROUND,
        fg=_BRIGHT,
        font=("DejaVu Sans", 72, "bold"),
        anchor="center",
    )
    callsign_label.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=0)

    voice_text = tk.StringVar(value="VOICE")
    voice_label = tk.Label(
        logger,
        textvariable=voice_text,
        bg=_PANEL_BACKGROUND,
        fg=_DISABLED,
        font=("DejaVu Sans", 36, "bold"),
        anchor="center",
    )
    voice_label.grid(row=2, column=0, sticky="nsew", padx=8, pady=0)

    commit_text = tk.StringVar(value="COMMIT")
    commit_label = tk.Label(
        logger,
        textvariable=commit_text,
        bg=_PANEL_BACKGROUND,
        fg=_DISABLED,
        font=("DejaVu Sans", 36, "bold"),
        anchor="center",
    )
    commit_label.grid(row=2, column=1, sticky="nsew", padx=8, pady=0)

    tk.Frame(logger, bg=_BORDER, height=3).grid(
        row=3,
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
    ).grid(row=4, column=0, columnspan=2, sticky="nsew", pady=0)

    band_text = tk.StringVar(value="--")
    tk.Label(
        logger,
        textvariable=band_text,
        bg=_PANEL_BACKGROUND,
        fg=_BRIGHT,
        font=("DejaVu Sans", 30, "bold"),
        anchor="w",
    ).grid(row=5, column=0, sticky="ew", padx=(10, 5), pady=0)

    mode_text = tk.StringVar(value="--")
    tk.Label(
        logger,
        textvariable=mode_text,
        bg=_PANEL_BACKGROUND,
        fg=_BRIGHT,
        font=("DejaVu Sans", 30, "bold"),
        anchor="e",
    ).grid(row=5, column=1, sticky="ew", padx=(5, 10), pady=0)

    tk.Frame(logger, bg=_BORDER, height=2).grid(
        row=6,
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
    ).grid(row=7, column=0, columnspan=2, sticky="nsew", padx=6, pady=0)

    context = tk.Frame(
        left,
        bg=_SECONDARY_BACKGROUND,
        highlightthickness=1,
        highlightbackground=_BORDER,
    )
    context.grid(row=1, column=0, sticky="nsew", padx=12, pady=(4, 12))
    context.grid_columnconfigure(0, weight=1)
    context.grid_rowconfigure(0, weight=1)

    context_content = tk.Frame(context, bg=_SECONDARY_BACKGROUND)
    context_content.grid(row=0, column=0, sticky="nsew", padx=6, pady=8)
    context_content.grid_columnconfigure(0, weight=1)
    context_content.grid_rowconfigure(1, weight=1)
    context_content.grid_rowconfigure(2, weight=0)

    context_title_text = tk.StringVar(value="POTA")
    context_title_label = tk.Label(
        context_content,
        textvariable=context_title_text,
        bg=_SECONDARY_BACKGROUND,
        fg=_BRIGHT,
        font=("DejaVu Sans", 48, "bold"),
        anchor="center",
    )
    context_title_label.grid(row=0, column=0, sticky="ew", pady=(2, 8))

    context_body_text = tk.StringVar(value="")
    context_body_label = tk.Label(
        context_content,
        textvariable=context_body_text,
        bg=_SECONDARY_BACKGROUND,
        fg=_MUTED,
        font=("DejaVu Sans", 22),
        justify="left",
        anchor="nw",
        wraplength=560,
    )
    context_body_label.grid(row=1, column=0, sticky="nsew")

    pota_panel_frame = tk.Frame(context_content, bg=_SECONDARY_BACKGROUND)
    pota_panel_frame.grid(row=1, column=0, sticky="nsew")
    pota_panel_frame.grid_columnconfigure(0, weight=1)
    pota_panel_frame.grid_rowconfigure(1, weight=1)
    pota_panel_frame.grid_remove()

    pota_more_above_text = tk.StringVar(value="")
    pota_more_above_label = tk.Label(
        pota_panel_frame,
        textvariable=pota_more_above_text,
        bg=_SECONDARY_BACKGROUND,
        fg=_BRIGHT,
        font=("DejaVu Sans", _POTA_BODY_FONT_SIZE, "bold"),
        anchor="center",
    )
    pota_more_above_label.grid(row=0, column=0, sticky="ew", pady=(0, 2))

    pota_status_text = tk.StringVar(value="")
    pota_status_label = tk.Label(
        pota_panel_frame,
        textvariable=pota_status_text,
        bg=_SECONDARY_BACKGROUND,
        fg=_MUTED,
        font=("DejaVu Sans", _POTA_BODY_FONT_SIZE, "bold"),
        justify="left",
        anchor="nw",
        wraplength=680,
    )
    pota_status_label.grid(row=1, column=0, sticky="nsew", padx=4, pady=4)

    pota_cards_container = tk.Frame(pota_panel_frame, bg=_SECONDARY_BACKGROUND)
    pota_cards_container.grid(row=1, column=0, sticky="nsew")
    pota_cards_container.grid_columnconfigure(0, weight=1)
    pota_cards_container.grid_remove()

    pota_card_frames: list[tk.Frame] = []
    pota_card_labels: list[tuple[tk.Label, tk.Label, tk.Label, tk.Label]] = []
    pota_card_texts: list[
        tuple[tk.StringVar, tk.StringVar, tk.StringVar, tk.StringVar]
    ] = []

    for card_index in range(_POTA_VISIBLE_CARD_COUNT):
        card_frame = tk.Frame(
            pota_cards_container,
            bg=_PANEL_BACKGROUND,
            highlightthickness=_POTA_CARD_SELECTED_BORDER_PX,
            highlightbackground=_SECONDARY_BACKGROUND,
            highlightcolor=_SECONDARY_BACKGROUND,
        )
        card_frame.grid(
            row=card_index,
            column=0,
            sticky="ew",
            padx=2,
            pady=5,
        )
        card_frame.grid_columnconfigure(0, weight=1)

        callsign_var = tk.StringVar(value="")
        frequency_var = tk.StringVar(value="")
        park_var = tk.StringVar(value="")
        location_var = tk.StringVar(value="")

        callsign_label = tk.Label(
            card_frame,
            textvariable=callsign_var,
            bg=_PANEL_BACKGROUND,
            fg=_BRIGHT,
            font=("DejaVu Sans", _POTA_BODY_FONT_SIZE, "bold"),
            anchor="w",
            justify="left",
            padx=12,
            pady=2,
        )
        callsign_label.grid(row=0, column=0, sticky="ew")

        frequency_label = tk.Label(
            card_frame,
            textvariable=frequency_var,
            bg=_PANEL_BACKGROUND,
            fg=_BRIGHT,
            font=("DejaVu Sans", _POTA_BODY_FONT_SIZE, "bold"),
            anchor="w",
            justify="left",
            padx=12,
            pady=0,
        )
        frequency_label.grid(row=1, column=0, sticky="ew")

        park_label = tk.Label(
            card_frame,
            textvariable=park_var,
            bg=_PANEL_BACKGROUND,
            fg=_BRIGHT,
            font=("DejaVu Sans", _POTA_BODY_FONT_SIZE, "bold"),
            anchor="w",
            justify="left",
            padx=12,
            pady=0,
            wraplength=680,
        )
        park_label.grid(row=2, column=0, sticky="ew")

        location_label = tk.Label(
            card_frame,
            textvariable=location_var,
            bg=_PANEL_BACKGROUND,
            fg=_BRIGHT,
            font=("DejaVu Sans", _POTA_BODY_FONT_SIZE, "bold"),
            anchor="w",
            justify="left",
            padx=12,
            pady=2,
        )
        location_label.grid(row=3, column=0, sticky="ew")

        pota_card_frames.append(card_frame)
        pota_card_labels.append(
            (callsign_label, frequency_label, park_label, location_label)
        )
        pota_card_texts.append(
            (callsign_var, frequency_var, park_var, location_var)
        )
        card_frame.grid_remove()

    pota_more_below_text = tk.StringVar(value="")
    pota_more_below_label = tk.Label(
        pota_panel_frame,
        textvariable=pota_more_below_text,
        bg=_SECONDARY_BACKGROUND,
        fg=_BRIGHT,
        font=("DejaVu Sans", _POTA_BODY_FONT_SIZE, "bold"),
        anchor="center",
    )
    pota_more_below_label.grid(row=2, column=0, sticky="ew", pady=(2, 0))

    pota_footer_text = tk.StringVar(value="")
    pota_footer_label = tk.Label(
        pota_panel_frame,
        textvariable=pota_footer_text,
        bg=_SECONDARY_BACKGROUND,
        fg=_MUTED,
        font=("DejaVu Sans", _POTA_BODY_FONT_SIZE, "bold"),
        anchor="w",
        justify="left",
        wraplength=680,
    )
    pota_footer_label.grid(row=3, column=0, sticky="ew", padx=4, pady=(4, 0))

    health_frame = tk.Frame(
        context_content,
        bg=_SECONDARY_BACKGROUND,
        highlightthickness=1,
        highlightbackground=_BORDER,
    )
    health_frame.grid(
        row=2,
        column=0,
        sticky="sew",
        pady=(12, 0),
    )
    health_frame.grid_columnconfigure(0, weight=1)
    health_frame.grid_remove()

    overall_health_text = tk.StringVar(value="Overall Station Health: —")
    overall_health_label = tk.Label(
        health_frame,
        textvariable=overall_health_text,
        bg=_SECONDARY_BACKGROUND,
        fg=_MUTED,
        font=("DejaVu Sans", 29, "bold"),
        anchor="w",
        padx=10,
        pady=10,
    )
    overall_health_label.grid(row=0, column=0, sticky="ew")

    health_table = tk.Frame(
        health_frame,
        bg=_BORDER,
        highlightthickness=1,
        highlightbackground=_BORDER,
    )
    health_table.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 8))

    health_labels = ("Radio", "GPS", "Voice", "Logging", "Storage")
    health_status_text: dict[str, tk.StringVar] = {}
    health_status_labels: dict[str, tk.Label] = {}

    for column, label in enumerate(health_labels):
        health_table.grid_columnconfigure(column, weight=1, uniform="health")

        tk.Label(
            health_table,
            text=label,
            bg=_PANEL_BACKGROUND,
            fg=_BRIGHT,
            font=("DejaVu Sans", 24, "bold"),
            anchor="center",
            relief="solid",
            borderwidth=1,
            padx=4,
            pady=8,
        ).grid(row=0, column=column, sticky="nsew")

        status_text = tk.StringVar(value="—")
        status_label = tk.Label(
            health_table,
            textvariable=status_text,
            bg=_DISABLED,
            fg=_HEALTH_DARK_TEXT,
            font=("DejaVu Sans", 26, "bold"),
            anchor="center",
            relief="solid",
            borderwidth=1,
            padx=4,
            pady=10,
        )
        status_label.grid(row=1, column=column, sticky="nsew")

        health_status_text[label] = status_text
        health_status_labels[label] = status_label

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

    previous_context: ContextId | None = None

    def show_standard_context_body() -> None:
        """Show the reusable text body and hide the POTA card viewport."""
        pota_panel_frame.grid_remove()
        context_body_label.grid()

    def show_pota_context_body() -> None:
        """Show the POTA card viewport and hide the generic text body."""
        context_body_label.grid_remove()
        pota_panel_frame.grid()

    def refresh() -> None:
        nonlocal previous_context

        if control_dispatcher is not None:
            control_dispatcher.dispatch_available()

        gps_state = runtime.latest_gps_state
        connectivity = build_runtime_connectivity_status(
            runtime,
            network_enabled=config.network_keepalive.enabled,
            platform_enabled=config.home_platform.enabled,
        )
        view = build_dashboard_state(
            runtime.latest_radio_state,
            capture_state(),
            gps_state,
            connectivity,
        )
        pending_callsign = "" if view.pending_callsign == "—" else view.pending_callsign
        voice_state = view.voice_state.upper()
        voice_engaged = voice_state in {
            "ACTIVE",
            "CAPTURING",
            "LISTENING",
            "RECORDING",
        }

        callsign_prompt_text.set("" if pending_callsign or voice_engaged else "CALLSIGN")
        callsign_text.set(pending_callsign)
        callsign_label.configure(
            font=("DejaVu Sans", _callsign_font_size(pending_callsign), "bold")
        )
        voice_text.set("VOICE")
        voice_label.configure(fg=_indicator_color(view.voice_state))
        commit_text.set("COMMIT")
        commit_label.configure(fg=_indicator_color(view.commit_state))
        frequency_text.set(view.frequency)
        band_text.set(view.band.replace(" ", ""))
        mode_text.set(view.mode)
        last_result = view.last_result if view.last_result != "—" else "—"
        last_result_text.set(f"Last Result: {last_result[:18]}")
        ticker = view.ticker
        if view.grid != "—":
            ticker = f"{ticker} — GRID {view.grid.upper()}"
        ticker = (
            f"{ticker} — NETWORK {view.network_state}"
            f" — HOME {view.home_platform_state}"
            f" — SYNC {view.synchronization_state}"
        )
        if view.connectivity_detail != "CONNECTIVITY READY":
            ticker = f"{ticker} — {view.connectivity_detail}"
        ticker_text.set(ticker)

        selected_context = context_navigation.state
        if (
            selected_context.selected is ContextId.POTA
            and previous_context is not ContextId.POTA
        ):
            pota_filters.activate_for_frequency(runtime.latest_radio_state.frequency)
        previous_context = selected_context.selected

        if selected_context.selected is ContextId.POTA:
            health_frame.grid_remove()
            show_pota_context_body()
            filter_state = pota_filters.state
            panel = build_pota_dashboard_panel(filter_state.dashboard)
            context_title_text.set(filter_state.display_line)
            context_title_label.configure(
                font=("DejaVu Sans", _POTA_HEADER_FONT_SIZE, "bold")
            )

            available_wrap_width = max(480, pota_panel_frame.winfo_width() - 36)
            pota_status_label.configure(wraplength=available_wrap_width)
            pota_footer_label.configure(wraplength=available_wrap_width)
            for labels in pota_card_labels:
                labels[2].configure(wraplength=available_wrap_width)

            if filter_state.dashboard.status != "READY":
                pota_cards_container.grid_remove()
                pota_status_label.grid()
                status_lines = [panel.detail_line, panel.status_line]
                if panel.error_line:
                    status_lines.append(panel.error_line)
                pota_status_text.set("\n".join(status_lines))
                pota_more_above_text.set("")
                pota_more_below_text.set("")
                for card_frame in pota_card_frames:
                    card_frame.grid_remove()
            else:
                pota_status_label.grid_remove()
                pota_cards_container.grid()
                pota_more_above_text.set(
                    "▲ MORE ▲" if panel.hidden_above_count else ""
                )
                pota_more_below_text.set(
                    "▼ MORE ▼" if panel.hidden_below_count else ""
                )

                for card_index, card_frame in enumerate(pota_card_frames):
                    if card_index >= len(panel.rows):
                        card_frame.grid_remove()
                        continue

                    row = panel.rows[card_index]
                    card_frame.grid()
                    callsign_var, frequency_var, park_var, location_var = (
                        pota_card_texts[card_index]
                    )
                    callsign_var.set(row.activator)
                    frequency_var.set(row.frequency)
                    park_var.set(f"{row.park_reference} - {row.park_name}")
                    location_var.set(row.location_code)

                    selected_background = (
                        _CONTEXT_SELECTED if row.is_selected else _PANEL_BACKGROUND
                    )
                    visible_border_width = (
                        _POTA_CARD_SELECTED_BORDER_PX
                        if row.is_selected
                        else _POTA_CARD_NORMAL_BORDER_PX
                    )
                    invisible_border_width = (
                        _POTA_CARD_OUTER_PAD_PX - visible_border_width
                    )
                    border_color = _BRIGHT if row.is_selected else _BORDER
                    card_frame.configure(
                        bg=selected_background,
                        highlightbackground=border_color,
                        highlightcolor=border_color,
                        highlightthickness=visible_border_width,
                        padx=invisible_border_width,
                        pady=invisible_border_width,
                    )
                    for card_label in pota_card_labels[card_index]:
                        card_label.configure(bg=selected_background)

            tune_presentation = pota_tune_ui.presentation
            footer_lines = [
                line
                for line in (
                    tune_presentation.summary_line,
                    tune_presentation.status_line,
                    tune_presentation.detail_line,
                )
                if line is not None
            ]
            pota_footer_text.set("\n".join(footer_lines))
        elif selected_context.selected is ContextId.SETTINGS:
            show_standard_context_body()
            context_title_text.set(selected_context.definition.title)
            context_title_label.configure(font=("DejaVu Sans", 48, "bold"))
            context_body_label.configure(font=("DejaVu Sans", 22), wraplength=560)
            context_body_text.set("")

            health = build_station_health(
                runtime.latest_radio_state,
                capture_state(),
                speech_enabled=config.speech.enabled,
                gps_state=gps_state,
            )

            overall_status = health.overall.value
            overall_health_text.set(f"Overall Station Health: {overall_status.title()}")
            overall_health_label.configure(
                fg=_health_color(overall_status),
            )

            for item in health.items:
                status = item.status.value
                health_status_text[item.label].set(status)
                health_status_labels[item.label].configure(
                    bg=_health_color(status),
                    fg=_health_cell_foreground(status),
                )

            health_frame.grid()
        else:
            show_standard_context_body()
            health_frame.grid_remove()
            context_title_text.set(selected_context.definition.title)
            context_title_label.configure(font=("DejaVu Sans", 48, "bold"))
            context_body_label.configure(font=("DejaVu Sans", 22), wraplength=560)
            context_body_text.set(selected_context.definition.placeholder)

        root.after(_REFRESH_MS, refresh)

    def close() -> None:
        control_close_error = close_control_source(control_source)
        if control_close_error is not None:
            print(f"Rolling Thunder physical controls shutdown error: {control_close_error}")
        runtime.stop()
        root.destroy()

    root.bind("<Escape>", lambda _event: close())
    root.bind(
        "<v>",
        lambda _event: operator_commands.execute(ControlAction.VOICE),
    )
    root.bind(
        "<V>",
        lambda _event: operator_commands.execute(ControlAction.VOICE),
    )
    root.bind(
        "<c>",
        lambda _event: operator_commands.execute(ControlAction.COMMIT),
    )
    root.bind(
        "<C>",
        lambda _event: operator_commands.execute(ControlAction.COMMIT),
    )
    root.bind(
        "<d>",
        lambda _event: operator_commands.execute(ControlAction.DISCARD),
    )
    root.bind(
        "<D>",
        lambda _event: operator_commands.execute(ControlAction.DISCARD),
    )

    def handle_pota_filter_key(event: tk.Event[tk.Misc]) -> None:
        if context_navigation.state.selected is ContextId.POTA:
            pota_filters.handle_key(event.char)

    for key in ("[", "]", ",", ".", "/"):
        root.bind(key, handle_pota_filter_key)

    def select_previous_pota_spot(_event: tk.Event[tk.Misc]) -> None:
        if context_navigation.state.selected is ContextId.POTA:
            pota_dashboard.select_previous()

    def select_next_pota_spot(_event: tk.Event[tk.Misc]) -> None:
        if context_navigation.state.selected is ContextId.POTA:
            pota_dashboard.select_next()

    root.bind("<Up>", select_previous_pota_spot)
    root.bind("<Down>", select_next_pota_spot)

    def request_pota_tune_intent(_event: tk.Event[tk.Misc]) -> None:
        if context_navigation.state.selected is ContextId.POTA:
            pota_tune_ui.request()

    def confirm_pota_tune_intent(_event: tk.Event[tk.Misc]) -> None:
        if context_navigation.state.selected is ContextId.POTA:
            pota_tune_ui.confirm()

    def cancel_pota_tune_intent(_event: tk.Event[tk.Misc]) -> None:
        if context_navigation.state.selected is ContextId.POTA:
            pota_tune_ui.cancel()

    def execute_pota_tune_intent(_event: tk.Event[tk.Misc]) -> None:
        if context_navigation.state.selected is ContextId.POTA:
            pota_tune_ui.execute()

    root.bind("<Return>", confirm_pota_tune_intent)
    root.bind("<KP_Enter>", confirm_pota_tune_intent)
    root.bind("<t>", request_pota_tune_intent)
    root.bind("<T>", request_pota_tune_intent)
    root.bind("<e>", execute_pota_tune_intent)
    root.bind("<E>", execute_pota_tune_intent)
    root.bind("<x>", cancel_pota_tune_intent)
    root.bind("<X>", cancel_pota_tune_intent)

    context_shortcut_actions = {
        "1": ControlAction.SELECT_POTA,
        "2": ControlAction.SELECT_DX,
        "3": ControlAction.SELECT_REPEATERS,
        "4": ControlAction.SELECT_AI,
        "5": ControlAction.SELECT_SETTINGS,
    }

    def select_context_shortcut(event: tk.Event[tk.Misc]) -> None:
        action = context_shortcut_actions.get(event.char)
        if action is not None:
            operator_commands.execute(action)

    for definition in CONTEXT_DEFINITIONS:
        root.bind(definition.shortcut, select_context_shortcut)
    root.protocol("WM_DELETE_WINDOW", close)
    refresh()
    root.mainloop()
    return 0


def main() -> int:
    """Console-script wrapper for the full-screen dashboard."""
    return run_dashboard()


if __name__ == "__main__":
    raise SystemExit(main())
