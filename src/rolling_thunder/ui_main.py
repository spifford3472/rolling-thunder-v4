"""Full-screen Raspberry Pi dashboard entry point."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from rolling_thunder.active_panel_commands import (
    SharedSpotActivePanelCommandController,
)
from rolling_thunder.application_runtime import ApplicationRuntime
from rolling_thunder.application_secrets import (
    SecretConfigurationError,
    load_application_secrets,
)
from rolling_thunder.browse_control import BrowseRadioController, browse_mode_label
from rolling_thunder.callsign_capture import (
    CallsignCaptureState,
    MockTranscriptController,
)
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
from rolling_thunder.dmr_active_panel_commands import DmrAwareActivePanelCommands
from rolling_thunder.dmr_dashboard_runtime import build_dmr_panel_runtime
from rolling_thunder.dmr_panel_runtime import DmrCommitEventKind
from rolling_thunder.dmr_ui import build_dmr_viewport
from rolling_thunder.dmr_widgets import DmrWidgets
from rolling_thunder.fm_repeater import FmRepeaterConfigurableRadio
from rolling_thunder.live_callsign_capture import LiveCallsignCaptureController
from rolling_thunder.live_map import LiveMapController
from rolling_thunder.live_map_ui import LiveMapWidgets
from rolling_thunder.log_panel import ContactLogRepository, LogPanelController
from rolling_thunder.log_panel_commands import LogAwareActivePanelCommands
from rolling_thunder.log_ui import LogWidgets
from rolling_thunder.main import DEFAULT_CONFIG_PATH
from rolling_thunder.operator_commands import OperatorCommandController
from rolling_thunder.operator_preferences import OperatorPreferenceRepository
from rolling_thunder.physical_controls import (
    ControlAction,
    ControlActionMapper,
    ControlEventGate,
    ControlSource,
)
from rolling_thunder.pota_tune_execution_controller import (
    PotaTuneIntentExecutor,
)
from rolling_thunder.pota_worked import PotaWorkedRepository, PotaWorkedTracker
from rolling_thunder.radio import RadioConnectionError
from rolling_thunder.receive_tuning import ReceiveTuningService
from rolling_thunder.repeater_configuration import (
    RepeaterConfigurationController,
    RepeaterConfigurationService,
)
from rolling_thunder.repeater_panel_runtime import RepeaterPanelRuntime
from rolling_thunder.repeater_ui import build_repeater_viewport
from rolling_thunder.repeater_widgets import RepeaterWidgets
from rolling_thunder.runtime_connectivity import build_runtime_connectivity_status
from rolling_thunder.settings_panel import DashboardSettingsController
from rolling_thunder.settings_ui import SettingsWidgets
from rolling_thunder.shared_pota_contact import shared_pota_spots_for_contact
from rolling_thunder.shared_spot_panel import SharedSpotPanelController
from rolling_thunder.shared_spot_tune_status import SharedSpotTuneStatusController
from rolling_thunder.shared_spot_tuning import SharedSpotTuneController
from rolling_thunder.shared_spot_ui import build_shared_spot_viewport
from rolling_thunder.speech_recognition import VoskCallsignRecognizer
from rolling_thunder.station_health import build_station_health
from rolling_thunder.status_bar_ui import StatusBarWidgets
from rolling_thunder.status_messages import StatusPresentation
from rolling_thunder.status_monitor import build_status_monitor
from rolling_thunder.status_strip import (
    build_status_bar_routine_message,
    build_status_strip_snapshot,
)
from rolling_thunder.weather_alert_panel import (
    WeatherAlertPanelController,
)
from rolling_thunder.weather_alert_viewport import WeatherAlertViewportController
from rolling_thunder.weather_panel import WeatherPanelController
from rolling_thunder.weather_ui import WeatherWidgets

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
_WARNING = "#ffd24a"
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
_POTA_WORKED_BACKGROUND = "#b9ddf5"
_POTA_WORKED_FOREGROUND = "#0b1f33"


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


def _status_foreground(presentation: StatusPresentation) -> str:
    """Map a status presentation token to the dashboard foreground color."""
    return {
        StatusPresentation.NORMAL: _BRIGHT,
        StatusPresentation.AMBER: _WARNING,
        StatusPresentation.SUCCESS: _SUCCESS,
        StatusPresentation.ERROR: _FAILURE,
        StatusPresentation.MUTED: _MUTED,
    }[presentation]


def _pota_card_colors(*, selected: bool, worked: bool) -> tuple[str, str]:
    """Return readable POTA card colors while preserving worked state."""
    if worked:
        return _POTA_WORKED_BACKGROUND, _POTA_WORKED_FOREGROUND
    if selected:
        return _CONTEXT_SELECTED, _BRIGHT
    return _PANEL_BACKGROUND, _BRIGHT


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

    try:
        secrets = load_application_secrets()
    except SecretConfigurationError as error:
        print(f"Rolling Thunder secret configuration error: {error}")
        return 2

    runtime = ApplicationRuntime.from_config(config, secrets=secrets)
    stored_radar_image = OperatorPreferenceRepository(
        config.storage.database_path
    ).read_radar_image_enabled()
    if runtime.live_radar is not None and stored_radar_image is not None:
        runtime.live_radar.set_display_enabled(stored_radar_image)

    preference_service = runtime.operator_preferences
    if preference_service is None:
        raise RuntimeError("Operator preferences are required by the Settings panel.")
    settings_panel = DashboardSettingsController(
        runtime.map_zoom_settings,
        runtime.live_radar,
        preference_service,
        runtime.map_solar,
    )
    weather_panel = WeatherPanelController()
    weather_alert_panel = WeatherAlertPanelController()
    weather_alert_viewport = WeatherAlertViewportController()

    try:
        runtime.start()
    except (RadioConnectionError, RuntimeError, ValueError) as error:
        print(f"Rolling Thunder startup error: {error}")
        return 3

    log_panel = LogPanelController(
        ContactLogRepository(config.storage.database_path),
        runtime.contact_sync,
    )
    log_panel.start()

    mock_transcripts = MockTranscriptController()
    live_capture: LiveCallsignCaptureController | None = None
    if config.speech.enabled:
        model_path = config.speech.model_path
        if model_path is None:
            print("Rolling Thunder startup error: speech model path is unavailable")
            log_panel.stop()
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
    pota_worked = PotaWorkedTracker(
        PotaWorkedRepository(config.storage.database_path)
    )
    shared_spot_panel = SharedSpotPanelController(
        runtime,
        pota_worked_status=pota_worked,
    )
    shared_spot_tuning = SharedSpotTuneController(ReceiveTuningService(runtime.radio))
    shared_spot_tune_status = SharedSpotTuneStatusController(
        shared_spot_tuning,
        runtime.status_messages,
    )
    browse_controls = BrowseRadioController(
        runtime.radio,
        radio_state=lambda: runtime.latest_radio_state,
    )
    repeater_panel_runtime = RepeaterPanelRuntime.build(
        database_path=config.storage.database_path,
        gps_state=lambda: runtime.latest_gps_state,
        source_path=config.repeaters.source_path,
    )
    repeater_panel = repeater_panel_runtime.panel
    repeater_configuration = (
        RepeaterConfigurationController(RepeaterConfigurationService(runtime.radio))
        if isinstance(runtime.radio, FmRepeaterConfigurableRadio)
        else None
    )
    base_active_panel_commands = SharedSpotActivePanelCommandController(
        context_navigation,
        shared_spot_panel,
        current_frequency=lambda: runtime.latest_radio_state.frequency,
        radio_state=lambda: runtime.latest_radio_state,
        shared_tuning=shared_spot_tuning,
        pending_callsign=capture,
        browse_panel=browse_controls,
        settings_panel=settings_panel,
        repeater_panel=repeater_panel,
        repeater_active_overrides=repeater_panel_runtime.persistence,
        repeater_configuration=repeater_configuration,
        weather_alert_viewport=weather_alert_viewport,
    )
    log_aware_active_panel_commands = LogAwareActivePanelCommands(
        context_navigation,
        base_active_panel_commands,
        log_panel,
    )
    try:
        dmr_panel_runtime = build_dmr_panel_runtime(
            config.dmr,
            database_path=config.storage.database_path,
            gps_state_provider=lambda: runtime.latest_gps_state,
            operator_callsign=config.operator.callsign,
        )
        if dmr_panel_runtime is not None:
            dmr_panel_runtime.set_polling_enabled(False)
            dmr_panel_runtime.start()
    except (RuntimeError, ValueError) as error:
        print(f"Rolling Thunder DMR startup error: {error}")
        log_panel.stop()
        runtime.stop()
        return 3
    active_panel_commands: (
        LogAwareActivePanelCommands | DmrAwareActivePanelCommands
    )
    if dmr_panel_runtime is None:
        active_panel_commands = log_aware_active_panel_commands
    else:
        active_panel_commands = DmrAwareActivePanelCommands(
            context_navigation,
            log_aware_active_panel_commands,
            dmr_panel_runtime.commands,
        )

    status_monitor = build_status_monitor(config)
    status_monitor.start()
    _ = pota_tune_executor

    def capture_state() -> CallsignCaptureState:
        """Return the active capture controller's immutable state."""
        return capture.state

    def commit_started(callsign: str) -> None:
        capture.commit_started(callsign)

    def commit_succeeded(callsign: str) -> None:
        capture.commit_succeeded(callsign)
        log_panel.request_sync()

    def commit_failed(message: str) -> None:
        capture.commit_failed(message)

    contact_commit = ContactCommitController(
        runtime.contact_logging,
        on_started=commit_started,
        on_succeeded=commit_succeeded,
        on_failed=commit_failed,
        gps_state_provider=lambda: runtime.latest_gps_state,
        pota_context_provider=lambda: (
            context_navigation.state.selected is ContextId.POTA
        ),
        browse_context_provider=lambda: (
            context_navigation.state.selected is ContextId.BROWSE
        ),
        pota_spots_provider=lambda: shared_pota_spots_for_contact(
            shared_spot_panel.visible_spots
        ),
        pota_worked_tracker=pota_worked,
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

    settings_widgets = SettingsWidgets(context_content)
    weather_widgets = WeatherWidgets(context_content)
    repeater_widgets = RepeaterWidgets(context_content)
    log_widgets = LogWidgets(context_content)
    dmr_widgets = DmrWidgets(context_content)

    browse_frame = tk.Frame(context_content, bg=_SECONDARY_BACKGROUND)
    browse_frame.grid(row=1, column=0, sticky="nsew")
    browse_frame.grid_columnconfigure(0, weight=1)
    for browse_row in range(6):
        browse_frame.grid_rowconfigure(browse_row, weight=1)
    browse_frame.grid_remove()

    browse_mode_caption = tk.Label(
        browse_frame,
        text="MODE",
        bg=_SECONDARY_BACKGROUND,
        fg=_MUTED,
        font=("DejaVu Sans", 22, "bold"),
    )
    browse_mode_caption.grid(row=0, column=0, sticky="s")
    browse_mode_text = tk.StringVar(value="--")
    tk.Label(
        browse_frame,
        textvariable=browse_mode_text,
        bg=_SECONDARY_BACKGROUND,
        fg=_BRIGHT,
        font=("DejaVu Sans", 52, "bold"),
    ).grid(row=1, column=0, sticky="nsew")

    tk.Label(
        browse_frame,
        text="FREQUENCY",
        bg=_SECONDARY_BACKGROUND,
        fg=_MUTED,
        font=("DejaVu Sans", 22, "bold"),
    ).grid(row=2, column=0, sticky="s")
    browse_frequency_text = tk.StringVar(value="---.--- MHz")
    tk.Label(
        browse_frame,
        textvariable=browse_frequency_text,
        bg=_SECONDARY_BACKGROUND,
        fg=_BRIGHT,
        font=("DejaVu Sans", 44, "bold"),
    ).grid(row=3, column=0, sticky="nsew")

    tk.Label(
        browse_frame,
        text="STEP",
        bg=_SECONDARY_BACKGROUND,
        fg=_MUTED,
        font=("DejaVu Sans", 24, "bold"),
    ).grid(row=4, column=0, sticky="s")
    browse_step_text = tk.StringVar(value="100 Hz")
    tk.Label(
        browse_frame,
        textvariable=browse_step_text,
        bg=_SECONDARY_BACKGROUND,
        fg=_WARNING,
        font=("DejaVu Sans", 58, "bold"),
    ).grid(row=5, column=0, sticky="nsew")

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
        pota_card_labels.append((callsign_label, frequency_label, park_label, location_label))
        pota_card_texts.append((callsign_var, frequency_var, park_var, location_var))
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
    live_map_controller = LiveMapController(
        stale_after=timedelta(seconds=config.map.gps_stale_after_s)
    )
    live_map_widgets = LiveMapWidgets(
        situational,
        pota_label_min_zoom=config.pota_map.label_min_zoom,
        pota_dot_diameter_px=config.pota_map.dot_diameter_px,
    )

    status_bar = StatusBarWidgets(root)
    status_bar.frame.grid(
        row=1,
        column=0,
        columnspan=2,
        sticky="nsew",
    )

    dmr_expanded_layout = False

    def set_dmr_expanded_layout(enabled: bool) -> None:
        """Give DMR the full left-column height without disturbing other contexts."""
        nonlocal dmr_expanded_layout
        if enabled == dmr_expanded_layout:
            return
        dmr_expanded_layout = enabled
        if enabled:
            logger.grid_remove()
            context.grid_configure(row=0, rowspan=2, pady=(8, 12))
            return
        context.grid_configure(row=1, rowspan=1, pady=(4, 12))
        logger.grid()

    def show_standard_context_body() -> None:
        """Show the reusable text body and hide specialized context viewports."""
        browse_frame.grid_remove()
        pota_panel_frame.grid_remove()
        repeater_widgets.hide()
        settings_widgets.hide()
        weather_widgets.hide()
        log_widgets.hide()
        dmr_widgets.hide()
        context_body_label.grid()

    def show_pota_context_body() -> None:
        """Show the POTA/DX card viewport and hide other context bodies."""
        browse_frame.grid_remove()
        context_body_label.grid_remove()
        repeater_widgets.hide()
        settings_widgets.hide()
        weather_widgets.hide()
        log_widgets.hide()
        dmr_widgets.hide()
        pota_panel_frame.grid()

    def show_browse_context_body() -> None:
        """Show free-form Browse radio state and hide unrelated context bodies."""
        context_body_label.grid_remove()
        pota_panel_frame.grid_remove()
        repeater_widgets.hide()
        settings_widgets.hide()
        weather_widgets.hide()
        log_widgets.hide()
        dmr_widgets.hide()
        browse_frame.grid()

    def show_repeater_context_body() -> None:
        """Show local repeaters and hide the generic/POTA/settings/weather bodies."""
        browse_frame.grid_remove()
        context_body_label.grid_remove()
        pota_panel_frame.grid_remove()
        settings_widgets.hide()
        weather_widgets.hide()
        log_widgets.hide()
        dmr_widgets.hide()
        repeater_widgets.show()

    def show_settings_context_body() -> None:
        """Show Settings controls and hide the generic/POTA/repeater/weather bodies."""
        browse_frame.grid_remove()
        context_body_label.grid_remove()
        pota_panel_frame.grid_remove()
        repeater_widgets.hide()
        weather_widgets.hide()
        log_widgets.hide()
        dmr_widgets.hide()
        settings_widgets.show()

    def show_weather_context_body() -> None:
        """Show retained weather and hide other context bodies."""
        browse_frame.grid_remove()
        context_body_label.grid_remove()
        pota_panel_frame.grid_remove()
        repeater_widgets.hide()
        settings_widgets.hide()
        log_widgets.hide()
        dmr_widgets.hide()
        weather_widgets.show()

    def show_log_context_body() -> None:
        """Show the local Log snapshot and hide every unrelated context body."""
        browse_frame.grid_remove()
        context_body_label.grid_remove()
        pota_panel_frame.grid_remove()
        repeater_widgets.hide()
        settings_widgets.hide()
        weather_widgets.hide()
        dmr_widgets.hide()
        log_widgets.show()

    def show_dmr_context_body() -> None:
        """Show DMR activity and hide every unrelated context body."""
        context_body_label.grid_remove()
        pota_panel_frame.grid_remove()
        repeater_widgets.hide()
        settings_widgets.hide()
        weather_widgets.hide()
        log_widgets.hide()
        dmr_widgets.show()

    def refresh() -> None:
        if control_dispatcher is not None:
            control_dispatcher.dispatch_available()

        active_panel_commands.synchronize_radio_state()
        shared_spot_tune_status.refresh()
        repeater_persistence_status = (
            repeater_panel_runtime.synchronize_completed_persistence()
        )
        if dmr_panel_runtime is not None:
            for dmr_event in dmr_panel_runtime.synchronize_commit_events():
                if dmr_event.kind is DmrCommitEventKind.SUCCEEDED:
                    log_panel.request_sync()

        weather_presentation = weather_panel.update(
            runtime.latest_forge_weather_state
        )
        weather_alert_presentation = weather_alert_panel.update(
            runtime.latest_forge_weather_alert_state
        )
        weather_alert_viewport_presentation = weather_alert_viewport.synchronize(
            weather_alert_presentation
        )

        gps_state = runtime.latest_gps_state
        live_map_presentation = live_map_controller.update(gps_state)
        if runtime.live_map is not None and live_map_presentation.position is not None:
            map_width, map_height = live_map_widgets.viewport_size
            if map_width >= 64 and map_height >= 64:
                runtime.live_map.request_viewport(
                    live_map_presentation.position,
                    width_px=map_width,
                    height_px=map_height,
                )
        live_map_snapshot = runtime.latest_live_map_state
        if runtime.pota_map_markers is not None:
            if (
                live_map_controller.pota_position_is_recent(
                    live_map_presentation,
                    grace_after=timedelta(seconds=config.pota_map.gps_grace_period_s),
                )
                and live_map_snapshot is not None
                and live_map_snapshot.viewport is not None
            ):
                runtime.pota_map_markers.request_viewport(live_map_snapshot.viewport)
            else:
                runtime.pota_map_markers.clear()
        if (
            runtime.live_radar is not None
            and live_map_snapshot is not None
            and live_map_snapshot.viewport is not None
        ):
            runtime.live_radar.request_viewport(live_map_snapshot.viewport)
        live_map_widgets.update(
            live_map_presentation,
            live_map_snapshot,
            runtime.latest_live_radar_state,
            runtime.latest_pota_map_marker_state,
            weather_presentation,
        )

        connectivity = build_runtime_connectivity_status(
            runtime,
            network_enabled=config.network_keepalive.enabled,
            platform_enabled=config.home_platform.enabled,
        )
        radio_state = runtime.latest_radio_state
        view = build_dashboard_state(
            radio_state,
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

        status_bar.update_statuses(
            build_status_strip_snapshot(
                radio_state,
                status_monitor.latest_state,
            )
        )
        ticker_message = build_status_bar_routine_message(view)
        runtime.status_messages.publish(
            replacement_key="dashboard.routine",
            text=ticker_message,
            presentation=StatusPresentation.NORMAL,
            priority=0,
        )
        current_status = runtime.status_messages.snapshot().current
        if current_status is None:
            status_bar.set_message(ticker_message, foreground=_BRIGHT)
        else:
            status_bar.set_message(
                current_status.text,
                foreground=_status_foreground(current_status.presentation),
            )

        selected_context = context_navigation.state
        if dmr_panel_runtime is not None:
            dmr_panel_runtime.set_polling_enabled(
                selected_context.selected is ContextId.DMR
            )
        set_dmr_expanded_layout(
            selected_context.selected is ContextId.DMR
            and dmr_panel_runtime is not None
        )

        if selected_context.selected in {ContextId.POTA, ContextId.DX}:
            health_frame.grid_remove()
            show_pota_context_body()
            panel_state = shared_spot_panel.state
            panel = build_shared_spot_viewport(panel_state)
            context_title_text.set(panel.title)
            context_title_label.configure(
                font=("DejaVu Sans", _POTA_HEADER_FONT_SIZE, "bold")
            )

            available_wrap_width = max(480, pota_panel_frame.winfo_width() - 36)
            pota_status_label.configure(wraplength=available_wrap_width)
            pota_footer_label.configure(wraplength=available_wrap_width)
            for labels in pota_card_labels:
                labels[0].configure(wraplength=available_wrap_width)
                labels[2].configure(wraplength=available_wrap_width)

            if not panel.has_cards:
                pota_cards_container.grid_remove()
                pota_status_label.grid()
                status_lines = [panel.detail_line, panel.status_line]
                if panel.error_line:
                    status_lines.append(f"ERROR: {panel.error_line}")
                pota_status_text.set("\n".join(status_lines))
                pota_more_above_text.set("")
                pota_more_below_text.set("")
                for card_frame in pota_card_frames:
                    card_frame.grid_remove()
            else:
                pota_status_label.grid_remove()
                pota_cards_container.grid()
                pota_more_above_text.set("▲ MORE ▲" if panel.hidden_above_count else "")
                pota_more_below_text.set("▼ MORE ▼" if panel.hidden_below_count else "")

                for card_index, card_frame in enumerate(pota_card_frames):
                    if card_index >= len(panel.cards):
                        card_frame.grid_remove()
                        continue

                    card = panel.cards[card_index]
                    card_frame.grid()
                    line1_var, line2_var, line3_var, line4_var = pota_card_texts[card_index]
                    line1_var.set(card.line1)
                    line2_var.set(card.line2)
                    line3_var.set(card.line3)
                    line4_var.set(card.line4)

                    card_background, card_foreground = _pota_card_colors(
                        selected=card.selected,
                        worked=card.worked,
                    )
                    visible_border_width = (
                        _POTA_CARD_SELECTED_BORDER_PX
                        if card.selected
                        else _POTA_CARD_NORMAL_BORDER_PX
                    )
                    invisible_border_width = _POTA_CARD_OUTER_PAD_PX - visible_border_width
                    border_color = _BRIGHT if card.selected else _BORDER
                    card_frame.configure(
                        bg=card_background,
                        highlightbackground=border_color,
                        highlightcolor=border_color,
                        highlightthickness=visible_border_width,
                        padx=invisible_border_width,
                        pady=invisible_border_width,
                    )
                    for card_label in pota_card_labels[card_index]:
                        card_label.configure(
                            bg=card_background,
                            fg=card_foreground,
                        )

            footer_lines = [panel.status_line]
            if panel.error_line:
                footer_lines.append(panel.error_line)
            footer_lines.append("SELECT A SPOT — PRESS TO TUNE")
            pota_footer_text.set("\n".join(footer_lines))
        elif selected_context.selected is ContextId.BROWSE:
            show_browse_context_body()
            health_frame.grid_remove()
            context_title_text.set("BROWSE")
            context_title_label.configure(font=("DejaVu Sans", 48, "bold"))
            browse_state = browse_controls.state
            browse_mode_text.set(browse_mode_label(radio_state.mode))
            browse_frequency_text.set(
                f"{radio_state.frequency.mhz:.6f} MHz"
                if radio_state.frequency is not None
                else "---.------ MHz"
            )
            browse_step_text.set(browse_state.step_label.upper())
        elif selected_context.selected is ContextId.REPEATERS:
            show_repeater_context_body()
            health_frame.grid_remove()
            repeater_viewport = build_repeater_viewport(
                repeater_panel.state,
                repeater_persistence_status,
                repeater_configuration.status if repeater_configuration is not None else None,
            )
            context_title_text.set(repeater_viewport.title)
            context_title_label.configure(
                font=("DejaVu Sans", 42, "bold")
            )
            repeater_widgets.update(repeater_viewport)
        elif selected_context.selected is ContextId.WEATHER:
            show_weather_context_body()
            health_frame.grid_remove()
            context_title_text.set(selected_context.definition.title)
            context_title_label.configure(
                font=("DejaVu Sans", 48, "bold")
            )
            weather_widgets.update(
                weather_presentation,
                weather_alert_presentation,
                weather_alert_viewport_presentation,
            )
        elif selected_context.selected is ContextId.LOG:
            show_log_context_body()
            health_frame.grid_remove()
            context_title_text.set(selected_context.definition.title)
            context_title_label.configure(font=("DejaVu Sans", 48, "bold"))
            log_widgets.update(log_panel.latest_state)
        elif selected_context.selected is ContextId.DMR:
            health_frame.grid_remove()
            context_title_text.set(selected_context.definition.title)
            context_title_label.configure(font=("DejaVu Sans", 40, "bold"))
            if dmr_panel_runtime is None:
                show_standard_context_body()
                context_body_text.set(
                    "DMR hotspot monitoring is disabled in configuration."
                )
            else:
                show_dmr_context_body()
                dmr_selection = dmr_panel_runtime.commands.refresh()
                dmr_widgets.update(
                    build_dmr_viewport(
                        dmr_panel_runtime.latest_monitor_state,
                        dmr_selection,
                        dmr_panel_runtime.commit.status,
                    )
                )
        elif selected_context.selected is ContextId.SETTINGS:
            show_settings_context_body()
            context_title_text.set(selected_context.definition.title)
            context_title_label.configure(font=("DejaVu Sans", 48, "bold"))
            settings_widgets.update(settings_panel.state)

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
        if dmr_panel_runtime is not None:
            dmr_panel_runtime.stop()
        log_panel.stop()
        status_monitor.stop()
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

    def execute_panel_action(action: ControlAction) -> None:
        operator_commands.execute(action)

    root.bind(
        "<Up>",
        lambda _event: execute_panel_action(ControlAction.MOVE_PREVIOUS),
    )
    root.bind(
        "<Down>",
        lambda _event: execute_panel_action(ControlAction.MOVE_NEXT),
    )
    root.bind(
        "<Return>",
        lambda _event: execute_panel_action(ControlAction.ACTIVATE_SELECTION),
    )
    root.bind(
        "<KP_Enter>",
        lambda _event: execute_panel_action(ControlAction.ACTIVATE_SELECTION),
    )
    root.bind(
        "<t>",
        lambda _event: execute_panel_action(ControlAction.ACTIVATE_SELECTION),
    )
    root.bind(
        "<T>",
        lambda _event: execute_panel_action(ControlAction.ACTIVATE_SELECTION),
    )
    root.bind(
        "<x>",
        lambda _event: execute_panel_action(ControlAction.BACK),
    )
    root.bind(
        "<X>",
        lambda _event: execute_panel_action(ControlAction.BACK),
    )
    root.bind(
        "]",
        lambda _event: execute_panel_action(ControlAction.PANEL_PRIMARY),
    )
    root.bind(
        ".",
        lambda _event: execute_panel_action(ControlAction.PANEL_SECONDARY),
    )
    root.bind(
        "/",
        lambda _event: execute_panel_action(ControlAction.PANEL_TERTIARY),
    )

    def select_context_shortcut(event: tk.Event[tk.Misc]) -> None:
        if not context_navigation.select_shortcut(event.char):
            return
        active_panel_commands.activate_context(
            context_navigation.state.selected
        )

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
