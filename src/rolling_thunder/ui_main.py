"""Full-screen Raspberry Pi dashboard entry point."""

from __future__ import annotations

import logging
import signal
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from threading import Event, Thread
from time import monotonic

from rolling_thunder.active_panel_commands import (
    CallsignInfoAwareActivePanelCommands,
    SharedSpotActivePanelCommandController,
)
from rolling_thunder.antenna_reference_commands import AntennaAwareActivePanelCommands
from rolling_thunder.antenna_reference_config import AntennaReferenceYamlSource
from rolling_thunder.antenna_reference_panel import AntennaReferencePanelController
from rolling_thunder.antenna_reference_service import AntennaReferenceService
from rolling_thunder.antenna_reference_ui import AntennaReferenceWidgets
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
from rolling_thunder.callsign_info_ui import (
    CallsignInfoOverlayWidgets,
    build_callsign_info_presentation,
    build_local_callsign_info_presentation,
    callsign_info_failure_status,
)
from rolling_thunder.config import ConfigurationError, load_config
from rolling_thunder.contact_commit_controller import ContactCommitController
from rolling_thunder.context_navigation import (
    ContextId,
    ContextNavigationController,
)
from rolling_thunder.control_dispatcher import (
    CompositeEventInterceptor,
    ControlDispatcher,
)
from rolling_thunder.control_source_factory import build_control_gate, build_control_source
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
from rolling_thunder.domain import Contact
from rolling_thunder.dx_worked import DxWorkedRepository, DxWorkedTracker
from rolling_thunder.fm_repeater import FmRepeaterConfigurableRadio
from rolling_thunder.friend_presentation import FRIEND_COLOR, friend_marker
from rolling_thunder.ft8.band_presentation import present_ft8_band_tune
from rolling_thunder.ft8.distance import format_maidenhead_distance
from rolling_thunder.ft8.panel import FT8PanelMode, FT8PanelSnapshot
from rolling_thunder.ft8.ptt_alarm import FT8PttAlarm
from rolling_thunder.ft8.start_control import FT8QsoStartState, FT8QsoStartStatus
from rolling_thunder.ft8.status import operator_ft8_status, target_activity_status
from rolling_thunder.ft8.terminal_return import FT8TerminalReturnTimer
from rolling_thunder.ft8_active_panel_commands import FT8AwareActivePanelCommands
from rolling_thunder.ft8_ui import (
    build_ft8_browser_viewport,
    format_ft8_receive_diagnostic,
    present_ft8_incoming_call,
)
from rolling_thunder.ft8_widgets import FT8Widgets
from rolling_thunder.live_callsign_capture import LiveCallsignCaptureController
from rolling_thunder.live_map import LiveMapController
from rolling_thunder.live_map_ui import LiveMapWidgets
from rolling_thunder.log_panel import ContactLogRepository, LogPanelController
from rolling_thunder.log_panel_commands import LogAwareActivePanelCommands
from rolling_thunder.log_ui import LogWidgets
from rolling_thunder.main import DEFAULT_CONFIG_PATH
from rolling_thunder.meshcore_ohgo_panel import (
    MeshcoreOhgoPanelWorker,
    present_meshcore_ohgo,
)
from rolling_thunder.operator_commands import OperatorCommandController
from rolling_thunder.operator_preferences import OperatorPreferenceRepository
from rolling_thunder.physical_controls import (
    ControlAction,
    ControlActionMapper,
    ControlSource,
)
from rolling_thunder.pota_tune_execution_controller import (
    PotaTuneIntentExecutor,
)
from rolling_thunder.pota_worked import PotaWorkedRepository, PotaWorkedTracker
from rolling_thunder.power_control import (
    LinuxSystemctlPowerAdapter,
    PowerConfirmationController,
    PowerGuardState,
    SettingsPowerEventInterceptor,
    radio_power_guard,
)
from rolling_thunder.radio import RadioConnectionError
from rolling_thunder.receive_tuning import ReceiveTuningService
from rolling_thunder.recovering_control_source import RecoveringControlSource
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
from rolling_thunder.speech_recognition import VoskCallsignRecognizer, VoskModelProvider
from rolling_thunder.station_health import build_station_health
from rolling_thunder.status_bar_ui import StatusBarWidgets
from rolling_thunder.status_messages import StatusPresentation
from rolling_thunder.status_monitor import build_status_monitor
from rolling_thunder.status_strip import (
    build_status_bar_routine_message,
    build_status_strip_snapshot,
)
from rolling_thunder.tron_control_gesture import TronCancelTriplePress
from rolling_thunder.tron_dispatch import dispatch_tron_intent
from rolling_thunder.tron_microphone import (
    PriorityCallsignCapture,
    TronMicrophoneService,
    TronWorkerEvent,
)
from rolling_thunder.ui_timing import UiTiming
from rolling_thunder.us_extra_band_advisory import (
    BandAdvisoryLevel,
    us_extra_band_advisory,
)
from rolling_thunder.weather_alert_panel import (
    WeatherAlertPanelController,
)
from rolling_thunder.weather_alert_viewport import WeatherAlertViewportController
from rolling_thunder.weather_panel import WeatherPanelController
from rolling_thunder.weather_ui import WeatherWidgets

_REFRESH_MS = 250


def _sigterm_close_handler(requested: Event) -> Callable[[int, object], None]:
    """Return a minimal handler that performs no Tk work."""
    def handle(_signum: int, _frame: object) -> None:
        requested.set()

    return handle


def _run_cleanup_steps(
    steps: tuple[tuple[str, Callable[[], object]], ...],
    errors: list[str],
) -> None:
    """Attempt every bounded cleanup step, preserving each truthful failure."""
    for label, callback in steps:
        try:
            callback()
        except Exception as error:  # noqa: BLE001 - cleanup must continue after any step
            errors.append(f"{label}: {error}")
_BACKGROUND = "#080808"
_PANEL_BACKGROUND = "#101010"
_SECONDARY_BACKGROUND = "#151515"
_CONTEXT_SELECTED = "#2a3f4b"
_BROWSE_HEADER_BACKGROUND = "#315f73"
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
_CONTEXT_HEADER_FONT = ("DejaVu Sans", 48, "bold")
_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _CallsignInfoTarget:
    callsign: str | None
    grid: str | None = None


def _callsign_info_target(
    context: ContextId,
    *,
    pending_callsign: str | None,
    ft8_snapshot: FT8PanelSnapshot | None = None,
    selected_ft8_callsign: str | None = None,
    ft8_start_status: FT8QsoStartStatus | None = None,
) -> _CallsignInfoTarget:
    """Resolve only the callsign currently owned by the visible lifecycle."""
    if context is not ContextId.FT8:
        return _CallsignInfoTarget(pending_callsign)
    if ft8_snapshot is None or ft8_snapshot.mode is FT8PanelMode.TERMINAL:
        return _CallsignInfoTarget(None)
    if ft8_snapshot.mode is FT8PanelMode.ACTIVE:
        active = ft8_snapshot.active_context
        if active is None:
            return _CallsignInfoTarget(None)
        return _CallsignInfoTarget(active.remote_callsign, active.remote_grid)
    if (
        ft8_start_status is not None
        and ft8_start_status.state is FT8QsoStartState.PREPARING
    ):
        candidate = ft8_start_status.activity or ft8_start_status.incoming_call
        if candidate is not None:
            return _CallsignInfoTarget(candidate.callsign, candidate.grid)
    if selected_ft8_callsign is None:
        return _CallsignInfoTarget(None)
    matches = tuple(
        activity
        for activity in ft8_snapshot.cq_activity
        if activity.callsign == selected_ft8_callsign
    )
    if len(matches) != 1:
        return _CallsignInfoTarget(None)
    return _CallsignInfoTarget(matches[0].callsign, matches[0].grid)


