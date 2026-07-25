"""Application composition root for the first persistent Pi dashboard."""

from dataclasses import dataclass

from rolling_thunder.config import ApplicationConfig
from rolling_thunder.contact_logging import ContactLoggingService
from rolling_thunder.contact_repository import ContactRepository
from rolling_thunder.domain import RadioState
from rolling_thunder.ft891_radio import Ft891Radio
from rolling_thunder.mock_radio import MockRadio
from rolling_thunder.pyserial_cat_transport import PySerialCatTransport
from rolling_thunder.radio import Radio
from rolling_thunder.radio_polling import PollScheduler, RadioPollingService
from rolling_thunder.threading_scheduler import ThreadingPollScheduler


@dataclass
class ApplicationRuntime:
    """Own the composed radio, logging, and polling lifecycle for one run."""

    radio: Radio
    polling: RadioPollingService
    contact_logging: ContactLoggingService
    _started: bool = False

    @classmethod
    def from_config(
        cls,
        config: ApplicationConfig,
        *,
        scheduler: PollScheduler | None = None,
        interval_s: float = 1.0,
    ) -> "ApplicationRuntime":
        """Build configured radio, persistence, and application services."""
        radio: Radio
        if config.hardware.mock:
            radio = MockRadio()
        else:
            radio_device = config.hardware.radio_device
            if radio_device is None:
                raise ValueError("A radio device is required outside mock mode.")
            radio = Ft891Radio(PySerialCatTransport(radio_device))

        polling_scheduler = scheduler or ThreadingPollScheduler()
        repository = ContactRepository(config.storage.database_path)
        return cls(
            radio=radio,
            polling=RadioPollingService(
                radio,
                polling_scheduler,
                interval_s=interval_s,
            ),
            contact_logging=ContactLoggingService(repository),
        )

    @property
    def latest_radio_state(self) -> RadioState:
        """Return the latest radio state available to the UI."""
        return self.polling.latest_state

    def start(self) -> RadioState:
        """Connect the radio and begin background polling."""
        if self._started:
            raise RuntimeError("Application runtime is already started.")
        state = self.radio.connect()
        self.polling.start()
        self._started = True
        return state

    def stop(self) -> RadioState:
        """Stop polling and disconnect the radio safely and idempotently."""
        if not self._started:
            return self.radio.get_state()
        self.polling.stop()
        state = self.radio.disconnect()
        self._started = False
        return state
