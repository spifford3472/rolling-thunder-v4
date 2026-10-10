"""Application composition root for the first persistent Pi dashboard."""

import logging
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
from rolling_thunder.completed_ft8_ingestion_client import (
    CompletedFt8HttpTransport,
    HttpCompletedFt8IngestionClient,
)
from rolling_thunder.completed_qso_ingestion_client import (
    CompletedQsoHttpTransport,
    HttpCompletedQsoIngestionClient,
)
from rolling_thunder.completed_qso_producer import (
    CompletedQsoCapture,
    CompletedQsoDeliveryService,
    CompletedQsoDeliveryWorker,
    CompletedQsoPostDurabilityAdapter,
    CompletedQsoProducerError,
    CompletedQsoProducerRepository,
)
from rolling_thunder.config import (
    ApplicationConfig,
    FT8DecoderBackend,
    HardwareAdapterMode,
)
from rolling_thunder.contact_logging import ContactLoggingService
from rolling_thunder.contact_qrz_enrichment import ContactQrzEnrichmentService
from rolling_thunder.contact_repository import ContactRepository
from rolling_thunder.contact_retry import ContactRetryRepository
from rolling_thunder.contact_sync import ContactSyncService
from rolling_thunder.contact_weather import PublishedContactWeatherSnapshotProvider
from rolling_thunder.domain import Contact, RadioState
from rolling_thunder.forge_radar_client import HttpForgeRadarClient
from rolling_thunder.ft8.activity import FT8CQActivityManager, is_us_cq_dx
from rolling_thunder.ft8.attempt_history import (
    FT8AttemptHistoryService,
    FT8AttemptVisualState,
)
from rolling_thunder.ft8.audio import AlsaArecordFT8AudioInput, FT8AudioInput
from rolling_thunder.ft8.audio_output import AlsaAplayFT8AudioOutput, FT8AudioOutput
from rolling_thunder.ft8.authorization import (
    FT8QsoAuthorizationError,
    FT8QsoAuthorizationService,
)
from rolling_thunder.ft8.band_control import FT8BandController
from rolling_thunder.ft8.coordinator import FT8QsoResult
from rolling_thunder.ft8.decoder import (
    ComparingFT8Decoder,
    FT8Decoder,
    Ft8LibDecoder,
    Ft8monDecoder,
)
from rolling_thunder.ft8.diagnostics import (
    ChronyNTPClockProbe,
    FT8MorningDiagnosticSession,
    NTPClockStatus,
)
from rolling_thunder.ft8.domain import (
    FT8CQActivity,
    FT8IncomingCall,
    FT8Period,
    FT8QsoContext,
    FT8QsoState,
)
from rolling_thunder.ft8.encoder import FT8Encoder, Ft8LibEncoder
from rolling_thunder.ft8.hardware_transmit import (
    BoundedFT8HardwareTransmitExecutor,
    FT8QsoHardwareTransmitExecutor,
)
from rolling_thunder.ft8.logging import FT8QsoLoggingService
from rolling_thunder.ft8.operator_qso import FT8OperatorQsoService
from rolling_thunder.ft8.panel import FT8PanelController
from rolling_thunder.ft8.performance import FT8AttemptSeed
from rolling_thunder.ft8.performance_outbox import FT8PerformanceOutboxRepository
from rolling_thunder.ft8.performance_recording import (
    FT8PerformanceRecorder,
    build_ft8_attempt_seed,
    build_ft8_responder_attempt_seed,
)
from rolling_thunder.ft8.performance_sync import FT8PerformanceSyncService
from rolling_thunder.ft8.period_repository import FT8PeriodSyncService, FT8TransmitPeriodRepository
from rolling_thunder.ft8.power_advisor import FT8PowerPolicy
from rolling_thunder.ft8.radio_preparation import (
    FT8RadioPreparationService,
    configure_ft8_receive_settings,
    restore_ft8_normal_receive_settings,
)
from rolling_thunder.ft8.receive import (
    BoundedFT8PeriodRecorder,
    FT8ReceiveService,
    FT8ReceiveState,
)
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
from rolling_thunder.known_callsign_client import (
    HttpKnownCallsignClient,
    KnownCallsignCache,
    KnownCallsignPollingService,
)
from rolling_thunder.live_map_service import LiveMapService, LiveMapSnapshot
from rolling_thunder.live_radar_service import LiveRadarOverlayService, LiveRadarSnapshot
from rolling_thunder.local_jurisdiction import LocalJurisdictionResolver
from rolling_thunder.map_solar import MapSolarStyleService, SynchronizedMapStyleTarget
from rolling_thunder.map_sources import (
    InstalledMapRegistry,
    MapTileResolver,
)
from rolling_thunder.map_tiles import (
    MapTileCache,
    MapTileClient,
    StylePartitionedMapTileCache,
)
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
from rolling_thunder.pota_spots import PotaSpot
from rolling_thunder.pyserial_cat_transport import PySerialCatTransport
from rolling_thunder.qrz_profile_image import QrzProfileImageProvider
from rolling_thunder.qrz_xml import QrzXmlCallsignNameProvider
from rolling_thunder.radio import Radio, RadioError
from rolling_thunder.radio_band import RadioBandResolutionError, resolve_radio_band
from rolling_thunder.radio_polling import PollScheduler, RadioPollingService
from rolling_thunder.receive_tuning import ReceiveTuningService
from rolling_thunder.serial_gps import SerialGPSReceiver
from rolling_thunder.shared_pota_contact import shared_pota_spots_for_contact
from rolling_thunder.status_messages import StatusMessageService
from rolling_thunder.threading_scheduler import ThreadingPollScheduler

