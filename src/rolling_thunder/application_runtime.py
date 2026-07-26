"""Application composition root for the first persistent Pi dashboard."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from rolling_thunder.config import ApplicationConfig
from rolling_thunder.contact_logging import ContactLoggingService
from rolling_thunder.contact_repository import ContactRepository
from rolling_thunder.domain import RadioState
from rolling_thunder.ft891_radio import Ft891Radio
from rolling_thunder.gps import GPSReceiver, GPSState
from rolling_thunder.gps_polling import GPSPollingService
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
    _started: bool = False

    @classmethod
    def from_config(
        cls,
        config: ApplicationConfig,
        *,
        scheduler: PollScheduler | None = None,
        gps_scheduler: PollScheduler | None = None,
        interval_s: float = 1.0,
        gps_interval_s: float = 1.0,
        gps_factory: GPSFactory = SerialGPSReceiver,
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
        )

    @property
    def latest_radio_state(self) -> RadioState:
        """Return the latest radio state available to the UI."""
        return self.polling.latest_state

    @property
    def latest_gps_state(self) -> GPSState | None:
        """Return the latest GPS snapshot available to the UI."""
        if self.gps_polling is not None:
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
        self._started = True
        return state

    def stop(self) -> RadioState:
        """Stop polling and disconnect configured hardware safely."""
        if not self._started:
            return self.radio.get_state()

        if self.gps_polling is not None:
            self.gps_polling.stop()
        self.polling.stop()
        if self.gps is not None:
            self.gps.disconnect()
        state = self.radio.disconnect()
        self._started = False
        return state
