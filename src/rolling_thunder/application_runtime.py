"""Application composition root for the first persistent Pi dashboard."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from rolling_thunder.config import ApplicationConfig
from rolling_thunder.contact_logging import ContactLoggingService
from rolling_thunder.contact_repository import ContactRepository
from rolling_thunder.contact_retry import ContactRetryRepository
from rolling_thunder.contact_sync import ContactSyncService
from rolling_thunder.domain import RadioState
from rolling_thunder.ft891_radio import Ft891Radio
from rolling_thunder.gps import GPSReceiver, GPSState
from rolling_thunder.gps_polling import GPSPollingService
from rolling_thunder.home_platform import HomePlatformClient
from rolling_thunder.home_platform_health import HomePlatformHealthService
from rolling_thunder.http_home_platform import HttpHomePlatformClient, HttpTransport
from rolling_thunder.mock_gps import MockGPSReceiver
from rolling_thunder.mock_radio import MockRadio
from rolling_thunder.pyserial_cat_transport import PySerialCatTransport
from rolling_thunder.radio import Radio
from rolling_thunder.radio_polling import PollScheduler, RadioPollingService
from rolling_thunder.serial_gps import SerialGPSReceiver
from rolling_thunder.threading_scheduler import ThreadingPollScheduler

GPSFactory = Callable[[Path], GPSReceiver]


@dataclass
class ApplicationRuntime:
    """Own composed radio, GPS, logging, and polling lifecycle for one run."""

    radio: Radio
    polling: RadioPollingService
    contact_logging: ContactLoggingService
    gps: GPSReceiver | None = None
    gps_polling: GPSPollingService | None = None
    home_platform_client: HomePlatformClient | None = None
    home_platform_health: HomePlatformHealthService | None = None
    contact_sync: ContactSyncService | None = None
    _started: bool = False

    @classmethod
    def from_config(
        cls,
        config: ApplicationConfig,
        *,
        scheduler: PollScheduler | None = None,
        gps_scheduler: PollScheduler | None = None,
        home_platform_scheduler: PollScheduler | None = None,
        contact_sync_scheduler: PollScheduler | None = None,
        interval_s: float = 1.0,
        gps_interval_s: float = 1.0,
        gps_factory: GPSFactory = SerialGPSReceiver,
        home_platform_transport: HttpTransport | None = None,
    ) -> "ApplicationRuntime":
        """Build configured hardware, persistence, and application services."""
        radio: Radio
        gps: GPSReceiver
        if config.hardware.mock:
            radio = MockRadio()
            gps = MockGPSReceiver()
        else:
            radio_device = config.hardware.radio_device
            if radio_device is None:
                raise ValueError("A radio device is required outside mock mode.")
            gps_device = config.hardware.gps_device
            if gps_device is None:
                raise ValueError("A GPS device is required outside mock mode.")
            radio = Ft891Radio(PySerialCatTransport(radio_device))
            gps = gps_factory(gps_device)

        polling_scheduler = scheduler or ThreadingPollScheduler()
        gps_polling_scheduler = gps_scheduler or ThreadingPollScheduler()
        repository = ContactRepository(config.storage.database_path)

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

        return cls(
            radio=radio,
            polling=RadioPollingService(
                radio,
                polling_scheduler,
                interval_s=interval_s,
            ),
            contact_logging=ContactLoggingService(repository),
            gps=gps,
            gps_polling=GPSPollingService(
                gps,
                gps_polling_scheduler,
                interval_s=gps_interval_s,
            ),
            home_platform_client=home_platform_client,
            home_platform_health=home_platform_health,
            contact_sync=contact_sync,
        )

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

    def start(self) -> RadioState:
        """Connect configured hardware and begin background polling."""
        if self._started:
            raise RuntimeError("Application runtime is already started.")

        state = self.radio.connect()
        if self.gps is not None:
            self.gps.connect()
        self.polling.start()
        if self.gps_polling is not None:
            self.gps_polling.start()
        if self.home_platform_health is not None:
            self.home_platform_health.start()
        if self.contact_sync is not None:
            self.contact_sync.start()
        self._started = True
        return state

    def stop(self) -> RadioState:
        """Stop polling and disconnect configured hardware safely."""
        if not self._started:
            return self.radio.get_state()

        if self.contact_sync is not None:
            self.contact_sync.stop()
        if self.home_platform_health is not None:
            self.home_platform_health.stop()
        if self.gps_polling is not None:
            self.gps_polling.stop()
        self.polling.stop()
        if self.gps is not None:
            self.gps.disconnect()
        state = self.radio.disconnect()
        self._started = False
        return state