GPSFactory = Callable[..., GPSReceiver]
RadioFactory = Callable[..., Radio]
_CLOCK_SYNC_ENV = "ROLLING_THUNDER_GPS_CLOCK_SYNC"
_LOGGER = logging.getLogger("rolling_thunder.application_runtime")


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
    known_callsigns: KnownCallsignPollingService | None = None
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
    ft8_power_policy: FT8PowerPolicy = field(default_factory=FT8PowerPolicy)
    ft8_qso: FT8OperatorQsoService | None = None
    ft8_qso_start: FT8QsoStartController | None = None
    ft8_logging: FT8QsoLoggingService | None = None
    ft8_worked_today: FT8WorkedTodayService | None = None
    ft8_performance_recorder: FT8PerformanceRecorder | None = None
    ft8_attempt_history: FT8AttemptHistoryService | None = None
    ft8_performance_sync: FT8PerformanceSyncService | None = None
    ft8_completed_qso_delivery: CompletedQsoDeliveryService | None = None
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
        ft8_completed_contact_handler: Callable[[Contact], None] | None = None,
        ft8_completed_qso_producer: CompletedQsoCapture | None = None,
        ft8_completed_qso_delivery_scheduler: PollScheduler | None = None,
        ft8_completed_qso_voacap_transport: CompletedQsoHttpTransport | None = None,
        ft8_completed_qso_psk_transport: CompletedFt8HttpTransport | None = None,
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
        ft8_ntp_status: Callable[[], NTPClockStatus] | None = None,
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
        jurisdiction_artifact = (
            Path(__file__).resolve().parent
            / "data"
            / "us_state_jurisdiction_v2.zip"
        )
        jurisdiction_resolver = LocalJurisdictionResolver.from_artifact(
            jurisdiction_artifact
        )
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

        known_callsigns: KnownCallsignPollingService | None = None
        friend_config = config.forge.known_callsigns
        if friend_config.enabled:
            assert friend_config.api_url is not None
            known_callsigns = KnownCallsignPollingService(
                KnownCallsignCache(
                    HttpKnownCallsignClient(str(friend_config.api_url),
                                           timeout_s=friend_config.request_timeout_s,
                                           transport=callsign_info_transport or forge_transport),
                    stale_after_s=friend_config.stale_after_s,
                ), polling_scheduler, interval_s=friend_config.refresh_interval_s,
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

        contact_weather_snapshots = PublishedContactWeatherSnapshotProvider(
            local_state=lambda: (
                PiForgeWeatherState.disabled()
                if pi_forge_weather_polling is None
                else pi_forge_weather_polling.latest_state
            ),
            callsign_state=lambda: (
                None if callsign_info is None else callsign_info.state
            ),
        )
        contact_logging = ContactLoggingService(
            repository,
            qrz_fallback_available=qrz_provider is not None,
            jurisdiction_resolver=jurisdiction_resolver,
            weather_snapshot_provider=contact_weather_snapshots,
        )
        ft8_worked_today = (
            FT8WorkedTodayService(repository) if config.ft8.enabled else None
        )

        def ft8_contact_completed(contact: Contact) -> None:
            """Publish durable FT8 completion to worked state and shared sync lifecycle."""
            if ft8_worked_today is not None:
                ft8_worked_today.record_completed(contact)
            if ft8_completed_contact_handler is not None:
                ft8_completed_contact_handler(contact)

        def ft8_pota_spots() -> tuple[PotaSpot, ...]:
            if pi_forge_spot_polling is not None:
                forge_state = pi_forge_spot_polling.latest_state
                if forge_state.snapshot is not None:
                    return shared_pota_spots_for_contact(forge_state.snapshot.spots)
            if pota_spot_polling is not None:
                pota_state = pota_spot_polling.latest_state
                return pota_state.spots
            return ()

        ft8_logging = FT8QsoLoggingService(
            contact_logging,
            completed_contact_handler=ft8_contact_completed,
            pota_spots_provider=ft8_pota_spots,
        )
        ft8_performance_outbox = (
            FT8PerformanceOutboxRepository(config.storage.database_path)
            if config.ft8.enabled
            else None
        )
        ft8_attempt_history = (
            None
            if ft8_performance_outbox is None
            else FT8AttemptHistoryService(ft8_performance_outbox)
        )
        ft8_performance_recorder = (
            None
            if ft8_performance_outbox is None
            else FT8PerformanceRecorder(
                ft8_performance_outbox,
                attempt_handler=(
                    None
                    if ft8_attempt_history is None
                    else ft8_attempt_history.record
                ),
            )
        )
        ft8_performance_sync = None
        if ft8_performance_outbox is not None and isinstance(
            home_platform_client,
            HttpHomePlatformClient,
        ):
            ft8_performance_sync = FT8PerformanceSyncService(
                ft8_performance_outbox,
                home_platform_client,
                ft8_performance_sync_scheduler or ThreadingPollScheduler(),
                interval_s=platform_config.contact_sync_interval_s,
                batch_size=platform_config.contact_sync_batch_size,
                period_sync=FT8PeriodSyncService(
                    FT8TransmitPeriodRepository(config.storage.database_path),
                    home_platform_client,
                ),
            )

        resolved_completed_qso_producer = ft8_completed_qso_producer
        completed_qso_delivery: CompletedQsoDeliveryService | None = None
        completed_qso_config = config.ft8.completed_qso_delivery
        if completed_qso_config.enabled:
            credentials = resolved_secrets.completed_qso_delivery
            if credentials is None:
                raise ValueError(
                    "completed-QSO delivery requires protected receiver credentials"
                )
            outbox = CompletedQsoProducerRepository(
                completed_qso_config.database_path
            )
            if resolved_completed_qso_producer is None:
                resolved_completed_qso_producer = CompletedQsoPostDurabilityAdapter(
                    outbox
                )
            voacap_sink = None
            if completed_qso_config.voacap.enabled:
                voacap_token = credentials.voacap_token
                if voacap_token is None:
                    raise ValueError(
                        "enabled completed-QSO VOACAP delivery requires "
                        "ROLLING_THUNDER_COMPLETED_QSO_VOACAP_TOKEN"
                    )
                voacap_url = completed_qso_config.voacap.base_url
                assert voacap_url is not None
                voacap_sink = HttpCompletedQsoIngestionClient(
                    str(voacap_url),
                    bearer_token=voacap_token.get_secret_value(),
                    timeout_s=completed_qso_config.voacap.timeout_s,
                    transport=ft8_completed_qso_voacap_transport,
                )
            psk_reporter_sink = None
            if completed_qso_config.psk_reporter.enabled:
                psk_token = credentials.psk_reporter_token
                if psk_token is None:
                    raise ValueError(
                        "enabled completed-QSO PSK Reporter delivery requires "
                        "ROLLING_THUNDER_COMPLETED_QSO_PSKREPORTER_TOKEN"
                    )
                psk_url = completed_qso_config.psk_reporter.base_url
                assert psk_url is not None
                psk_reporter_sink = HttpCompletedFt8IngestionClient(
                    str(psk_url),
                    bearer_token=psk_token.get_secret_value(),
                    timeout_s=completed_qso_config.psk_reporter.timeout_s,
                    transport=ft8_completed_qso_psk_transport,
                )
            completed_qso_delivery = CompletedQsoDeliveryService(
                CompletedQsoDeliveryWorker(
                    outbox,
                    voacap_sink=voacap_sink,
                    psk_reporter_sink=psk_reporter_sink,
                    batch_size=completed_qso_config.batch_size,
                    retry_initial_delay=timedelta(
                        seconds=completed_qso_config.retry_initial_delay_s
                    ),
                    retry_maximum_delay=timedelta(
                        seconds=completed_qso_config.retry_maximum_delay_s
                    ),
                ),
                ft8_completed_qso_delivery_scheduler or ThreadingPollScheduler(),
                interval_s=completed_qso_config.interval_s,
            )

        ft8_receive: FT8ReceiveService | None = None
        resolved_ft8_clock: FT8Clock | None = None
        if config.ft8.enabled:
            resolved_ft8_clock = ft8_clock or SystemFT8Clock()
            diagnostic_session = None
            diagnostic_end = config.ft8.receive.diagnostic_session_end_local
            if diagnostic_end is not None:
                diagnostic_session = FT8MorningDiagnosticSession(
                    now_utc=resolved_ft8_clock.now_utc,
                    end_local=diagnostic_end,
                )
            decoder_executable = config.ft8.receive.decoder_executable
            if decoder_executable is None:
                raise ValueError(
                    "FT8 decoder executable is required when FT8 is enabled."
                )
            resolved_audio_input = ft8_audio_input or AlsaArecordFT8AudioInput(
                config.ft8.receive.audio_device,
                clock=resolved_ft8_clock,
            )
            if ft8_decoder is not None:
                resolved_decoder = ft8_decoder
            else:
                decoder_type = (
                    Ft8LibDecoder
                    if config.ft8.receive.decoder_backend is FT8DecoderBackend.FT8_LIB
                    else Ft8monDecoder
                )
                resolved_decoder = decoder_type(
                    str(decoder_executable),
                    timeout_s=config.ft8.receive.decoder_timeout_s,
                )
                comparison_executable = (
                    config.ft8.receive.comparison_decoder_executable
                )
                comparison_backend = config.ft8.receive.comparison_backend
                if comparison_executable is not None and comparison_backend is not None:
                    comparison_type = (
                        Ft8LibDecoder
                        if comparison_backend is FT8DecoderBackend.FT8_LIB
                        else Ft8monDecoder
                    )
                    resolved_decoder = ComparingFT8Decoder(
                        resolved_decoder,
                        comparison_type(
                            str(comparison_executable),
                            timeout_s=config.ft8.receive.decoder_timeout_s,
                        ),
                        comparison_enabled=(
                            None
                            if diagnostic_session is None
                            else lambda: diagnostic_session.is_active
                        ),
                    )
            recorder = None
            if config.ft8.receive.saved_pcm_periods:
                saved_pcm_directory = config.ft8.receive.saved_pcm_directory
                assert saved_pcm_directory is not None
                recorder = BoundedFT8PeriodRecorder(
                    saved_pcm_directory,
                    maximum_periods=config.ft8.receive.saved_pcm_periods,
                )
            ft8_receive = FT8ReceiveService(
                resolved_audio_input,
                resolved_decoder,
                FT8CQActivityManager(),
                reconnect_delay_s=config.ft8.receive.reconnect_delay_s,
                clock=resolved_ft8_clock,
                gps_utc=lambda: gps_polling.latest_state.utc,
                ntp_status=ft8_ntp_status or ChronyNTPClockProbe(),
                recorder=recorder,
                diagnostic_session=diagnostic_session,
                diagnostic_snapshot_path=(
                    config.ft8.receive.diagnostic_snapshot_path
                ),
                local_callsign=config.operator.callsign,
            )

        ft8_band_control: FT8BandController | None = None
        if config.ft8.enabled:
            receive_settings_callback: Callable[[], object] | None = None
            normal_settings_callback: Callable[[], object] | None = None
            if isinstance(radio, Ft891Radio):
                def apply_ft8_receive_settings() -> object:
                    configure_ft8_receive_settings(radio)
                    return None

                def restore_ft8_normal_settings() -> object:
                    restore_ft8_normal_receive_settings(radio)
                    return None

                receive_settings_callback = apply_ft8_receive_settings
                normal_settings_callback = restore_ft8_normal_settings

            ft8_band_control = FT8BandController(
                ReceiveTuningService(radio),
                radio.get_state,
                configure_receive_settings=receive_settings_callback,
                restore_normal_settings=normal_settings_callback,
                band_changed=(
                    ft8_receive.clear_cq_activity
                    if ft8_receive is not None
                    else None
                ),
            )

        ft8_authorization: FT8QsoAuthorizationService | None = None
        ft8_qso: FT8OperatorQsoService | None = None
        resolved_ft8_executor: FT8QsoHardwareTransmitExecutor | None = None
        if config.ft8.enabled:
            assert resolved_ft8_clock is not None
            ft8_authorization = FT8QsoAuthorizationService(
                local_callsign=config.operator.callsign,
                home_grid=config.operator.home_grid,
                clock=resolved_ft8_clock,
                jurisdiction_resolver=jurisdiction_resolver,
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
                period_store = FT8TransmitPeriodRepository(config.storage.database_path)
                resolved_ft8_executor = BoundedFT8HardwareTransmitExecutor(
                    radio,
                    resolved_ft8_audio_output,
                    period_recorder=period_store.append,
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
                tx_power_end_watts = self_power = None
                power_reader = getattr(radio, "read_power_watts", None)
                if callable(power_reader):
                    try:
                        self_power = power_reader()
                    except (RadioError, RuntimeError, ValueError):
                        self_power = None
                if isinstance(self_power, int) and not isinstance(self_power, bool):
                    tx_power_end_watts = self_power
                contact = ft8_logging.handle_terminal_result(
                    result,
                    tx_power_watts=(
                        tx_power_end_watts
                        if config.contact_logging.capture_tx_power
                        else None
                    ),
                    weather_notes_enabled=config.contact_logging.append_weather_notes,
                )
                terminal_attempt = None
                if ft8_performance_recorder is not None:
                    meter_summary = None
                    meter_reader = getattr(resolved_ft8_executor, "meter_summary", None)
                    if callable(meter_reader):
                        meter_summary = meter_reader(result.context.qso_id)
                    terminal_attempt = ft8_performance_recorder.record_qso_result(
                        result,
                        power_meter_raw=(
                            None if meter_summary is None else meter_summary.power_peak_raw
                        ),
                        swr_meter_raw=(
                            None if meter_summary is None else meter_summary.swr_peak_raw
                        ),
                        alc_meter_raw=(
                            None if meter_summary is None else meter_summary.alc_peak_raw
                        ),
                        tx_power_end_watts=tx_power_end_watts,
                    )
                if (
                    contact is not None
                    and terminal_attempt is not None
                    and resolved_completed_qso_producer is not None
                ):
                    try:
                        resolved_completed_qso_producer.capture(contact, terminal_attempt)
                    except (CompletedQsoProducerError, OSError, ValueError) as error:
                        # Both authoritative source records are already durable. A
                        # producer-outbox failure must not undo logging or alter the
                        # terminal radio result.
                        _LOGGER.error(
                            "Completed-QSO analytics event could not be queued: %s",
                            error,
                        )
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
                callsign_map_cache = StylePartitionedMapTileCache(
                    map_config.cache_directory / "callsign-info",
                    style=map_config.style.value,
                    retention=timedelta(days=map_config.cache_retention_days),
                    maximum_tiles=map_config.maximum_cached_tiles,
                )
                callsign_tile_url_template = (
                    map_config.callsign_tile_url_template
                    or map_config.tile_url_template
                )
                transform_callsign_night = (
                    map_config.callsign_tile_url_template is None
                    and "{style}" not in map_config.tile_url_template
                )
                callsign_map_client = MapTileClient(
                    callsign_tile_url_template,
                    timeout_s=map_config.request_timeout_s,
                    transport=map_transport,
                    style=map_config.style.value,
                    require_style_token_for_night=not transform_callsign_night,
                    transform_night_without_style_token=transform_callsign_night,
                )
                callsign_map_registry = InstalledMapRegistry.load(())
                callsign_map_resolver = MapTileResolver(
                    callsign_map_registry,
                    callsign_map_cache,
                    callsign_map_client,
                    style=map_config.style,
                    online_attribution=map_config.online_attribution,
                )
                callsign_map = LiveMapService(
                    callsign_map_resolver,
                    zoom=6,
                    executor=callsign_map_executor,
                )
            map_style_target = SynchronizedMapStyleTarget(
                live_map,
                (() if callsign_map is None else (callsign_map,)),
            )
            map_zoom_settings = MapZoomSettingsController(
                live_map,
                zoom_bounds,
                operator_preferences,
                style_target=map_style_target,
            )
            map_solar = MapSolarStyleService(
                map_style_target,
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
            known_callsigns=known_callsigns,
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
            ft8_power_policy=config.ft8.power,
            ft8_qso=ft8_qso,
            ft8_logging=ft8_logging,
            ft8_worked_today=ft8_worked_today,
            ft8_performance_recorder=ft8_performance_recorder,
            ft8_attempt_history=ft8_attempt_history,
            ft8_performance_sync=ft8_performance_sync,
            ft8_completed_qso_delivery=completed_qso_delivery,
            ft8_hardware_transmit=resolved_ft8_executor,
        )
        if (
            config.ft8.transmit.enabled
            and isinstance(radio, Ft891Radio)
            and runtime.ft8_authorization is not None
            and runtime.ft8_qso is not None
        ):
            preparation = FT8RadioPreparationService(radio, power_policy=config.ft8.power)

            def start_prepared_ft8_qso(
                candidate: FT8CQActivity | FT8IncomingCall,
                prepared_radio_state: RadioState,
                attempt_seed: FT8AttemptSeed,
            ) -> None:
                assert runtime.ft8_authorization is not None
                assert runtime.ft8_qso is not None
                if isinstance(candidate, FT8IncomingCall):
                    context = runtime.ft8_authorization.authorize_incoming(
                        candidate,
                        radio_state=prepared_radio_state,
                        gps_state=runtime.latest_gps_state,
                        qso_id=attempt_seed.attempt_id,
                        selection_freshness_validated=True,
                        tx_power_target_watts=attempt_seed.tx_power_target_watts,
                        tx_power_start_watts=attempt_seed.tx_power_target_watts,
                    )
                else:
                    context = runtime.ft8_authorization.authorize(
                        candidate,
                        radio_state=prepared_radio_state,
                        gps_state=runtime.latest_gps_state,
                        qso_id=attempt_seed.attempt_id,
                        selection_freshness_validated=True,
                        tx_power_target_watts=attempt_seed.tx_power_target_watts,
                        tx_power_start_watts=attempt_seed.tx_power_target_watts,
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
                failure_recovery=lambda: configure_ft8_receive_settings(radio),
            )

        def ft8_activity_visible(activity: FT8CQActivity) -> bool:
            if is_us_cq_dx(activity):
                return False
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
                respond=runtime.request_ft8_response,
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
        selected_at_utc = self.ft8_authorization.clock.now_utc()
        current_period = FT8Period.from_utc(selected_at_utc)
        receive = self.latest_ft8_receive_state
        if receive is None or receive.last_period is None:
            return False
        selection_period = receive.last_period
        try:
            self.ft8_authorization.validate_selection_freshness(
                activity,
                selection_period=selection_period,
                current_period=current_period,
            )
        except FT8QsoAuthorizationError:
            return False
        if self.ft8_qso_start is not None:
            seed = build_ft8_attempt_seed(
                activity,
                radio_state=self.latest_radio_state,
                gps_state=self.latest_gps_state,
                home_grid=self.ft8_authorization.home_grid,
                started_at_utc=selected_at_utc,
                power_policy=self.ft8_power_policy,
            )
            return self.ft8_qso_start.start(activity, attempt_seed=seed)
        context = self.ft8_authorization.authorize(
            activity,
            radio_state=self.latest_radio_state,
            gps_state=self.latest_gps_state,
            freshness_reference_period=selection_period,
        )
        self.ft8_qso.authorize_and_start(context)
        return True

    def request_ft8_response(self, incoming: FT8IncomingCall) -> bool:
        """Accept one exact addressed decode after explicit Button 2 authorization."""
        if self.ft8_authorization is None or self.ft8_qso is None:
            return False
        selected_at_utc = self.ft8_authorization.clock.now_utc()
        current_period = FT8Period.from_utc(selected_at_utc)
        receive = self.latest_ft8_receive_state
        if receive is None or receive.last_period is None:
            return False
        selection_period = receive.last_period
        try:
            self.ft8_authorization.validate_incoming_freshness(
                incoming,
                selection_period=selection_period,
                current_period=current_period,
            )
        except FT8QsoAuthorizationError:
            return False
        if self.ft8_qso_start is not None:
            seed = build_ft8_responder_attempt_seed(
                incoming,
                radio_state=self.latest_radio_state,
                gps_state=self.latest_gps_state,
                home_grid=self.ft8_authorization.home_grid,
                started_at_utc=selected_at_utc,
                power_policy=self.ft8_power_policy,
            )
            return self.ft8_qso_start.start_incoming(incoming, attempt_seed=seed)
        context = self.ft8_authorization.authorize_incoming(
            incoming,
            radio_state=self.latest_radio_state,
            gps_state=self.latest_gps_state,
            freshness_reference_period=selection_period,
        )
        self.ft8_qso.authorize_and_start(context)
        return True

    @property
    def latest_ft8_qso_start_status(self) -> FT8QsoStartStatus | None:
        """Return the immutable preparation/restore status when production prep exists."""
        if self.ft8_qso_start is None:
            return None
        return self.ft8_qso_start.status

    def clear_ft8_qso_start_status(self) -> bool:
        """Clear a non-busy prior FT8 start result before a new selection."""
        if self.ft8_qso_start is None:
            return True
        return self.ft8_qso_start.reset_to_idle()

    def ft8_attempt_visual_state(
        self,
        callsign: str,
    ) -> FT8AttemptVisualState | None:
        """Return today's prior failed/aborted state for a visible CQ on this band."""
        history = self.ft8_attempt_history
        frequency = self.latest_radio_state.frequency
        if history is None or frequency is None:
            return None
        try:
            band = resolve_radio_band(frequency)
        except RadioBandResolutionError:
            return None
        return history.state_for(callsign, band.value)

    def enter_ft8_context(self) -> bool:
        """Apply the owner-required FT8 receive settings without transmit authority."""
        if self.ft8_band_control is None:
            return True
        return self.ft8_band_control.enter_ft8()

    def exit_ft8_context(self) -> bool:
        """Abort live FT8 work, restore 100 W when applicable, and return BFO to AUTO."""
        if self.ft8_qso is not None:
            self.ft8_qso.abort()

        accepted = True
        if self.ft8_qso_start is not None:
            accepted = self.ft8_qso_start.request_restore() and accepted
        if self.ft8_band_control is not None:
            accepted = self.ft8_band_control.exit_ft8() and accepted
        return accepted

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

    def authorize_ft8_response(self, incoming: FT8IncomingCall) -> FT8QsoContext:
        """Freeze and start one explicitly accepted inbound FT8 call."""
        if self.ft8_authorization is None or self.ft8_qso is None:
            raise RuntimeError("FT8 QSO transmit execution is disabled")
        context = self.ft8_authorization.authorize_incoming(
            incoming,
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
        result = self.ft8_qso.return_to_browser()
        if self.ft8_qso_start is not None:
            self.ft8_qso_start.reset_to_idle()
        return result

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

    def read_tx_power_watts(self) -> int | None:
        """Best-effort configured-power snapshot through the typed radio adapter."""
        reader = getattr(self.radio, "read_power_watts", None)
        if not callable(reader):
            return None
        try:
            value = reader()
        except (RadioError, RuntimeError, ValueError):
            return None
        return value if isinstance(value, int) and not isinstance(value, bool) else None

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
        if self.known_callsigns is not None:
            self.known_callsigns.start()
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
        if self.ft8_performance_sync is not None:
            self.ft8_performance_sync.start()
        if self.ft8_completed_qso_delivery is not None:
            self.ft8_completed_qso_delivery.start()
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
        if self.ft8_completed_qso_delivery is not None:
            self.ft8_completed_qso_delivery.stop()
        if self.ft8_performance_sync is not None:
            self.ft8_performance_sync.stop()
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
        if self.known_callsigns is not None:
            self.known_callsigns.stop()
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
        if self.ft8_band_control is not None:
            self.ft8_band_control.restore_normal_settings_for_shutdown()
        if self.gps is not None:
            self.gps.disconnect()
        state = self.radio.disconnect()
        self._started = False
        return state
