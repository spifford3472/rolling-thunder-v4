"""Application composition root for the first persistent Pi dashboard."""

import os
from collections.abc import Callable
from concurrent.futures import Executor
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from time import monotonic
from uuid import uuid4

from rolling_thunder.application_secrets import ApplicationSecrets
from rolling_thunder.callsign_info_client import HttpCallsignInfoClient
from rolling_thunder.callsign_info_service import CallsignInfoLookupService
from rolling_thunder.census_state_outline import CensusStateOutlineProvider
from rolling_thunder.chrony_clock import ChronyHelperClockSetter
from rolling_thunder.clock_sync import (
    ClockSynchronizationService,
    ClockSyncState,
    SystemClockSetter,
)
from rolling_thunder.config import ApplicationConfig, HardwareAdapterMode
from rolling_thunder.contact_logging import ContactLoggingService
from rolling_thunder.contact_qrz_enrichment import ContactQrzEnrichmentService
from rolling_thunder.contact_repository import ContactRepository
from rolling_thunder.contact_retry import ContactRetryRepository
from rolling_thunder.contact_sync import ContactSyncService
from rolling_thunder.domain import RadioState
from rolling_thunder.forge_radar_client import HttpForgeRadarClient
from rolling_thunder.ft8.activity import FT8CQActivityManager
from rolling_thunder.ft8.audio import AlsaArecordFT8AudioInput, FT8AudioInput
from rolling_thunder.ft8.audio_output import AlsaAplayFT8AudioOutput, FT8AudioOutput
from rolling_thunder.ft8.authorization import FT8QsoAuthorizationService
from rolling_thunder.ft8.band_control import FT8BandController
from rolling_thunder.ft8.coordinator import FT8QsoResult
from rolling_thunder.ft8.decoder import FT8Decoder, Ft8LibDecoder
from rolling_thunder.ft8.domain import FT8CQActivity, FT8QsoContext, FT8QsoState
from rolling_thunder.ft8.encoder import FT8Encoder, Ft8LibEncoder
from rolling_thunder.ft8.hardware_transmit import (
    BoundedFT8HardwareTransmitExecutor,
    FT8QsoHardwareTransmitExecutor,
)
from rolling_thunder.ft8.logging import FT8QsoLoggingService
from rolling_thunder.ft8.operator_qso import FT8OperatorQsoService
from rolling_thunder.ft8.panel import FT8PanelController
from rolling_thunder.ft8.performance_outbox import FT8PerformanceOutboxRepository
from rolling_thunder.ft8.performance_recording import (
    FT8PerformanceRecorder,
    build_ft8_attempt_seed,
)
from rolling_thunder.ft8.performance_sync import FT8PerformanceSyncService
from rolling_thunder.ft8.radio_preparation import FT8RadioPreparationService
from rolling_thunder.ft8.receive import FT8ReceiveService, FT8ReceiveState
from rolling_thunder.ft8.session import (
    FT8QsoSessionAuthorization,
    HardwareDigitalTransmitSession,
)
from rolling_thunder.ft8.start_control import FT8QsoStartController, FT8QsoStartStatus
from rolling_thunder.ft8.timing import FT8Clock, SystemFT8Clock
from rolling_thunder.ft8.worked_today import FT8WorkedTodayService
from rolling_thunder.ft891_radio import Ft891Radio
from rolling_thunder.gps import GPSReceiver, GPSState
from rolling_thunder.gps_polling import GPSPollingService
from rolling_thunder.home_platform import HomePlatformClient
from rolling_thunder.home_platform_health import HomePlatformHealthService
from rolling_thunder.http_home_platform import HttpHomePlatformClient, HttpTransport
from rolling_thunder.live_map_service import LiveMapService, LiveMapSnapshot
from rolling_thunder.live_radar_service import LiveRadarOverlayService, LiveRadarSnapshot
from rolling_thunder.map_solar import MapSolarStyleService
from rolling_thunder.map_sources import (
    InstalledMapRegistry,
    MapPackageStyle,
    MapTileResolver,
)
from rolling_thunder.map_tiles import MapTileCache, MapTileClient
from rolling_thunder.map_zoom import (
    MapZoomSettingsController,
    effective_map_zoom_bounds,
    resolve_initial_map_zoom,
)
from rolling_thunder.mock_gps import MockGPSReceiver
from rolling_thunder.mock_radio import MockRadio
from rolling_thunder.network_keepalive import (
    NetworkKeepaliveService,
    NetworkKeepaliveTransport,
)
from rolling_thunder.open_meteo import OpenMeteoParkWeatherProvider
from rolling_thunder.operator_preferences import (
    OperatorPreferenceRepository,
    OperatorPreferenceService,
)
from rolling_thunder.pi_forge_location_publisher import (
    PiForgeLocationPublisherState,
    PiForgeLocationPublishingService,
)
from rolling_thunder.pi_forge_runtime import (
    build_pi_forge_location_publishing,
    build_pi_forge_spot_polling,
    build_pi_forge_weather_alert_polling,
    build_pi_forge_weather_polling,
)
from rolling_thunder.pi_forge_spot_polling import ExecutorFactory, PiForgeSpotPollingService
from rolling_thunder.pi_forge_spot_service import PiForgeSpotState
from rolling_thunder.pi_forge_weather_alert_polling import (
    PiForgeWeatherAlertNotificationBatch,
    PiForgeWeatherAlertPollingService,
    WeatherAlertExecutorFactory,
)
from rolling_thunder.pi_forge_weather_alert_service import (
    PiForgeWeatherAlertState,
)
from rolling_thunder.pi_forge_weather_polling import (
    PiForgeWeatherPollingService,
    WeatherExecutorFactory,
)
from rolling_thunder.pi_forge_weather_service import PiForgeWeatherState
from rolling_thunder.pota_enrichment import PotaEnrichmentService
from rolling_thunder.pota_map_markers import PotaMapMarkerService, PotaMapMarkerSnapshot
from rolling_thunder.pota_receive_tune_executor import PotaReceiveTuneExecutor
from rolling_thunder.pota_runtime import build_pota_spot_polling
from rolling_thunder.pota_spot_polling import PotaSpotPollingService
from rolling_thunder.pota_spot_service import PotaSpotServiceState
from rolling_thunder.pyserial_cat_transport import PySerialCatTransport
from rolling_thunder.qrz_profile_image import QrzProfileImageProvider
from rolling_thunder.qrz_xml import QrzXmlCallsignNameProvider
from rolling_thunder.radio import Radio
from rolling_thunder.radio_band import RadioBandResolutionError, resolve_radio_band
from rolling_thunder.radio_polling import PollScheduler, RadioPollingService
from rolling_thunder.receive_tuning import ReceiveTuningService
from rolling_thunder.serial_gps import SerialGPSReceiver
from rolling_thunder.status_messages import StatusMessageService
from rolling_thunder.threading_scheduler import ThreadingPollScheduler

