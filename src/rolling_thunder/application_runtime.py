"""Application composition root for the first persistent Pi dashboard."""

import os
from collections.abc import Callable
from concurrent.futures import Executor
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from time import monotonic

from rolling_thunder.application_secrets import ApplicationSecrets
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
from rolling_thunder.ft891_radio import Ft891Radio
from rolling_thunder.gps import GPSReceiver, GPSState
from rolling_thunder.gps_polling import GPSPollingService
from rolling_thunder.home_platform import HomePlatformClient
from rolling_thunder.home_platform_health import HomePlatformHealthService
from rolling_thunder.http_home_platform import HttpHomePlatformClient, HttpTransport
from rolling_thunder.live_map_service import LiveMapService, LiveMapSnapshot
from rolling_thunder.live_radar_service import LiveRadarOverlayService, LiveRadarSnapshot
from rolling_thunder.map_sources import InstalledMapRegistry, MapTileResolver
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
)
from rolling_thunder.pi_forge_spot_polling import ExecutorFactory, PiForgeSpotPollingService
from rolling_thunder.pi_forge_spot_service import PiForgeSpotState
from rolling_thunder.pota_enrichment import PotaEnrichmentService
from rolling_thunder.pota_receive_tune_executor import PotaReceiveTuneExecutor
from rolling_thunder.pota_runtime import build_pota_spot_polling
from rolling_thunder.pota_spot_polling import PotaSpotPollingService
from rolling_thunder.pota_spot_service import PotaSpotServiceState
from rolling_thunder.pyserial_cat_transport import PySerialCatTransport
from rolling_thunder.qrz_profile_image import QrzProfileImageProvider
from rolling_thunder.qrz_xml import QrzXmlCallsignNameProvider
from rolling_thunder.radio import Radio
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
    live_radar: LiveRadarOverlayService | None = None
    map_zoom_settings: MapZoomSettingsController | None = None
    operator_preferences: OperatorPreferenceService | None = None
    home_platform_client: HomePlatformClient | None = None
    home_platform_health: HomePlatformHealthService | None = None
    contact_qrz_enrichment: ContactQrzEnrichmentService | None = None
    contact_sync: ContactSyncService | None = None
    network_keepalive: NetworkKeepaliveService | None = None
    pi_forge_spot_polling: PiForgeSpotPollingService | None = None
    pi_forge_location_publishing: PiForgeLocationPublishingService | None = None
    pota_spot_polling: PotaSpotPollingService | None = None
    pota_enrichment: PotaEnrichmentService = field(default_factory=PotaEnrichmentService)
    status_messages: StatusMessageService = field(default_factory=StatusMessageService)
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
        network_keepalive_scheduler: PollScheduler | None = None,
        forge_scheduler: PollScheduler | None = None,
        forge_location_scheduler: PollScheduler | None = None,
        pota_scheduler: PollScheduler | None = None,
        interval_s: float = 1.0,
        gps_interval_s: float = 1.0,
        radio_factory: RadioFactory = _build_serial_radio,
        gps_factory: GPSFactory = SerialGPSReceiver,
        clock_sync_setter: SystemClockSetter | None = None,
        clock_sync_enabled: bool | None = None,
        home_platform_transport: HttpTransport | None = None,
        network_keepalive_transport: NetworkKeepaliveTransport | None = None,
        forge_transport: HttpTransport | None = None,
        forge_location_transport: HttpTransport | None = None,
        pota_transport: HttpTransport | None = None,
        qrz_transport: HttpTransport | None = None,
        weather_transport: HttpTransport | None = None,
        image_transport: HttpTransport | None = None,
        state_map_transport: HttpTransport | None = None,
        map_transport: HttpTransport | None = None,
        forge_executor_factory: ExecutorFactory | None = None,
        forge_location_executor_factory: ExecutorFactory | None = None,
        enrichment_executor: Executor | None = None,
        map_executor: Executor | None = None,
        radar_executor: Executor | None = None,
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

        live_map: LiveMapService | None = None
        live_radar: LiveRadarOverlayService | None = None
        map_zoom_settings: MapZoomSettingsController | None = None
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
            map_zoom_settings = MapZoomSettingsController(
                live_map,
                zoom_bounds,
                operator_preferences,
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

        return cls(
            radio=radio,
            polling=RadioPollingService(
                radio,
                polling_scheduler,
                interval_s=interval_s,
            ),
            contact_logging=ContactLoggingService(
                repository,
                qrz_fallback_available=qrz_provider is not None,
            ),
            gps=gps,
            gps_polling=gps_polling,
            clock_sync=clock_sync,
            live_map=live_map,
            live_radar=live_radar,
            map_zoom_settings=map_zoom_settings,
            operator_preferences=operator_preferences,
            home_platform_client=home_platform_client,
            home_platform_health=home_platform_health,
            contact_qrz_enrichment=contact_qrz_enrichment,
            contact_sync=contact_sync,
            network_keepalive=network_keepalive,
            pi_forge_spot_polling=pi_forge_spot_polling,
            pi_forge_location_publishing=pi_forge_location_publishing,
            pota_spot_polling=pota_spot_polling,
            pota_enrichment=pota_enrichment,
        )

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
        if self.gps_polling is not None:
            self.gps_polling.start()
        if self.clock_sync is not None:
            self.clock_sync.start()
        if self.pi_forge_location_publishing is not None:
            self.pi_forge_location_publishing.start()
        if self.live_map is not None:
            self.live_map.start()
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
        self.pota_enrichment.start()
        if self.pota_spot_polling is not None:
            self.pota_spot_polling.start()
        self._started = True
        return state

    def stop(self) -> RadioState:
        """Stop polling and disconnect configured hardware safely."""
        if not self._started:
            return self.radio.get_state()

        if self.pota_spot_polling is not None:
            self.pota_spot_polling.stop()
        self.pota_enrichment.stop()
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
        if self.live_map is not None:
            self.live_map.stop()
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
