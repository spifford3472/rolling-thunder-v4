"""Deterministic mock implementation of the radio boundary."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Final

from rolling_thunder.domain import (
    Frequency,
    RadioConnectionState,
    RadioMode,
    RadioState,
)
from rolling_thunder.radio import RadioBand, RadioConnectionError

Clock = Callable[[], datetime]

_DEFAULT_FREQUENCY: Final = Frequency(hz=14_250_000)
_DEFAULT_MODE: Final = RadioMode.USB

_BAND_DEFAULTS: Final[dict[RadioBand, tuple[Frequency, RadioMode]]] = {
    RadioBand.BAND_160M: (Frequency(hz=1_900_000), RadioMode.LSB),
    RadioBand.BAND_80M: (Frequency(hz=3_900_000), RadioMode.LSB),
    RadioBand.BAND_60M: (Frequency(hz=5_357_000), RadioMode.USB),
    RadioBand.BAND_40M: (Frequency(hz=7_200_000), RadioMode.LSB),
    RadioBand.BAND_30M: (Frequency(hz=10_120_000), RadioMode.CW),
    RadioBand.BAND_20M: (Frequency(hz=14_250_000), RadioMode.USB),
    RadioBand.BAND_17M: (Frequency(hz=18_130_000), RadioMode.USB),
    RadioBand.BAND_15M: (Frequency(hz=21_300_000), RadioMode.USB),
    RadioBand.BAND_12M: (Frequency(hz=24_950_000), RadioMode.USB),
    RadioBand.BAND_10M: (Frequency(hz=28_400_000), RadioMode.USB),
    RadioBand.BAND_6M: (Frequency(hz=50_125_000), RadioMode.USB),
}


def _utc_now() -> datetime:
    """Return the current UTC time for normal mock use."""
    return datetime.now(UTC)


class MockRadio:
    """Predictable in-memory radio used by tests and mock-hardware mode."""

    def __init__(
        self,
        *,
        clock: Clock = _utc_now,
        initial_frequency: Frequency = _DEFAULT_FREQUENCY,
        initial_mode: RadioMode = _DEFAULT_MODE,
    ) -> None:
        self._clock = clock
        self._frequency = initial_frequency
        self._mode = initial_mode
        self._connected = False
        self._state = RadioState(
            connection_state=RadioConnectionState.DISCONNECTED,
            updated_at=self._timestamp(),
        )

    def connect(self) -> RadioState:
        """Connect immediately and expose the configured initial state."""
        self._connected = True
        return self._replace_state(
            connection_state=RadioConnectionState.CONNECTED,
            frequency=self._frequency,
            mode=self._mode,
        )

    def disconnect(self) -> RadioState:
        """Disconnect immediately and clear hardware-dependent readout."""
        self._connected = False
        return self._replace_state(
            connection_state=RadioConnectionState.DISCONNECTED,
            frequency=None,
            mode=None,
        )

    def get_state(self) -> RadioState:
        """Return the latest immutable snapshot."""
        return self._state

    def set_frequency(self, frequency: Frequency) -> RadioState:
        """Change frequency while connected."""
        self._require_connected()
        if not isinstance(frequency, Frequency):
            raise TypeError("frequency must be a Frequency")

        self._frequency = frequency
        return self._replace_state(frequency=frequency)

    def set_mode(self, mode: RadioMode) -> RadioState:
        """Change operating mode while connected."""
        self._require_connected()
        if not isinstance(mode, RadioMode):
            raise TypeError("mode must be a RadioMode")

        self._mode = mode
        return self._replace_state(mode=mode)

    def change_band(self, band: RadioBand) -> RadioState:
        """Select the mock's deterministic frequency and mode for a band."""
        self._require_connected()
        if not isinstance(band, RadioBand):
            raise TypeError("band must be a RadioBand")

        frequency, mode = _BAND_DEFAULTS[band]
        self._frequency = frequency
        self._mode = mode
        return self._replace_state(frequency=frequency, mode=mode)

    def simulate_error(self, message: str) -> RadioState:
        """Enter a deterministic adapter-error state for application tests."""
        normalized = message.strip()
        if not normalized:
            raise ValueError("mock radio error message must not be empty")

        self._connected = False
        return self._replace_state(
            connection_state=RadioConnectionState.ERROR,
            frequency=None,
            mode=None,
            last_error=normalized,
        )

    def _require_connected(self) -> None:
        if not self._connected:
            raise RadioConnectionError("Radio operation requires a connected radio.")

    def _timestamp(self) -> datetime:
        timestamp = self._clock()
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("Mock radio clock must return a timezone-aware datetime.")
        return timestamp.astimezone(UTC)

    def _replace_state(
        self,
        *,
        connection_state: RadioConnectionState | None = None,
        frequency: Frequency | None | object = ..., 
        mode: RadioMode | None | object = ...,
        last_error: str | None | object = ...,
    ) -> RadioState:
        updates: dict[str, object] = {
            "updated_at": self._timestamp(),
            "transmitting": False,
        }
        if connection_state is not None:
            updates["connection_state"] = connection_state
        if frequency is not ...:
            updates["frequency"] = frequency
        if mode is not ...:
            updates["mode"] = mode
        if last_error is not ...:
            updates["last_error"] = last_error
        elif connection_state is not RadioConnectionState.ERROR:
            updates["last_error"] = None

        self._state = self._state.model_copy(update=updates)
        return self._state