GPSFactory = Callable[..., GPSReceiver]
RadioFactory = Callable[..., Radio]
_CLOCK_SYNC_ENV = "ROLLING_THUNDER_GPS_CLOCK_SYNC"


def _clock_sync_enabled_from_environment() -> bool:
    """Enable the production clock-sync path only through an explicit runtime flag."""
    return os.environ.get(_CLOCK_SYNC_ENV, "").strip() == "1"


def _build_serial_radio(
    device: Path,
    *,
    baud_rate: int,
    timeout_s: float,
) -> Radio:
    """Build the physical FT-891 adapter with configured CAT settings."""
    return Ft891Radio(
        PySerialCatTransport(
            device,
            baud_rate=baud_rate,
            timeout_s=timeout_s,
        )
    )


@dataclass
class ApplicationRuntime:
    """Own composed radio, GPS, logging, polling, clock, and enrichment lifecycle."""

    radio: Radio
    polling: RadioPollingService
    contact_logging: ContactLoggingService
    gps: GPSReceiver | None = None
    gps_polling: GPSPollingService | None = None
    clock_sync: ClockSynchronizationService | None = None
    live_map: LiveMapService | None = None
    callsign_map: LiveMapService | None = None
    pota_map_markers: PotaMapMarkerService | None = None
    live_radar: LiveRadarOverlayService | None = None
    map_zoom_settings: MapZoomSettingsController | None = None
    map_solar: MapSolarStyleService | None = None
    operator_preferences: OperatorPreferenceService | None = None
    callsign_info: CallsignInfoLookupService | None = None
    home_platform_client: HomePlatformClient | None = None
    home_platform_health: HomePlatformHealthService | None = None
    contact_qrz_enrichment: ContactQrzEnrichmentService | None = None
    contact_sync: ContactSyncService | None = None
    network_keepalive: NetworkKeepaliveService | None = None
    pi_forge_spot_polling: PiForgeSpotPollingService | None = None
    pi_forge_weather_polling: PiForgeWeatherPollingService | None = None
    pi_forge_weather_alert_polling: (
        PiForgeWeatherAlertPollingService | None
    ) = None
    pi_forge_location_publishing: PiForgeLocationPublishingService | None = None
    pota_spot_polling: PotaSpotPollingService | None = None
    pota_enrichment: PotaEnrichmentService = field(default_factory=PotaEnrichmentService)
    status_messages: StatusMessageService = field(default_factory=StatusMessageService)
    ft8_receive: FT8ReceiveService | None = None
    ft8_band_control: FT8BandController | None = None
    ft8_authorization: FT8QsoAuthorizationService | None = None
    ft8_qso: FT8OperatorQsoService | None = None
    ft8_qso_start: FT8QsoStartController | None = None
    ft8_logging: FT8QsoLoggingService | None = None
    ft8_worked_today: FT8WorkedTodayService | None = None
    ft8_performance_recorder: FT8PerformanceRecorder | None = None
    ft8_performance_sync: FT8PerformanceSyncService | None = None
    ft8_panel: FT8PanelController | None = None
    ft8_hardware_transmit: FT8QsoHardwareTransmitExecutor | None = None
    _started: bool = False

    @classmethod
    def from_config(
        cls,
        config: ApplicationConfig,
        *,
        secrets: ApplicationSecrets | None = None,
        scheduler: PollScheduler | None = None,
        gps_scheduler: PollScheduler | None = None,
        clock_sync_scheduler: PollScheduler | None = None,
        home_platform_scheduler: PollScheduler | None = None,
        contact_qrz_enrichment_scheduler: PollScheduler | None = None,
        contact_sync_scheduler: PollScheduler | None = None,
        ft8_performance_sync_scheduler: PollScheduler | None = None,
        network_keepalive_scheduler: PollScheduler | None = None,
        forge_scheduler: PollScheduler | None = None,
        forge_weather_scheduler: PollScheduler | None = None,
        forge_weather_alert_scheduler: PollScheduler | None = None,
        forge_location_scheduler: PollScheduler | None = None,
        pota_scheduler: PollScheduler | None = None,
        map_solar_scheduler: PollScheduler | None = None,
        interval_s: float = 1.0,
        gps_interval_s: float = 1.0,
        radio_factory: RadioFactory = _build_serial_radio,
        gps_factory: GPSFactory = SerialGPSReceiver,
        clock_sync_setter: SystemClockSetter | None = None,
        clock_sync_enabled: bool | None = None,
        home_platform_transport: HttpTransport | None = None,
        network_keepalive_transport: NetworkKeepaliveTransport | None = None,
        forge_transport: HttpTransport | None = None,
        callsign_info_transport: HttpTransport | None = None,
        forge_location_transport: HttpTransport | None = None,
        pota_transport: HttpTransport | None = None,
        qrz_transport: HttpTransport | None = None,
        weather_transport: HttpTransport | None = None,
        image_transport: HttpTransport | None = None,
        state_map_transport: HttpTransport | None = None,
        map_transport: HttpTransport | None = None,
        forge_executor_factory: ExecutorFactory | None = None,
        forge_weather_executor_factory: WeatherExecutorFactory | None = None,
        forge_weather_alert_executor_factory: (
            WeatherAlertExecutorFactory | None
        ) = None,
        forge_location_executor_factory: ExecutorFactory | None = None,
        enrichment_executor: Executor | None = None,
        map_executor: Executor | None = None,
        radar_executor: Executor | None = None,
        pota_map_executor: Executor | None = None,
        callsign_info_executor: Executor | None = None,
        callsign_map_executor: Executor | None = None,
        ft8_audio_input: FT8AudioInput | None = None,
        ft8_decoder: FT8Decoder | None = None,
        ft8_audio_output: FT8AudioOutput | None = None,
        ft8_encoder: FT8Encoder | None = None,
        ft8_clock: FT8Clock | None = None,
        ft8_hardware_executor: FT8QsoHardwareTransmitExecutor | None = None,
    ) -> "ApplicationRuntime":
        """Build configured hardware, persistence, and application services."""
        radio: Radio
        if config.hardware.effective_radio_mode is HardwareAdapterMode.MOCK:
            radio = MockRadio()
        else:
            radio_device = config.hardware.radio_device
            if radio_device is None:
                raise ValueError("A radio device is required when radio mode is real.")
            radio = radio_factory(
                radio_device,
                baud_rate=config.hardware.radio_baud_rate,
                timeout_s=config.hardware.radio_timeout_s,
            )

        gps: GPSReceiver
        if config.hardware.effective_gps_mode is HardwareAdapterMode.MOCK:
            gps = MockGPSReceiver()
        else:
            gps_device = config.hardware.gps_device
            if gps_device is None:
                raise ValueError("A GPS device is required when GPS mode is real.")
            gps = gps_factory(
                gps_device,
                baud_rate=config.hardware.gps_baud_rate,
                timeout_s=config.hardware.gps_timeout_s,
            )

        polling_scheduler = scheduler or ThreadingPollScheduler()
        gps_polling_scheduler = gps_scheduler or ThreadingPollScheduler()
        gps_polling = GPSPollingService(
            gps,
            gps_polling_scheduler,
            interval_s=gps_interval_s,
        )

        enable_clock_sync = (
            _clock_sync_enabled_from_environment()
            if clock_sync_enabled is None
            else clock_sync_enabled
        )
        clock_sync: ClockSynchronizationService | None = None
        if enable_clock_sync:
            if config.hardware.effective_gps_mode is not HardwareAdapterMode.REAL:
                raise ValueError("GPS clock synchronization requires real GPS hardware mode.")
            clock_sync = ClockSynchronizationService(
                lambda: gps_polling.latest_state,
                clock_sync_setter or ChronyHelperClockSetter(),
                clock_sync_scheduler or ThreadingPollScheduler(),
                monotonic_clock=monotonic,
            )

        repository = ContactRepository(config.storage.database_path)
        preference_repository = OperatorPreferenceRepository(config.storage.database_path)
        operator_preferences = OperatorPreferenceService(preference_repository)

        home_platform_client: HomePlatformClient | None = None
        home_platform_health: HomePlatformHealthService | None = None
        contact_sync: ContactSyncService | None = None
        platform_config = config.home_platform
        if platform_config.enabled:
            base_url = platform_config.base_url
            if base_url is None:
                raise ValueError("Home platform base URL is required when enabled.")
            home_platform_client = HttpHomePlatformClient(
                str(base_url),
                timeout_s=platform_config.request_timeout_s,
                transport=home_platform_transport,
            )
            home_platform_health = HomePlatformHealthService(
                home_platform_client,
                home_platform_scheduler or ThreadingPollScheduler(),
                interval_s=platform_config.health_poll_interval_s,
            )
            contact_sync = ContactSyncService(
                repository,
                home_platform_client,
                contact_sync_scheduler or ThreadingPollScheduler(),
                interval_s=platform_config.contact_sync_interval_s,
                batch_size=platform_config.contact_sync_batch_size,
                retry_store=ContactRetryRepository(config.storage.database_path),
            )

        network_keepalive: NetworkKeepaliveService | None = None
        keepalive_config = config.network_keepalive
        if keepalive_config.enabled:
            target_url = keepalive_config.target_url
            if target_url is None:
                raise ValueError("Network keepalive target URL is required when enabled.")
            network_keepalive = NetworkKeepaliveService(
                str(target_url),
                network_keepalive_scheduler or ThreadingPollScheduler(),
                interval_s=keepalive_config.interval_s,
                timeout_s=keepalive_config.timeout_s,
                transport=network_keepalive_transport,
            )

        pi_forge_spot_polling = build_pi_forge_spot_polling(
            config.forge,
            database_path=config.storage.database_path,
            scheduler=forge_scheduler,
            transport=forge_transport,
            executor_factory=forge_executor_factory,
        )
        pi_forge_weather_polling = build_pi_forge_weather_polling(
            config.forge,
            database_path=config.storage.database_path,
            scheduler=forge_weather_scheduler,
            transport=forge_transport,
            executor_factory=forge_weather_executor_factory,
        )

        pi_forge_weather_alert_polling = (
            build_pi_forge_weather_alert_polling(
                config.forge,
                lambda: gps_polling.latest_state,
                database_path=config.storage.database_path,
                scheduler=forge_weather_alert_scheduler,
                transport=forge_transport,
                executor_factory=(
                    forge_weather_alert_executor_factory
                ),
            )
        )

        callsign_info: CallsignInfoLookupService | None = None
        callsign_info_config = config.forge.callsign_info
        if callsign_info_config.enabled:
            callsign_info_url = callsign_info_config.api_url
            if callsign_info_url is None:
                raise ValueError(
                    "Callsign-info API URL is required when callsign-info is enabled."
                )
            callsign_info = CallsignInfoLookupService(
                HttpCallsignInfoClient(
                    str(callsign_info_url),
                    timeout_s=callsign_info_config.request_timeout_s,
                    max_response_bytes=callsign_info_config.max_response_bytes,
                    transport=callsign_info_transport or forge_transport,
                ),
                overlay_timeout_s=callsign_info_config.overlay_timeout_s,
                executor=callsign_info_executor,
            )

        pi_forge_location_publishing: PiForgeLocationPublishingService | None = None
        if (
            config.forge.enabled
            and config.hardware.effective_gps_mode is HardwareAdapterMode.REAL
        ):
            pi_forge_location_publishing = build_pi_forge_location_publishing(
                config.forge,
                lambda: gps_polling.latest_state,
                scheduler=forge_location_scheduler,
                transport=forge_location_transport or forge_transport,
                executor_factory=forge_location_executor_factory,
            )

        pota_spot_polling: PotaSpotPollingService | None = None
        if not config.forge.enabled:
            pota_spot_polling = build_pota_spot_polling(
                config.pota_spots,
                pota_scheduler or ThreadingPollScheduler(),
                database_path=config.storage.database_path,
                mock_mode=(
                    config.hardware.effective_radio_mode
                    is HardwareAdapterMode.MOCK
                ),
                transport=pota_transport,
            )

        resolved_secrets = secrets or ApplicationSecrets()
        qrz_provider = None
        qrz_timeout_s = config.pota_spots.request_timeout_s
        if resolved_secrets.qrz is not None:
            qrz_provider = QrzXmlCallsignNameProvider(
                resolved_secrets.qrz,
                timeout_s=qrz_timeout_s,
                transport=qrz_transport,
            )

        contact_qrz_enrichment = None
        if qrz_provider is not None:
            contact_qrz_enrichment = ContactQrzEnrichmentService(
                repository,
                qrz_provider,
                contact_qrz_enrichment_scheduler or ThreadingPollScheduler(),
            )

        qrz_photo_provider = None
        weather_provider = None
        state_outline_provider = None
        if config.pota_spots.enabled:
            timeout_s = config.pota_spots.request_timeout_s
            if qrz_provider is not None:
                qrz_photo_provider = QrzProfileImageProvider(
                    timeout_s=timeout_s,
                    transport=image_transport,
                )
            weather_provider = OpenMeteoParkWeatherProvider(
                timeout_s=timeout_s,
                transport=weather_transport,
            )
            state_outline_provider = CensusStateOutlineProvider(
                timeout_s=timeout_s,
                transport=state_map_transport,
            )

        pota_enrichment = PotaEnrichmentService(
            callsign_provider=qrz_provider,
            callsign_photo_provider=qrz_photo_provider,
            weather_provider=weather_provider,
            state_outline_provider=state_outline_provider,
            executor=enrichment_executor,
        )

        contact_logging = ContactLoggingService(
            repository,
            qrz_fallback_available=qrz_provider is not None,
        )
        ft8_worked_today = (
            FT8WorkedTodayService(repository) if config.ft8.enabled else None
        )
        ft8_logging = FT8QsoLoggingService(
            contact_logging,
            completed_contact_handler=(
                None
                if ft8_worked_today is None
                else ft8_worked_today.record_completed
            ),
        )
        ft8_performance_recorder = (
            FT8PerformanceRecorder(
                FT8PerformanceOutboxRepository(config.storage.database_path)
            )
            if config.ft8.enabled
            else None
        )
        ft8_performance_sync = None
        if (
            config.ft8.enabled
            and home_platform_client is not None
            and ft8_performance_recorder is not None
        ):
            ft8_performance_sync = FT8PerformanceSyncService(
                ft8_performance_recorder._repository,
                home_platform_client,  # type: ignore[arg-type]
                ft8_performance_sync_scheduler or ThreadingPollScheduler(),
                interval_s=platform_config.contact_sync_interval_s,
                batch_size=platform_config.contact_sync_batch_size,
            )

        ft8_receive: FT8ReceiveService | None = None
        if config.ft8.enabled:
            decoder_executable = config.ft8.receive.decoder_executable
            if decoder_executable is None:
                raise ValueError(
                    "FT8 decoder executable is required when FT8 is enabled."
                )
            resolved_audio_input = ft8_audio_input or AlsaArecordFT8AudioInput(
                config.ft8.receive.audio_device
            )
            resolved_decoder = ft8_decoder or Ft8LibDecoder(
                str(decoder_executable),
                timeout_s=config.ft8.receive.decoder_timeout_s,
            )
            ft8_receive = FT8ReceiveService(
                resolved_audio_input,
                resolved_decoder,
                FT8CQActivityManager(),
                reconnect_delay_s=config.ft8.receive.reconnect_delay_s,
            )

        ft8_band_control = (
            FT8BandController(ReceiveTuningService(radio), radio.get_state)
            if config.ft8.enabled
            else None
        )

        ft8_authorization: FT8QsoAuthorizationService | None = None
        ft8_qso: FT8OperatorQsoService | None = None
        resolved_ft8_executor: FT8QsoHardwareTransmitExecutor | None = None
        resolved_ft8_clock: FT8Clock | None = None
        if config.ft8.enabled:
            resolved_ft8_clock = ft8_clock or SystemFT8Clock()
            ft8_authorization = FT8QsoAuthorizationService(
                local_callsign=config.operator.callsign,
                home_grid=config.operator.home_grid,
                clock=resolved_ft8_clock,
            )
        if config.ft8.transmit.enabled:
            if ft8_receive is None or resolved_ft8_clock is None:
                raise RuntimeError("FT8 QSO execution requires enabled FT8 receive/timing")
            active_ft8_clock = resolved_ft8_clock
            encoder_executable = config.ft8.transmit.encoder_executable
            if encoder_executable is None:
                raise ValueError(
                    "FT8 encoder executable is required when FT8 transmit is enabled."
                )
            resolved_ft8_encoder = ft8_encoder or Ft8LibEncoder(str(encoder_executable))
            if ft8_hardware_executor is not None:
                resolved_ft8_executor = ft8_hardware_executor
            else:
                if not isinstance(radio, Ft891Radio):
                    raise ValueError(
                        "FT8 transmit requires the real FT-891 adapter "
                        "or an injected test executor."
                    )
                resolved_ft8_audio_output = (
                    ft8_audio_output
                    or AlsaAplayFT8AudioOutput(config.ft8.transmit.audio_device)
                )
                resolved_ft8_executor = BoundedFT8HardwareTransmitExecutor(
                    radio,
                    resolved_ft8_audio_output,
                )

            def build_ft8_session(
                context: FT8QsoContext,
            ) -> HardwareDigitalTransmitSession:
                assert resolved_ft8_executor is not None
                return HardwareDigitalTransmitSession(
                    FT8QsoSessionAuthorization(uuid4().hex, context),
                    resolved_ft8_encoder,
                    resolved_ft8_executor,
                    active_ft8_clock,
                    release_margin_s=config.ft8.transmit.release_margin_s,
                )

            def handle_ft8_terminal_result(result: FT8QsoResult) -> object:
                contact = ft8_logging.handle_terminal_result(result)
                if ft8_performance_recorder is not None:
                    ft8_performance_recorder.record_qso_result(result)
                return contact

            ft8_qso = FT8OperatorQsoService(
                ft8_receive,
                build_ft8_session,
                active_ft8_clock,
                attempts_per_state=config.ft8.qso.attempts_per_state,
                terminal_result_handler=handle_ft8_terminal_result,
            )

        live_map: LiveMapService | None = None
        callsign_map: LiveMapService | None = None
        live_radar: LiveRadarOverlayService | None = None
        map_zoom_settings: MapZoomSettingsController | None = None
        map_solar: MapSolarStyleService | None = None
        map_config = config.map
        if map_config.enabled:
            map_cache = MapTileCache(
                map_config.cache_directory,
                retention=timedelta(days=map_config.cache_retention_days),
                maximum_tiles=map_config.maximum_cached_tiles,
            )
            map_client = MapTileClient(
                map_config.tile_url_template,
                timeout_s=map_config.request_timeout_s,
                transport=map_transport,
            )
            installed_registry = InstalledMapRegistry.load(map_config.installed_packages)
            zoom_bounds = effective_map_zoom_bounds(
                installed_registry.packages,
                style=map_config.style,
            )
            effective_zoom = resolve_initial_map_zoom(
                preference_repository.read_map_zoom(),
                map_config.zoom,
                zoom_bounds,
            )
            map_resolver = MapTileResolver(
                installed_registry,
                map_cache,
                map_client,
                style=map_config.style,
                online_attribution=map_config.online_attribution,
            )
            live_map = LiveMapService(
                map_resolver,
                zoom=effective_zoom,
                executor=map_executor,
            )
            if config.forge.callsign_info.enabled:
                # Contact maps can be anywhere in the world. Keep their tile
                # source/cache isolated from corridor MBTiles so a viewport
                # cannot splice night installed tiles with light online tiles.
                callsign_map_cache = MapTileCache(
                    map_config.cache_directory / "callsign-info",
                    retention=timedelta(days=map_config.cache_retention_days),
                    maximum_tiles=map_config.maximum_cached_tiles,
                )
                callsign_map_client = MapTileClient(
                    map_config.tile_url_template,
                    timeout_s=map_config.request_timeout_s,
                    transport=map_transport,
                )
                callsign_map_registry = InstalledMapRegistry.load(())
                callsign_map_resolver = MapTileResolver(
                    callsign_map_registry,
                    callsign_map_cache,
                    callsign_map_client,
                    style=MapPackageStyle.DAY,
                    online_attribution=map_config.online_attribution,
                )
                callsign_map = LiveMapService(
                    callsign_map_resolver,
                    zoom=6,
                    executor=callsign_map_executor,
                )
            map_zoom_settings = MapZoomSettingsController(
                live_map,
                zoom_bounds,
                operator_preferences,
            )
            map_solar = MapSolarStyleService(
                live_map,
                map_solar_scheduler or ThreadingPollScheduler(),
                stale_after=timedelta(seconds=map_config.gps_stale_after_s),
            )
            gps_polling.add_listener(map_solar.observe_gps_state)

        pota_map_markers: PotaMapMarkerService | None = None
        if map_config.enabled and config.pota_map.enabled:
            pota_map_markers = PotaMapMarkerService(
                config.pota_map.catalog_path,
                executor=pota_map_executor,
            )

        if config.radar.enabled:
            forge_api_url = config.forge.api_url
            if forge_api_url is None:
                raise ValueError("Forge API URL is required when radar is enabled.")
            radar_client = HttpForgeRadarClient(
                str(forge_api_url),
                timeout_s=config.forge.request_timeout_s,
                transport=forge_transport,
            )
            live_radar = LiveRadarOverlayService(
                radar_client,
                manifest_refresh_interval_s=config.radar.manifest_refresh_interval_s,
                stale_after_s=config.radar.stale_after_s,
                hide_after_s=config.radar.hide_after_s,
                opacity=config.radar.opacity,
                executor=radar_executor,
            )

        runtime = cls(
            radio=radio,
            polling=RadioPollingService(
                radio,
                polling_scheduler,
                interval_s=interval_s,
            ),
            contact_logging=contact_logging,
            gps=gps,
            gps_polling=gps_polling,
            clock_sync=clock_sync,
            live_map=live_map,
            callsign_map=callsign_map,
            pota_map_markers=pota_map_markers,
            live_radar=live_radar,
            map_zoom_settings=map_zoom_settings,
            map_solar=map_solar,
            operator_preferences=operator_preferences,
            callsign_info=callsign_info,
            home_platform_client=home_platform_client,
            home_platform_health=home_platform_health,
            contact_qrz_enrichment=contact_qrz_enrichment,
            contact_sync=contact_sync,
            network_keepalive=network_keepalive,
            pi_forge_spot_polling=pi_forge_spot_polling,
            pi_forge_weather_polling=pi_forge_weather_polling,
            pi_forge_weather_alert_polling=(
                pi_forge_weather_alert_polling
            ),
            pi_forge_location_publishing=pi_forge_location_publishing,
            pota_spot_polling=pota_spot_polling,
            pota_enrichment=pota_enrichment,
            ft8_receive=ft8_receive,
            ft8_band_control=ft8_band_control,
            ft8_authorization=ft8_authorization,
            ft8_qso=ft8_qso,
            ft8_logging=ft8_logging,
            ft8_worked_today=ft8_worked_today,
            ft8_performance_recorder=ft8_performance_recorder,
            ft8_performance_sync=ft8_performance_sync,
            ft8_hardware_transmit=resolved_ft8_executor,
        )
        if (
            config.ft8.transmit.enabled
            and isinstance(radio, Ft891Radio)
            and runtime.ft8_authorization is not None
            and runtime.ft8_qso is not None
        ):
            preparation = FT8RadioPreparationService(radio)

            def start_prepared_ft8_qso(
                activity: FT8CQActivity,
                prepared_radio_state: RadioState,
                attempt_seed: object,
            ) -> None:
                from rolling_thunder.ft8.performance import FT8AttemptSeed

                if not isinstance(attempt_seed, FT8AttemptSeed):
                    raise TypeError("attempt_seed must be an FT8AttemptSeed")
                assert runtime.ft8_authorization is not None
                assert runtime.ft8_qso is not None
                context = runtime.ft8_authorization.authorize(
                    activity,
                    radio_state=prepared_radio_state,
                    gps_state=runtime.latest_gps_state,
                    qso_id=attempt_seed.attempt_id,
                )
                runtime.ft8_qso.authorize_and_start(context)

            runtime.ft8_qso_start = FT8QsoStartController(
                preparation,
                start_prepared_ft8_qso,
                preparation_failure_handler=(
                    None
                    if runtime.ft8_performance_recorder is None
                    else runtime.ft8_performance_recorder.record_preparation_failure
                ),
            )

        def ft8_activity_visible(activity: FT8CQActivity) -> bool:
            worked = runtime.ft8_worked_today
            state = runtime.latest_radio_state
            if worked is None or state.frequency is None:
                return True
            try:
                band = resolve_radio_band(state.frequency)
            except RadioBandResolutionError:
                return True
            return not worked.is_suppressed(activity.callsign, band)

        if ft8_receive is not None:
            runtime.ft8_panel = FT8PanelController(
                receive_state=lambda: runtime.latest_ft8_receive_state,
                qso_state=lambda: runtime.latest_ft8_qso_state,
                qso_context=lambda: runtime.latest_ft8_qso_context,
                qso_result=lambda: runtime.latest_ft8_qso_result,
                authorize=runtime.request_ft8_qso,
                abort=runtime.abort_ft8_qso,
                return_to_browser=runtime.return_ft8_to_browser,
                attempt_count=lambda: (
                    0 if runtime.ft8_qso is None else runtime.ft8_qso.attempt_count
                ),
                attempts_per_state=lambda: (
                    0 if runtime.ft8_qso is None else runtime.ft8_qso.attempts_per_state
                ),
                authorization_enabled=lambda: runtime.ft8_qso is not None,
                activity_filter=ft8_activity_visible,
            )
        return runtime

    @property
    def latest_ft8_receive_state(self) -> FT8ReceiveState | None:
        """Return immutable FT8 receive state without performing I/O."""
        if self.ft8_receive is None:
            return None
        return self.ft8_receive.latest_state

    def request_ft8_qso(self, activity: FT8CQActivity) -> bool:
        """Accept one selected CQ without blocking the caller on CAT preparation."""
        if self.ft8_authorization is None or self.ft8_qso is None:
            return False
        if self.ft8_qso_start is not None:
            seed = build_ft8_attempt_seed(
                activity,
                radio_state=self.latest_radio_state,
                gps_state=self.latest_gps_state,
                home_grid=self.ft8_authorization.home_grid,
                started_at_utc=self.ft8_authorization.clock.now_utc(),
            )
            return self.ft8_qso_start.start(activity, attempt_seed=seed)
        self.authorize_ft8_qso(activity)
        return True

    @property
    def latest_ft8_qso_start_status(self) -> FT8QsoStartStatus | None:
        """Return the immutable preparation/restore status when production prep exists."""
        if self.ft8_qso_start is None:
            return None
        return self.ft8_qso_start.status

    def exit_ft8_context(self) -> bool:
        """Abort any live QSO first, then request required 100 W/AUTO restore."""
        if self.ft8_qso is not None:
            self.ft8_qso.abort()
        if self.ft8_qso_start is None:
            return True
        return self.ft8_qso_start.request_restore()

    def authorize_ft8_qso(self, activity: FT8CQActivity) -> FT8QsoContext:
        """Freeze and start one explicitly selected FT8 CQ through application services."""
        if self.ft8_authorization is None or self.ft8_qso is None:
            raise RuntimeError("FT8 QSO transmit execution is disabled")
        context = self.ft8_authorization.authorize(
            activity,
            radio_state=self.latest_radio_state,
            gps_state=self.latest_gps_state,
        )
        self.ft8_qso.authorize_and_start(context)
        return context

    def abort_ft8_qso(self) -> None:
        """Abort the active FT8 QSO without exposing CAT/PTT to callers."""
        if self.ft8_qso is not None:
            self.ft8_qso.abort()

    def return_ft8_to_browser(self) -> FT8QsoResult | None:
        """Release one terminal QSO and restore CQ-browser ownership."""
        if self.ft8_qso is None:
            return None
        return self.ft8_qso.return_to_browser()

    @property
    def latest_ft8_qso_state(self) -> FT8QsoState:
        """Return presentation-safe FT8 QSO state."""
        if self.ft8_qso is None:
            return FT8QsoState.IDLE
        return self.ft8_qso.state

    @property
    def latest_ft8_qso_context(self) -> FT8QsoContext | None:
        """Return the active frozen QSO context, when present."""
        if self.ft8_qso is None:
            return None
        return self.ft8_qso.context

    @property
    def latest_ft8_qso_result(self) -> FT8QsoResult | None:
        """Return the immutable terminal QSO result without persistence."""
        if self.ft8_qso is None:
            return None
        return self.ft8_qso.result

    @property
    def pota_receive_tune_executor(self) -> PotaReceiveTuneExecutor:
        """Return POTA tuning through the ordered receive-tuning service."""
        return PotaReceiveTuneExecutor(ReceiveTuningService(self.radio))

    @property
    def latest_radio_state(self) -> RadioState:
        """Return the latest radio state available to the UI."""
        return self.polling.latest_state

    @property
    def latest_gps_state(self) -> GPSState | None:
        """Return the latest GPS snapshot available to the UI."""
        if self._started and self.gps_polling is not None:
            return self.gps_polling.latest_state
        if self.gps is None:
            return None
        return self.gps.get_state()

    @property
    def latest_clock_sync_state(self) -> ClockSyncState | None:
        """Return the latest GPS-assisted system-clock state without performing I/O."""
        if self.clock_sync is None:
            return None
        return self.clock_sync.latest_state

    @property
    def latest_live_map_state(self) -> LiveMapSnapshot | None:
        """Return the latest immutable map snapshot without performing I/O."""
        if self.live_map is None:
            return None
        return self.live_map.latest_state

    @property
    def latest_pota_map_marker_state(self) -> PotaMapMarkerSnapshot | None:
        """Return immutable visible POTA marker state without performing I/O."""
        if self.pota_map_markers is None:
            return None
        return self.pota_map_markers.latest_state

    @property
    def latest_live_radar_state(self) -> LiveRadarSnapshot | None:
        """Return the latest immutable radar overlay snapshot without performing I/O."""
        if self.live_radar is None:
            return None
        return self.live_radar.latest_state

    @property
    def latest_forge_spot_state(self) -> PiForgeSpotState | None:
        """Return the latest Forge-derived shared-spot state without I/O."""
        if self.pi_forge_spot_polling is None:
            return None
        return self.pi_forge_spot_polling.latest_state

    @property
    def latest_forge_weather_state(self) -> PiForgeWeatherState:
        """Return immutable Pi weather state, including explicit disabled state."""
        if self.pi_forge_weather_polling is None:
            return PiForgeWeatherState.disabled()
        return self.pi_forge_weather_polling.latest_state

    @property
    def latest_forge_weather_alert_state(
        self,
    ) -> PiForgeWeatherAlertState:
        """Return locally guarded retained alert state without I/O."""
        if self.pi_forge_weather_alert_polling is None:
            return PiForgeWeatherAlertState.disabled()

        return self.pi_forge_weather_alert_polling.latest_state

    @property
    def latest_forge_weather_alert_notifications(
        self,
    ) -> PiForgeWeatherAlertNotificationBatch:
        """Return latest claimed alert event batch without I/O."""
        if self.pi_forge_weather_alert_polling is None:
            return PiForgeWeatherAlertNotificationBatch()

        return (
            self.pi_forge_weather_alert_polling
            .latest_notification_batch
        )

    @property
    def latest_forge_location_publisher_state(
        self,
    ) -> PiForgeLocationPublisherState | None:
        """Return the latest Pi-to-Forge location publication state without I/O."""
        if self.pi_forge_location_publishing is None:
            return None
        return self.pi_forge_location_publishing.latest_state

    @property
    def latest_pota_spot_state(self) -> PotaSpotServiceState | None:
        """Return the latest POTA spot snapshot available to consumers."""
        if self.pota_spot_polling is None:
            return None
        return self.pota_spot_polling.latest_state

    def start(self) -> RadioState:
        """Start hardware polling and the remaining application services."""
        if self._started:
            raise RuntimeError("Application runtime is already started.")

        state = self.polling.start()
        self._started = True
        try:
            self._start_remaining_services()
        except (OSError, RuntimeError, ValueError):
            try:
                self.stop()
            except (OSError, RuntimeError, ValueError) as cleanup_error:
                print(f"Rolling Thunder startup cleanup error: {cleanup_error}")
            raise
        return state

    def _start_remaining_services(self) -> None:
        """Start services after radio polling with rollback handled by start()."""
        if self.ft8_receive is not None:
            self.ft8_receive.start()
        if self.gps_polling is not None:
            self.gps_polling.start()
        if self.clock_sync is not None:
            self.clock_sync.start()
        if self.pi_forge_location_publishing is not None:
            self.pi_forge_location_publishing.start()
        if self.live_map is not None:
            self.live_map.start()
        if self.callsign_map is not None:
            self.callsign_map.start()
        if self.pota_map_markers is not None:
            self.pota_map_markers.start()
        if self.map_solar is not None:
            initial_gps = (
                self.gps_polling.latest_state
                if self.gps_polling is not None
                else None
            )
            self.map_solar.start(initial_gps)
        if self.live_radar is not None:
            self.live_radar.start()
        if self.home_platform_health is not None:
            self.home_platform_health.start()
        if self.contact_qrz_enrichment is not None:
            self.contact_qrz_enrichment.start()
        if self.contact_sync is not None:
            self.contact_sync.start()
        if self.network_keepalive is not None:
            self.network_keepalive.start()
        if self.pi_forge_spot_polling is not None:
            self.pi_forge_spot_polling.start()
        if self.pi_forge_weather_polling is not None:
            self.pi_forge_weather_polling.start()
        if self.pi_forge_weather_alert_polling is not None:
            self.pi_forge_weather_alert_polling.start()
        self.pota_enrichment.start()
        if self.pota_spot_polling is not None:
            self.pota_spot_polling.start()

    def stop(self) -> RadioState:
        """Stop polling and disconnect configured hardware safely."""
        if not self._started:
            if self.ft8_qso is not None:
                self.ft8_qso.close()
            if self.ft8_hardware_transmit is not None:
                self.ft8_hardware_transmit.close()
            return self.radio.get_state()

        if self.ft8_qso is not None:
            self.ft8_qso.close()
        if self.ft8_hardware_transmit is not None:
            self.ft8_hardware_transmit.close()
        if self.ft8_receive is not None:
            self.ft8_receive.stop()
        if self.pota_spot_polling is not None:
            self.pota_spot_polling.stop()
        self.pota_enrichment.stop()
        if self.pi_forge_weather_alert_polling is not None:
            self.pi_forge_weather_alert_polling.stop()
        if self.pi_forge_weather_polling is not None:
            self.pi_forge_weather_polling.stop()
        if self.pi_forge_spot_polling is not None:
            self.pi_forge_spot_polling.stop()
        if self.network_keepalive is not None:
            self.network_keepalive.stop()
        if self.contact_sync is not None:
            self.contact_sync.stop()
        if self.contact_qrz_enrichment is not None:
            self.contact_qrz_enrichment.stop()
        if self.home_platform_health is not None:
            self.home_platform_health.stop()
        if self.live_radar is not None:
            self.live_radar.stop()
        if self.map_solar is not None:
            self.map_solar.stop()
        if self.pota_map_markers is not None:
            self.pota_map_markers.stop()
        if self.callsign_map is not None:
            self.callsign_map.stop()
        if self.live_map is not None:
            self.live_map.stop()
        if self.callsign_info is not None:
            self.callsign_info.stop()
        if self.operator_preferences is not None:
            self.operator_preferences.stop()
        if self.pi_forge_location_publishing is not None:
            self.pi_forge_location_publishing.stop()
        if self.clock_sync is not None:
            self.clock_sync.stop()
        if self.gps_polling is not None:
            self.gps_polling.stop()
        self.polling.stop()
        if self.gps is not None:
            self.gps.disconnect()
        state = self.radio.disconnect()
        self._started = False
        return state