@contextmanager
def _callsign_info_presentation_boundary(
    hide: Callable[[], None],
) -> Iterator[None]:
    """Isolate the optional overlay from dashboard and radio workflows."""
    try:
        yield
    except Exception:
        _LOGGER.exception("Callsign-info overlay presentation failed")
        try:
            hide()
        except Exception:
            _LOGGER.exception("Callsign-info overlay cleanup failed")


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


def _context_decode_header_text(
    context: ContextId,
    decode_count: int | None,
) -> str:
    """Return decode text only for an FT8 context with an available count."""
    if context is not ContextId.FT8 or decode_count is None:
        return ""
    return f"DECODE {decode_count}"


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

    def ft8_contact_completed(_contact: Contact) -> None:
        """Use the same nonblocking sync request as ordinary and DMR commits."""
        log_panel.request_sync()

    runtime = ApplicationRuntime.from_config(
        config,
        secrets=secrets,
        ft8_completed_contact_handler=ft8_contact_completed,
    )
    preference_repository = OperatorPreferenceRepository(
        config.storage.database_path
    )
    stored_radar_image = preference_repository.read_radar_image_enabled()
    if runtime.live_radar is not None and stored_radar_image is not None:
        runtime.live_radar.set_display_enabled(stored_radar_image)
    stored_callsign_info = preference_repository.read_callsign_info_enabled()
    if runtime.callsign_info is not None and stored_callsign_info is not None:
        runtime.callsign_info.set_enabled(stored_callsign_info)

    preference_service = runtime.operator_preferences
    if preference_service is None:
        raise RuntimeError("Operator preferences are required by the Settings panel.")
    settings_panel = DashboardSettingsController(
        runtime.map_zoom_settings,
        runtime.live_radar,
        preference_service,
        runtime.map_solar,
        runtime.callsign_info,
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
    tron_microphone: TronMicrophoneService | None = None
    capture: (
        LiveCallsignCaptureController
        | MockTranscriptController
        | PriorityCallsignCapture
    )
    if config.speech.enabled:
        model_path = config.speech.model_path
        if model_path is None:
            print("Rolling Thunder startup error: speech model path is unavailable")
            log_panel.stop()
            runtime.stop()
            return 3
        model_provider = VoskModelProvider(model_path)
        if config.tron.enabled:
            tron_microphone = TronMicrophoneService(
                audio_device=config.speech.audio_device,
                model_provider=model_provider,
                sample_rate=config.speech.sample_rate,
                channels=config.speech.channels,
                duration_s=config.tron.capture_duration_seconds,
            )
        recognizer = VoskCallsignRecognizer(
            model_path=model_path,
            audio_device=config.speech.audio_device,
            duration_s=config.speech.capture_duration_seconds,
            sample_rate=config.speech.sample_rate,
            channels=config.speech.channels,
            model_provider=model_provider,
        )
        live_capture = LiveCallsignCaptureController(
            recognizer,
            on_finished=(
                None if tron_microphone is None else tron_microphone.callsign_finished
            ),
        )

    capture = live_capture if live_capture is not None else mock_transcripts
    if tron_microphone is not None and live_capture is not None:
        capture = PriorityCallsignCapture(live_capture, tron_microphone)
    # OHGO is read-only and polled off-Tk; Forge alone owns its secret.
    ohgo_panel_worker = MeshcoreOhgoPanelWorker(
        str(config.forge.api_url)
        if config.forge.enabled and config.forge.api_url
        else None
    )
    ohgo_panel_worker.start()

    context_navigation = ContextNavigationController(
        include_antennas=config.antenna_reference.enabled
    )
    antenna_panel = (
        AntennaReferencePanelController(
            AntennaReferenceService(
                AntennaReferenceYamlSource(config.antenna_reference.data_file)
            )
        )
        if config.antenna_reference.enabled
        and config.antenna_reference.data_file is not None
        else None
    )
    if antenna_panel is not None:
        antenna_panel.start()
    pota_worked = PotaWorkedTracker(
        PotaWorkedRepository(config.storage.database_path)
    )
    dx_worked = DxWorkedTracker(DxWorkedRepository(config.storage.database_path))
    shared_spot_panel = SharedSpotPanelController(
        runtime,
        pota_worked_status=pota_worked,
        dx_worked_status=dx_worked,
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
        if antenna_panel is not None:
            antenna_panel.close()
        log_panel.stop()
        runtime.stop()
        return 3
    active_panel_commands: (
        CallsignInfoAwareActivePanelCommands
        |
        LogAwareActivePanelCommands
        | DmrAwareActivePanelCommands
        | FT8AwareActivePanelCommands
        | AntennaAwareActivePanelCommands
    )
    if dmr_panel_runtime is None:
        active_panel_commands = log_aware_active_panel_commands
    else:
        active_panel_commands = DmrAwareActivePanelCommands(
            context_navigation,
            log_aware_active_panel_commands,
            dmr_panel_runtime.commands,
        )
    if runtime.ft8_panel is not None:
        active_panel_commands = FT8AwareActivePanelCommands(
            context_navigation,
            active_panel_commands,
            runtime.ft8_panel,
            cycle_band=(
                None
                if runtime.ft8_band_control is None
                else runtime.ft8_band_control.cycle_band
            ),
            enter_ft8=runtime.enter_ft8_context,
            exit_ft8=runtime.exit_ft8_context,
            clear_start_status=runtime.clear_ft8_qso_start_status,
            pending_callsign=capture,
        )
    if antenna_panel is not None:
        active_panel_commands = AntennaAwareActivePanelCommands(
            context_navigation,
            active_panel_commands,
            antenna_panel,
        )
    if runtime.callsign_info is not None:
        active_panel_commands = CallsignInfoAwareActivePanelCommands(
            context_navigation,
            active_panel_commands,
            runtime.callsign_info,
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
        dx_context_provider=lambda: context_navigation.state.selected is ContextId.DX,
        browse_context_provider=lambda: (
            context_navigation.state.selected is ContextId.BROWSE
        ),
        pota_spots_provider=lambda: shared_pota_spots_for_contact(
            shared_spot_panel.visible_spots
        ),
        pota_worked_tracker=pota_worked,
        dx_worked_tracker=dx_worked,
        tx_power_provider=(
            runtime.read_tx_power_watts
            if config.contact_logging.capture_tx_power
            else None
        ),
        weather_notes_enabled=config.contact_logging.append_weather_notes,
    )
    # Supervised visual acceptance uses an ISOLATED alarm instance. Never touches
    # runtime.ft8_ptt_alarm, CAT, PTT, or the production transmit authorization.
    visual_test = FT8PttAlarm()
    visual_test_deadline = [0.0]
    visual_test_file = Path('/home/geoff/rolling-thunder-h4-visual-test.trigger')

    def visual_test_active() -> bool:
        return visual_test_deadline[0] > monotonic()

    def acknowledge_ptt_alarm() -> bool:
        if visual_test_active():
            if visual_test.active:
                visual_test.voice_cancel()
            return True
        if not runtime.ft8_ptt_alarm.active:
            return False
        runtime.ft8_ptt_alarm.voice_cancel()
        return True

    def handle_ptt_unlock_action(action: ControlAction) -> bool:
        if visual_test_active():
            if (not visual_test.active and visual_test.tx_inhibited
                    and visual_test.unlock_step(
                        action, ft8_screen=context_navigation.state.selected is ContextId.FT8,
                        radio_confirmed_receive=True,
                    )):
                visual_test_deadline[0] = 0.0
            return True
        alarm = runtime.ft8_ptt_alarm
        if not alarm.tx_inhibited:
            return False
        # All command presses during a lock are consumed, even an incorrect step.
        # The operator must have manually powered down/recovered the radio.
        # The sequence acknowledges this; CAT status is not RF proof.
        alarm.unlock_step(
            action,
            ft8_screen=context_navigation.state.selected is ContextId.FT8,
            radio_confirmed_receive=True,
        )
        return True

    ui_timing = UiTiming.from_environment()

    def power_guard() -> PowerGuardState:
        radio = runtime.latest_radio_state
        start_status = runtime.latest_ft8_qso_start_status
        return PowerGuardState(
            ft8_context_attached=runtime.latest_ft8_qso_context is not None,
            ft8_busy=start_status is not None and start_status.busy,
            hardware_transmitting=(
                runtime.ft8_hardware_transmit is not None
                and runtime.ft8_hardware_transmit.transmitting
            ),
            ptt_alarm_or_inhibited=(
                runtime.ft8_ptt_alarm.active or runtime.ft8_ptt_alarm.tx_inhibited
            ),
            radio_transmitting=radio_power_guard(radio),
            contact_commit_active=contact_commit.status.committing,
            dmr_commit_active=(
                dmr_panel_runtime is not None
                and dmr_panel_runtime.commit.status.committing
            ),
        )

    power_confirmation = PowerConfirmationController(
        LinuxSystemctlPowerAdapter(),
        preference_service,
        power_guard,
    )
    settings_panel.attach_power_confirmation(power_confirmation)
    operator_commands = OperatorCommandController(
        capture,
        contact_commit,
        context_navigation,
        radio_state=lambda: runtime.latest_radio_state,
        active_panel=active_panel_commands,
        cancel_ptt_alarm=acknowledge_ptt_alarm,
        ptt_unlock_step=handle_ptt_unlock_action,
        mutation_blocked=lambda: (
            power_confirmation.state.pending or close_started.is_set()
        ),
    )

    control_source: ControlSource | None = None
    control_dispatcher: ControlDispatcher | None = None
    if config.physical_controls.enabled:
        control_source = build_control_source(config.physical_controls)
        control_start_error = open_control_source(control_source)
        if control_start_error is not None:
            print(f"Rolling Thunder physical controls unavailable: {control_start_error}")

        tron_toggle_interceptor = TronCancelTriplePress(
            on_toggle=lambda: toggle_tron_listening(),
            allowed=lambda: (
                not power_confirmation.state.pending
                and not runtime.ft8_ptt_alarm.active
                and not runtime.ft8_ptt_alarm.tx_inhibited
                and not visual_test_active()
                and not visual_test.tx_inhibited
                and not close_started.is_set()
            ),
        )
        settings_interceptor = (
            SettingsPowerEventInterceptor(
                power_confirmation,
                context=lambda: context_navigation.state.selected,
                selection=lambda: settings_panel.state.selection.selected,
                recovery_snapshot=lambda: control_source.snapshot,
            )
            if isinstance(control_source, RecoveringControlSource)
            else None
        )
        control_dispatcher = ControlDispatcher(
            control_source,
            ControlActionMapper(config.physical_controls.mappings),
            build_control_gate(config.physical_controls, control_source),
            operator_commands,
            action_observer=(
                ui_timing.observe_control_action if ui_timing.enabled else None
            ),
            event_interceptor=CompositeEventInterceptor(
                tron_toggle_interceptor,
                settings_interceptor,
            ),
        )

    root = tk.Tk()
    root.title("Rolling Thunder v4")
    root.configure(bg=_BACKGROUND, cursor="none")
    root.attributes("-fullscreen", True)
    # Emergency warning overlays every dashboard context; stays until voice cancel.
    ptt_alert = tk.Frame(root, bg="#fff000", highlightthickness=8,
                         highlightbackground="#101010")
    tk.Label(ptt_alert, text="WARNING: RADIO MAY BE STUCK TRANSMITTING",
             bg="#fff000", fg="#000000", font=("DejaVu Sans", 26, "bold"),
             wraplength=1200).pack(padx=22, pady=(16, 8))
    tk.Label(ptt_alert, text="STOP SAFELY. POWER DOWN RADIO MANUALLY.\n"
             "PRESS VOICE CANCEL TO ACKNOWLEDGE.",
             bg="#fff000", fg="#000000", font=("DejaVu Sans", 23, "bold"),
             justify="center").pack(padx=22, pady=(0, 16))
    ptt_unlock = tk.Frame(root, bg="#148137", highlightthickness=5,
                          highlightbackground="#ffffff")
    tk.Label(
        ptt_unlock,
        text="Press command buttons in this order Command 1, Command 3, Command 1 to unlock",
        bg="#148137", fg="#ffffff", font=("DejaVu Sans", 26, "bold"),
        wraplength=1100, justify="center",
    ).pack(padx=18, pady=22)
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
    pending_call_cell = tk.Frame(logger, bg=_PANEL_BACKGROUND)
    pending_call_cell.grid(row=1, column=0, columnspan=2, sticky="nsew")
    pending_call_cell.grid_columnconfigure(0, weight=1)
    pending_call_cell.grid_columnconfigure(2, weight=1)
    callsign_label = tk.Label(
        pending_call_cell,
        textvariable=callsign_text,
        bg=_PANEL_BACKGROUND,
        fg=_BRIGHT,
        font=("DejaVu Sans", 72, "bold"),
        anchor="center",
    )
    callsign_label.grid(row=0, column=0, sticky="e", pady=0)
    pending_friend_label = tk.Label(pending_call_cell, text="", bg=_PANEL_BACKGROUND,
                                    fg=FRIEND_COLOR, font=("DejaVu Sans", 28, "bold"))
    pending_friend_label.grid(row=0, column=1, sticky="w")

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

    context_header = tk.Frame(context_content, bg=_SECONDARY_BACKGROUND)
    context_header.grid(row=0, column=0, sticky="ew", pady=(2, 8))
    context_header.grid_columnconfigure(0, weight=1)

    context_title_text = tk.StringVar(value="POTA")
    context_title_label = tk.Label(
        context_header,
        textvariable=context_title_text,
        bg=_SECONDARY_BACKGROUND,
        fg=_BRIGHT,
        font=_CONTEXT_HEADER_FONT,
        anchor="center",
    )
    context_title_label.grid(row=0, column=0, sticky="ew")
    context_decode_text = tk.StringVar(value="")
    context_decode_label = tk.Label(
        context_header,
        textvariable=context_decode_text,
        bg=_SECONDARY_BACKGROUND,
        fg=_BRIGHT,
        font=_CONTEXT_HEADER_FONT,
        anchor="e",
    )
    context_decode_label.grid(row=0, column=1, sticky="e", padx=(12, 0))

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
    antenna_widgets = (
        AntennaReferenceWidgets(context_content)
        if antenna_panel is not None
        else None
    )
    weather_widgets = WeatherWidgets(context_content)
    repeater_widgets = RepeaterWidgets(context_content)
    log_widgets = LogWidgets(context_content)
    dmr_widgets = DmrWidgets(context_content)
    ft8_widgets = FT8Widgets(context_content)

    browse_frame = tk.Frame(context_content, bg=_SECONDARY_BACKGROUND)
    browse_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=(4, 8))
    browse_frame.grid_columnconfigure(0, weight=1)
    browse_frame.grid_columnconfigure(1, weight=1)
    browse_frame.grid_rowconfigure(0, weight=3)
    browse_frame.grid_rowconfigure(1, weight=2)
    browse_frame.grid_remove()

    browse_frequency_card = tk.Frame(
        browse_frame,
        bg=_PANEL_BACKGROUND,
        highlightthickness=2,
        highlightbackground=_BROWSE_HEADER_BACKGROUND,
    )
    browse_frequency_card.grid(
        row=0,
        column=0,
        columnspan=2,
        sticky="nsew",
        padx=4,
        pady=(4, 8),
    )
    browse_frequency_card.grid_columnconfigure(0, weight=1)
    browse_frequency_card.grid_rowconfigure(1, weight=1)
    browse_frequency_card.grid_rowconfigure(2, weight=0)

    tk.Label(
        browse_frequency_card,
        text="FREQUENCY",
        bg=_BROWSE_HEADER_BACKGROUND,
        fg=_BRIGHT,
        font=("DejaVu Sans", 44, "bold"),
        anchor="center",
    ).grid(row=0, column=0, sticky="ew", ipady=7)

    browse_frequency_text = tk.StringVar(value="---.--- MHz")
    tk.Label(
        browse_frequency_card,
        textvariable=browse_frequency_text,
        bg=_PANEL_BACKGROUND,
        fg=_BRIGHT,
        font=("DejaVu Sans", 40, "bold"),
        anchor="center",
    ).grid(row=1, column=0, sticky="nsew", padx=12, pady=12)

    browse_warning_text = tk.StringVar(value="")
    browse_warning_label = tk.Label(
        browse_frequency_card,
        textvariable=browse_warning_text,
        bg=_FAILURE,
        fg=_BRIGHT,
        font=("DejaVu Sans", 26, "bold"),
        anchor="center",
        justify="center",
    )
    browse_warning_label.grid(
        row=2,
        column=0,
        sticky="ew",
        padx=12,
        pady=(0, 12),
        ipady=7,
    )
    browse_warning_label.grid_remove()

    browse_mode_card = tk.Frame(
        browse_frame,
        bg=_PANEL_BACKGROUND,
        highlightthickness=2,
        highlightbackground=_BROWSE_HEADER_BACKGROUND,
    )
    browse_mode_card.grid(
        row=1,
        column=0,
        sticky="nsew",
        padx=(4, 6),
        pady=(0, 4),
    )
    browse_mode_card.grid_columnconfigure(0, weight=1)
    browse_mode_card.grid_rowconfigure(1, weight=1)

    tk.Label(
        browse_mode_card,
        text="MODE",
        bg=_BROWSE_HEADER_BACKGROUND,
        fg=_BRIGHT,
        font=("DejaVu Sans", 40, "bold"),
        anchor="center",
    ).grid(row=0, column=0, sticky="ew", ipady=6)

    browse_mode_text = tk.StringVar(value="--")
    tk.Label(
        browse_mode_card,
        textvariable=browse_mode_text,
        bg=_PANEL_BACKGROUND,
        fg=_BRIGHT,
        font=("DejaVu Sans", 36, "bold"),
        anchor="center",
    ).grid(row=1, column=0, sticky="nsew", padx=10, pady=10)

    browse_step_card = tk.Frame(
        browse_frame,
        bg=_PANEL_BACKGROUND,
        highlightthickness=2,
        highlightbackground=_BROWSE_HEADER_BACKGROUND,
    )
    browse_step_card.grid(
        row=1,
        column=1,
        sticky="nsew",
        padx=(6, 4),
        pady=(0, 4),
    )
    browse_step_card.grid_columnconfigure(0, weight=1)
    browse_step_card.grid_rowconfigure(1, weight=1)

    tk.Label(
        browse_step_card,
        text="STEP",
        bg=_BROWSE_HEADER_BACKGROUND,
        fg=_BRIGHT,
        font=("DejaVu Sans", 40, "bold"),
        anchor="center",
    ).grid(row=0, column=0, sticky="ew", ipady=6)

    browse_step_text = tk.StringVar(value="100 Hz")
    tk.Label(
        browse_step_card,
        textvariable=browse_step_text,
        bg=_PANEL_BACKGROUND,
        fg=_WARNING,
        font=("DejaVu Sans", 36, "bold"),
        anchor="center",
    ).grid(row=1, column=0, sticky="nsew", padx=10, pady=10)

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
    pota_friend_labels: list[tk.Label] = []
    pota_call_headers: list[tk.Frame] = []
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

        call_header = tk.Frame(card_frame, bg=_PANEL_BACKGROUND)
        call_header.grid(row=0, column=0, sticky="ew")
        call_header.grid_columnconfigure(1, weight=1)
        friend_label = tk.Label(call_header, text="", bg=_PANEL_BACKGROUND,
                               fg=FRIEND_COLOR, font=("DejaVu Sans", _POTA_BODY_FONT_SIZE, "bold"))
        friend_label.grid(row=0, column=0, sticky="w")
        pota_friend_labels.append(friend_label)
        pota_call_headers.append(call_header)
        callsign_label = tk.Label(
            call_header,
            textvariable=callsign_var,
            bg=_PANEL_BACKGROUND,
            fg=_BRIGHT,
            font=("DejaVu Sans", _POTA_BODY_FONT_SIZE, "bold"),
            anchor="w",
            justify="left",
            padx=12,
            pady=2,
        )
        callsign_label.grid(row=0, column=1, sticky="ew")

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
    callsign_info_widgets = CallsignInfoOverlayWidgets(situational)

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
        if antenna_widgets is not None:
            antenna_widgets.hide()
        weather_widgets.hide()
        log_widgets.hide()
        dmr_widgets.hide()
        ft8_widgets.hide()
        context_body_label.grid()

    def show_pota_context_body() -> None:
        """Show the POTA/DX card viewport and hide other context bodies."""
        browse_frame.grid_remove()
        context_body_label.grid_remove()
        repeater_widgets.hide()
        settings_widgets.hide()
        if antenna_widgets is not None:
            antenna_widgets.hide()
        weather_widgets.hide()
        log_widgets.hide()
        dmr_widgets.hide()
        ft8_widgets.hide()
        pota_panel_frame.grid()

    def show_browse_context_body() -> None:
        """Show free-form Browse radio state and hide unrelated context bodies."""
        context_body_label.grid_remove()
        pota_panel_frame.grid_remove()
        repeater_widgets.hide()
        settings_widgets.hide()
        if antenna_widgets is not None:
            antenna_widgets.hide()
        weather_widgets.hide()
        log_widgets.hide()
        dmr_widgets.hide()
        ft8_widgets.hide()
        browse_frame.grid()

    def show_repeater_context_body() -> None:
        """Show local repeaters and hide the generic/POTA/settings/weather bodies."""
        browse_frame.grid_remove()
        context_body_label.grid_remove()
        pota_panel_frame.grid_remove()
        settings_widgets.hide()
        if antenna_widgets is not None:
            antenna_widgets.hide()
        weather_widgets.hide()
        log_widgets.hide()
        dmr_widgets.hide()
        ft8_widgets.hide()
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
        ft8_widgets.hide()
        settings_widgets.show()
        if antenna_widgets is not None:
            antenna_widgets.hide()

    def show_weather_context_body() -> None:
        """Show retained weather and hide other context bodies."""
        browse_frame.grid_remove()
        context_body_label.grid_remove()
        pota_panel_frame.grid_remove()
        repeater_widgets.hide()
        settings_widgets.hide()
        if antenna_widgets is not None:
            antenna_widgets.hide()
        log_widgets.hide()
        dmr_widgets.hide()
        ft8_widgets.hide()
        weather_widgets.show()

    def show_log_context_body() -> None:
        """Show the local Log snapshot and hide every unrelated context body."""
        browse_frame.grid_remove()
        context_body_label.grid_remove()
        pota_panel_frame.grid_remove()
        repeater_widgets.hide()
        settings_widgets.hide()
        if antenna_widgets is not None:
            antenna_widgets.hide()
        weather_widgets.hide()
        dmr_widgets.hide()
        ft8_widgets.hide()
        log_widgets.show()

    def show_dmr_context_body() -> None:
        """Show DMR activity and hide every unrelated context body."""
        context_body_label.grid_remove()
        pota_panel_frame.grid_remove()
        repeater_widgets.hide()
        settings_widgets.hide()
        if antenna_widgets is not None:
            antenna_widgets.hide()
        weather_widgets.hide()
        log_widgets.hide()
        ft8_widgets.hide()
        dmr_widgets.show()

    def show_ft8_context_body() -> None:
        """Show the large FT8 CQ browser and hide unrelated context bodies."""
        browse_frame.grid_remove()
        context_body_label.grid_remove()
        pota_panel_frame.grid_remove()
        repeater_widgets.hide()
        settings_widgets.hide()
        if antenna_widgets is not None:
            antenna_widgets.hide()
        weather_widgets.hide()
        log_widgets.hide()
        dmr_widgets.hide()
        ft8_widgets.show()

    def show_antenna_context_body() -> None:
        """Show the offline antenna advisory and hide unrelated context bodies."""
        browse_frame.grid_remove()
        context_body_label.grid_remove()
        pota_panel_frame.grid_remove()
        repeater_widgets.hide()
        settings_widgets.hide()
        weather_widgets.hide()
        log_widgets.hide()
        dmr_widgets.hide()
        ft8_widgets.hide()
        if antenna_widgets is not None:
            antenna_widgets.show()

    acknowledged_ft8_tune: list[object | None] = [None]
    ft8_terminal_return = FT8TerminalReturnTimer(hold_seconds=3.0)
    tron_popup_window: list[tk.Toplevel | None] = [None]
    tron_popup_after_id: list[str | None] = [None]

    def dismiss_tron_popup() -> None:
        after_id = tron_popup_after_id[0]
        tron_popup_after_id[0] = None
        if after_id is not None:
            try:
                root.after_cancel(after_id)
            except tk.TclError:
                pass
        window = tron_popup_window[0]
        tron_popup_window[0] = None
        if window is not None:
            try:
                if window.winfo_exists():
                    window.destroy()
            except tk.TclError:
                pass

    def show_tron_popup(message: str) -> None:
        dismiss_tron_popup()
        window = tk.Toplevel(root)
        tron_popup_window[0] = window
        window.withdraw()
        window.overrideredirect(True)
        window.configure(bg="#FFF4DF", highlightthickness=3, highlightbackground="#E58B2A")
        label = tk.Label(
            window,
            text=message,
            font=("DejaVu Sans", 20, "bold"),
            fg="#17212B",
            bg="#FFF4DF",
            justify="center",
            wraplength=max(420, int(root.winfo_width() * 0.75)),
            padx=24,
            pady=16,
        )
        label.pack()
        window.update_idletasks()
        x = root.winfo_rootx() + max(0, (root.winfo_width() - window.winfo_width()) // 2)
        y = root.winfo_rooty() + max(0, (root.winfo_height() - window.winfo_height()) // 2)
        window.geometry(f"+{x}+{y}")
        window.deiconify()
        window.lift()
        tron_popup_after_id[0] = root.after(3000, dismiss_tron_popup)

    def publish_tron_status(message: str, *, error: bool = False) -> None:
        runtime.status_messages.publish(
            replacement_key="tron.voice",
            text=message,
            presentation=(
                StatusPresentation.ERROR if error else StatusPresentation.NORMAL
            ),
            priority=30,
        )

    def toggle_tron_listening() -> None:
        if tron_microphone is None:
            show_tron_popup("TRON VOICE DISABLED")
            return
        if tron_microphone.listening_requested:
            tron_microphone.pause_listening()
            show_tron_popup("TRON STOPPED")
            return
        started = tron_microphone.start_listening()
        if started or tron_microphone.listening_requested:
            show_tron_popup("TRON STARTING")
        else:
            show_tron_popup("TRON START FAILED")

    def refresh() -> None:
        if close_started.is_set():
            return
        if sigterm_requested.is_set():
            close()
            return
        refresh_start = ui_timing.begin_refresh()
        if runtime.ft8_panel is not None and ft8_terminal_return.poll(
            runtime.ft8_panel.qso_state,
            monotonic(),
        ):
            try:
                runtime.ft8_panel.return_to_browser()
            except RuntimeError:
                _LOGGER.info("FT8 terminal return was superseded by a lifecycle change")

        # SSH trigger is consumed only in receive-only mode while FT8 is visible.
        # Never trigger the actual PTT alarm state or affect radio authority.
        if visual_test_file.is_file():
            visual_test_file.unlink(missing_ok=True)
            if (not config.ft8.transmit.enabled
                    and context_navigation.state.selected is ContextId.FT8
                    and not runtime.ft8_ptt_alarm.tx_inhibited):
                visual_test.trigger()
                visual_test_deadline[0] = monotonic() + 90.0
        if ((visual_test_active() and visual_test.tx_inhibited and not visual_test.active)
                or (runtime.ft8_ptt_alarm.tx_inhibited and not runtime.ft8_ptt_alarm.active)) and (
            context_navigation.state.selected is ContextId.FT8
        ):
            ptt_unlock.place(relx=0.5, rely=0.5, anchor="center", relwidth=0.96)
            ptt_unlock.lift()
        else:
            ptt_unlock.place_forget()
        if runtime.ft8_ptt_alarm.active or (visual_test_active() and visual_test.active):
            ptt_alert.place(relx=0.5, rely=0.5, anchor="center", relwidth=0.96)
            ptt_alert.lift()
        else:
            ptt_alert.place_forget()
        ui_timing.checkpoint("pre_controls")
        if isinstance(control_source, RecoveringControlSource):
            recovery = control_source.snapshot
            power_confirmation.retain_session(
                recovery.session_nonce,
                recovery.health.generation,
                recovery.health.state,
            )
        else:
            power_confirmation.retain_session(None, None, None)
        if control_dispatcher is not None:
            controls_start = ui_timing.start()
            try:
                control_dispatcher.dispatch_available()
            finally:
                ui_timing.observe("controls", controls_start)
        ui_timing.checkpoint("controls")

        # Callsign controls run first so a queued physical press invalidates any
        # command waiting in the bounded Tron event queue before dispatch.
        if tron_microphone is not None:
            def handle_tron_event(tron_event: TronWorkerEvent) -> None:
                if tron_event.kind == "intent" and tron_event.intent is not None:
                    response = dispatch_tron_intent(
                        tron_event.intent,
                        context_navigation,
                        on_context_changed=active_panel_commands.activate_context,
                        panel_commands=active_panel_commands,
                    )
                    if response is not None and tron_event.intent.action == "status":
                        show_tron_popup(response)
                elif tron_event.kind == "audio_error":
                    publish_tron_status(
                        "Tron microphone unavailable; callsign capture remains available.",
                        error=True,
                    )
                elif tron_event.kind == "recognition_error":
                    publish_tron_status("Tron could not recognize that phrase.")

            tron_microphone.dispatch_pending_events(handle_tron_event, limit=8)
            if tron_microphone.callsign_preemption_stalled():
                publish_tron_status(
                    "Callsign capture is waiting; Tron has not released the microphone.",
                    error=True,
                )

        with ui_timing.subphase("radio_sync"):
            active_panel_commands.synchronize_radio_state()
        with ui_timing.subphase("spot_tune_status"):
            shared_spot_tune_status.refresh()
        with ui_timing.subphase("repeater_persistence"):
            repeater_persistence_status = (
                repeater_panel_runtime.synchronize_completed_persistence()
            )
        with ui_timing.subphase("dmr_commits"):
            if dmr_panel_runtime is not None:
                for dmr_event in dmr_panel_runtime.synchronize_commit_events():
                    if dmr_event.kind is DmrCommitEventKind.SUCCEEDED:
                        log_panel.request_sync()

        with ui_timing.subphase("weather_update"):
            weather_presentation = weather_panel.update(
                runtime.latest_forge_weather_state
            )
        with ui_timing.subphase("weather_alert_update"):
            weather_alert_presentation = weather_alert_panel.update(
                runtime.latest_forge_weather_alert_state
            )
        with ui_timing.subphase("weather_alert_viewport"):
            weather_alert_viewport_presentation = weather_alert_viewport.synchronize(
                weather_alert_presentation
            )

        with ui_timing.subphase("gps_snapshot"):
            gps_state = runtime.latest_gps_state
        with ui_timing.subphase("map_controller"):
            live_map_presentation = live_map_controller.update(gps_state)
        if runtime.live_map is not None and live_map_presentation.position is not None:
            map_width, map_height = live_map_widgets.viewport_size
            if map_width >= 64 and map_height >= 64:
                with ui_timing.subphase("map_viewport_request"):
                    runtime.live_map.request_viewport(
                        live_map_presentation.position,
                        width_px=map_width,
                        height_px=map_height,
                    )
        with ui_timing.subphase("map_snapshot"):
            live_map_snapshot = runtime.latest_live_map_state
        with ui_timing.subphase("pota_viewport_request"):
            if runtime.pota_map_markers is not None:
                if (
                    live_map_controller.pota_position_is_recent(
                        live_map_presentation,
                        grace_after=timedelta(
                            seconds=config.pota_map.gps_grace_period_s
                        ),
                    )
                    and live_map_snapshot is not None
                    and live_map_snapshot.viewport is not None
                ):
                    runtime.pota_map_markers.request_viewport(
                        live_map_snapshot.viewport
                    )
                else:
                    runtime.pota_map_markers.clear()
        with ui_timing.subphase("radar_viewport_request"):
            if (
                runtime.live_radar is not None
                and live_map_snapshot is not None
                and live_map_snapshot.viewport is not None
            ):
                runtime.live_radar.request_viewport(live_map_snapshot.viewport)
        ft8_map_status: str | None = None
        ft8_remote_status: str | None = None
        if (
            context_navigation.state.selected is ContextId.FT8
            and runtime.ft8_panel is not None
        ):
            with ui_timing.subphase("ft8_panel_snapshot"):
                map_ft8_snapshot = runtime.ft8_panel.snapshot()
                start_status = runtime.latest_ft8_qso_start_status
                selected_target = (
                    map_ft8_snapshot.active_context.remote_callsign
                    if map_ft8_snapshot.active_context is not None
                    else runtime.ft8_panel.selected_callsign
                )
            if runtime.ft8_receive is not None:
                with ui_timing.subphase("ft8_receive_target"):
                    runtime.ft8_receive.select_activity_target(selected_target)
                with ui_timing.subphase("ft8_receive_snapshot"):
                    receive_snapshot = runtime.latest_ft8_receive_state
                    ft8_remote_status = target_activity_status(
                        None
                        if receive_snapshot is None
                        else receive_snapshot.target_activity
                    )
            with ui_timing.subphase("ft8_presentation"):
                if map_ft8_snapshot.active_context is not None:
                    tries = map_ft8_snapshot.attempt_count
                    allowed = map_ft8_snapshot.attempts_per_state
                else:
                    tries = allowed = 0
                ft8_map_status = operator_ft8_status(
                    panel_mode=map_ft8_snapshot.mode,
                    qso_state=map_ft8_snapshot.qso_state,
                    selected_callsign=runtime.ft8_panel.selected_callsign,
                    start_state=None if start_status is None else start_status.state,
                ).value
                if selected_target is not None:
                    ft8_map_status += f"  {selected_target}"
                if tries and allowed:
                    ft8_map_status += f"  TRY {tries}/{allowed}"
        elif runtime.ft8_receive is not None:
            with ui_timing.subphase("ft8_receive_target"):
                runtime.ft8_receive.select_activity_target(None)

        ui_timing.checkpoint("map_prepare")
        map_start = ui_timing.start()
        try:
            live_map_widgets.update(
                live_map_presentation,
            live_map_snapshot,
            runtime.latest_live_radar_state,
            runtime.latest_pota_map_marker_state,
            weather_presentation,
            ft8_status=ft8_map_status,
                ft8_remote_status=ft8_remote_status,
                timing=ui_timing,
            )
        finally:
            ui_timing.observe("map", map_start)
        ui_timing.checkpoint("map_update")

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
        friends = (runtime.known_callsigns.cache.friends
                   if runtime.known_callsigns is not None else frozenset())
        pending_callsign = "" if view.pending_callsign == "—" else view.pending_callsign

        pota_latitude: float | None = None
        pota_longitude: float | None = None
        callsign_info_target = _callsign_info_target(
            context_navigation.state.selected,
            pending_callsign=pending_callsign or None,
        )

        if (
            context_navigation.state.selected is ContextId.FT8
            and runtime.ft8_panel is not None
        ):
            ft8_panel_snapshot = runtime.ft8_panel.snapshot()
            callsign_info_target = _callsign_info_target(
                ContextId.FT8,
                pending_callsign=pending_callsign or None,
                ft8_snapshot=ft8_panel_snapshot,
                selected_ft8_callsign=runtime.ft8_panel.selected_callsign,
                ft8_start_status=runtime.latest_ft8_qso_start_status,
            )

        selected_spot = shared_spot_panel.selected_spot
        if (
            context_navigation.state.selected is ContextId.POTA
            and selected_spot is not None
            and selected_spot.callsign == pending_callsign
            and selected_spot.pota is not None
            and selected_spot.pota.latitude is not None
            and selected_spot.pota.longitude is not None
        ):
            pota_latitude = selected_spot.pota.latitude
            pota_longitude = selected_spot.pota.longitude

        if runtime.callsign_info is not None:
            with _callsign_info_presentation_boundary(callsign_info_widgets.hide):
                runtime.callsign_info.observe_callsign(
                    callsign_info_target.callsign,
                    pota_latitude=pota_latitude,
                    pota_longitude=pota_longitude,
                )
                callsign_info_state = runtime.callsign_info.state
                if callsign_info_state.response is not None:
                    callsign_presentation = build_callsign_info_presentation(
                        callsign_info_state.response,
                        friends=friends,
                        pota_latitude=callsign_info_state.target_latitude,
                        pota_longitude=callsign_info_state.target_longitude,
                        target_grid=callsign_info_target.grid,
                    )
                elif (
                    callsign_info_state.presentation_active
                    and callsign_info_state.callsign is not None
                ):
                    failure_status = callsign_info_failure_status(
                        callsign_info_state.failure,
                        network_status=connectivity.network,
                    )
                    callsign_presentation = build_local_callsign_info_presentation(
                        callsign_info_state.callsign,
                        friends=friends,
                        target_grid=callsign_info_target.grid,
                        service_status=failure_status or "LOOKING UP LOCATION",
                        service_status_error=failure_status is not None,
                    )
                else:
                    callsign_presentation = None

                callsign_map_snapshot = None
                if callsign_presentation is not None:
                    if (
                        runtime.callsign_map is not None
                        and callsign_presentation.target is not None
                    ):
                        runtime.callsign_map.set_zoom(callsign_presentation.map_zoom)
                        info_map_width, info_map_height = callsign_info_widgets.map_size
                        if info_map_width >= 64 and info_map_height >= 64:
                            runtime.callsign_map.request_viewport(
                                callsign_presentation.target,
                                width_px=info_map_width,
                                height_px=info_map_height,
                            )
                        callsign_map_snapshot = runtime.callsign_map.latest_state
                    callsign_info_widgets.show(
                        callsign_presentation,
                        callsign_map_snapshot,
                    )
                else:
                    callsign_info_widgets.hide()
        else:
            callsign_info_widgets.hide()

        voice_state = view.voice_state.upper()
        voice_engaged = voice_state in {
            "ACTIVE",
            "CAPTURING",
            "LISTENING",
            "RECORDING",
        }

        callsign_prompt_text.set("" if pending_callsign or voice_engaged else "CALLSIGN")
        callsign_text.set(pending_callsign)
        pending_friend_label.configure(text=friend_marker(pending_callsign, friends))
        callsign_label.configure(
            font=("DejaVu Sans", _callsign_font_size(pending_callsign), "bold")
        )
        voice_text.set("VOICE")
        voice_label.configure(fg=_indicator_color(view.voice_state))
        commit_text.set("COMMIT")
        commit_label.configure(fg=_indicator_color(view.commit_state))
        displayed_frequency = view.frequency
        displayed_band = view.band.replace(" ", "")
        if (
            context_navigation.state.selected is ContextId.FT8
            and runtime.ft8_band_control is not None
        ):
            displayed_frequency, displayed_band, acknowledged = present_ft8_band_tune(
                radio_state,
                runtime.ft8_band_control.status,
                acknowledged_ft8_tune[0],
                displayed_frequency,
                displayed_band,
            )
            acknowledged_ft8_tune[0] = acknowledged
        frequency_text.set(displayed_frequency)
        band_text.set(displayed_band)
        mode_text.set(view.mode)
        last_result = view.last_result if view.last_result != "—" else "—"
        last_result_text.set(f"Last Result: {last_result[:18]}")

        status_bar.update_statuses(
            build_status_strip_snapshot(
                radio_state,
                status_monitor.latest_state,
            )
        )
        ticker_message = build_status_bar_routine_message(
            view, control_health=control_source.snapshot.health if isinstance(control_source, RecoveringControlSource) else None,
        )
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
            (
                selected_context.selected is ContextId.DMR
                and dmr_panel_runtime is not None
            )
            or selected_context.selected is ContextId.ANTENNAS
        )

        ui_timing.checkpoint("presentation")
        context_decode_text.set("")
        if selected_context.selected in {ContextId.POTA, ContextId.DX}:
            health_frame.grid_remove()
            show_pota_context_body()
            panel_state = shared_spot_panel.state
            panel = build_shared_spot_viewport(panel_state, friends=friends)
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
                    pota_call_headers[card_index].configure(bg=card_background)
                    pota_friend_labels[card_index].configure(text=card.friend_marker, bg=card_background)
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
            context_title_label.configure(font=_CONTEXT_HEADER_FONT)
            browse_state = browse_controls.state
            browse_mode_text.set(browse_mode_label(radio_state.mode))
            browse_frequency_text.set(
                f"{radio_state.frequency.mhz:.6f} MHz"
                if radio_state.frequency is not None
                else "---.------ MHz"
            )
            browse_step_text.set(browse_state.step_label.upper())
            browse_advisory = us_extra_band_advisory(
                radio_state.frequency,
                radio_state.mode,
            )
            if browse_advisory.level is BandAdvisoryLevel.OK:
                browse_warning_label.grid_remove()
            else:
                browse_warning_text.set(browse_advisory.message or "")
                if browse_advisory.level is BandAdvisoryLevel.OUT_OF_BAND:
                    browse_warning_label.configure(
                        bg=_FAILURE,
                        fg=_BRIGHT,
                    )
                else:
                    browse_warning_label.configure(
                        bg=_WARNING,
                        fg=_HEALTH_DARK_TEXT,
                    )
                browse_warning_label.grid()
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
            log_widgets.update(log_panel.latest_state, friends=friends)
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
                        friends=friends,
                    )
                )
        elif selected_context.selected is ContextId.MESHCORE_OHGO:
            show_standard_context_body()
            health_frame.grid_remove()
            context_title_text.set("MESHCORE & OHGO")
            context_title_label.configure(font=("DejaVu Sans", 34, "bold"))
            context_body_label.configure(
                font=("DejaVu Sans", 21, "bold"), wraplength=720,
            )
            context_body_text.set(
                present_meshcore_ohgo(ohgo_panel_worker.state)
            )
        elif selected_context.selected is ContextId.FT8:
            health_frame.grid_remove()
            context_title_text.set("FT8")
            context_title_label.configure(font=_CONTEXT_HEADER_FONT)
            if runtime.ft8_panel is None:
                show_standard_context_body()
                context_body_label.configure(
                    font=("DejaVu Sans", 26, "bold"),
                    wraplength=620,
                )
                context_body_text.set(
                    "Native FT8 is disabled.\n\n"
                    "Enable ft8.enabled for receive-only CQ browsing.\n"
                    "FT8 transmit remains independently gated."
                )
            else:
                ft8_snapshot = runtime.ft8_panel.snapshot()
                receive_state = runtime.latest_ft8_receive_state
                receive_status = (
                    "UNKNOWN"
                    if receive_state is None
                    else receive_state.status.value.upper()
                )
                transmitting = bool(
                    getattr(runtime.ft8_hardware_transmit, "transmitting", False)
                )
                if transmitting:
                    activity_text = "TX RUNNING"
                    activity_color = "#ffae66"
                elif receive_state is not None and receive_state.decoding:
                    activity_text = "DECODING"
                    activity_color = "#66ccff"
                elif receive_status == "RUNNING":
                    activity_text = "RX RUNNING"
                    activity_color = _BRIGHT
                else:
                    activity_text = f"RX {receive_status}"
                    activity_color = _BRIGHT
                context_title_text.set(f"FT8  •  {activity_text}")
                context_title_label.configure(fg=activity_color)
                context_decode_text.set(
                    _context_decode_header_text(
                        selected_context.selected,
                        None
                        if receive_state is None or receive_state.last_decoder is None
                        else receive_state.last_decoder.parsed_decode_count
                    )
                )

                if ft8_snapshot.mode is FT8PanelMode.BROWSE:
                    show_ft8_context_body()
                    selected_callsign = runtime.ft8_panel.selected_callsign
                    attempt_states = {
                        activity.callsign: state
                        for activity in ft8_snapshot.cq_activity
                        if (
                            state := runtime.ft8_attempt_visual_state(
                                activity.callsign
                            )
                        )
                        is not None
                    }
                    viewport = build_ft8_browser_viewport(
                        ft8_snapshot.cq_activity,
                        current_period=ft8_snapshot.receive_period,
                        selected_callsign=selected_callsign,
                        visible_rows=ft8_widgets.visible_rows,
                        attempt_states=attempt_states,
                        friends=friends,
                        rankings=(
                            {} if runtime.ft8_browser_ranking is None
                            else runtime.ft8_browser_ranking.latest_rankings
                        ),
                        pending_ranking_callsigns=(
                            frozenset() if runtime.ft8_browser_ranking is None
                            else runtime.ft8_browser_ranking.pending_callsigns
                        ),
                    )
                    selected_activity = next(
                        (row for row in ft8_snapshot.cq_activity if row.callsign == selected_callsign),
                        None,
                    )
                    current_grid = (
                        view.grid
                        if view.grid != "—"
                        else str(config.operator.home_grid)
                    )
                    ft8_widgets.update(
                        viewport,
                        transmit_enabled=ft8_snapshot.authorization_enabled,
                        distance_text=(
                            None
                            if selected_activity is None
                            else format_maidenhead_distance(
                                current_grid,
                                selected_activity.grid,
                            )
                        ),
                        diagnostic_text=format_ft8_receive_diagnostic(
                            receive_state
                        ),
                        incoming_call=present_ft8_incoming_call(
                            ft8_snapshot.incoming_call
                        ),
                    )
                else:
                    show_standard_context_body()
                    context_body_label.configure(
                        font=("DejaVu Sans", 29, "bold"),
                        wraplength=640,
                    )
                    lines = [
                        f"QSO: {ft8_snapshot.qso_state.value.upper()}",
                    ]
                    if ft8_snapshot.mode is FT8PanelMode.ACTIVE:
                        context = ft8_snapshot.active_context
                        lines.append("")
                        lines.append("ACTIVE FT8 QSO")
                        if context is not None:
                            lines.append(f"CALL  {context.remote_callsign}")
                            lines.append(
                                f"GRID  {context.local_grid or '------'}"
                            )
                            lines.append(
                                f"FREQ  {context.radio_frequency_hz / 1_000_000:.6f} MHz"
                            )
                            lines.append(
                                format_maidenhead_distance(
                                    context.local_grid,
                                    context.remote_grid,
                                )
                            )
                        lines.append(
                            "ATTEMPT "
                            f"{ft8_snapshot.attempt_count}/{ft8_snapshot.attempts_per_state}"
                        )
                        lines.append("")
                        lines.append("CONTEXT BUTTON 3 — ABORT QSO NOW")
                        lines.append("BACK / X — ABORT QSO")
                    else:
                        result = ft8_snapshot.result
                        lines.append("")
                        lines.append(
                            f"RESULT  {ft8_snapshot.qso_state.value.upper()}"
                        )
                        if result is not None and result.terminal_reason:
                            lines.append(result.terminal_reason)
                        lines.append("")
                        lines.append("PRESS ENCODER — RETURN TO CQ BROWSER")
                        lines.append("CONTEXT BUTTON 3 — RETURN TO CQ BROWSER")
                    context_body_text.set("\n".join(lines))
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
        elif selected_context.selected is ContextId.ANTENNAS:
            health_frame.grid_remove()
            show_antenna_context_body()
            context_title_text.set(selected_context.definition.title)
            context_title_label.configure(font=("DejaVu Sans", 31, "bold"))
            if antenna_widgets is not None and antenna_panel is not None:
                antenna_widgets.update(antenna_panel.state)
        else:
            show_standard_context_body()
            health_frame.grid_remove()
            context_title_text.set(selected_context.definition.title)
            context_title_label.configure(font=("DejaVu Sans", 48, "bold"))
            context_body_label.configure(font=("DejaVu Sans", 22), wraplength=560)
            context_body_text.set(selected_context.definition.placeholder)

        ui_timing.end_refresh(refresh_start)
        root.after(_REFRESH_MS, refresh)

    close_started = Event()
    close_finished = Event()
    sigterm_requested = Event()
    close_errors: list[str] = []

    def finish_close() -> None:
        if not close_finished.is_set():
            root.after(50, finish_close)
            return
        for message in close_errors:
            print(f"Rolling Thunder shutdown error: {message}")
        root.destroy()

    def close_worker() -> None:
        def close_controls() -> None:
            control_close_error = close_control_source(control_source)
            if control_close_error is not None:
                raise RuntimeError(control_close_error)

        def stop_callsign_capture() -> None:
            if live_capture is not None and not live_capture.shutdown(timeout_s=3.0):
                raise RuntimeError("callsign audio capture did not stop cleanly")

        def stop_tron_microphone() -> None:
            if tron_microphone is not None and not tron_microphone.shutdown(timeout_s=3.0):
                raise RuntimeError("Tron audio worker did not stop cleanly")

        def stop_dmr() -> None:
            if dmr_panel_runtime is not None:
                dmr_panel_runtime.stop()

        def close_antenna() -> None:
            if antenna_panel is not None:
                antenna_panel.close()

        def drain_preferences() -> None:
            if not preference_service.flush(3.0):
                raise RuntimeError("queued operator preferences did not drain")

        try:
            _run_cleanup_steps(
                (
                    ("physical controls", close_controls),
                    ("callsign audio", stop_callsign_capture),
                    ("Tron audio", stop_tron_microphone),
                    ("OHGO panel", ohgo_panel_worker.stop),
                    ("DMR", stop_dmr),
                    ("antenna reference", close_antenna),
                    ("log panel", log_panel.stop),
                    ("status monitor", status_monitor.stop),
                    ("operator preferences", drain_preferences),
                    ("power worker", power_confirmation.stop),
                    ("application runtime", runtime.stop),
                ),
                close_errors,
            )
        finally:
            close_finished.set()

    def close() -> None:
        if close_started.is_set():
            return
        close_started.set()
        Thread(target=close_worker, daemon=True, name="rt-orderly-close").start()
        finish_close()

    previous_sigterm_handler = signal.signal(
        signal.SIGTERM,
        _sigterm_close_handler(sigterm_requested),
    )

    root.bind("<Escape>", lambda _event: close())
    root.bind("<F12>", lambda _event: toggle_tron_listening())
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
        if power_confirmation.state.pending or close_started.is_set():
            return
        if not context_navigation.select_shortcut(event.char):
            return
        active_panel_commands.activate_context(
            context_navigation.state.selected
        )

    for definition in context_navigation.definitions:
        root.bind(definition.shortcut, select_context_shortcut)
    root.protocol("WM_DELETE_WINDOW", close)
    refresh()
    try:
        root.mainloop()
    finally:
        signal.signal(signal.SIGTERM, previous_sigterm_handler)
    return 0


def main() -> int:
    """Console-script wrapper for the full-screen dashboard."""
    return run_dashboard()


if __name__ == "__main__":
    raise SystemExit(main())
