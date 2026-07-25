"""FT-891 radio adapter built on the typed CAT transport boundary."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Final

from rolling_thunder.cat_transport import CatTransport
from rolling_thunder.domain import (
    Frequency,
    RadioConnectionState,
    RadioMode,
    RadioState,
)
from rolling_thunder.ft891_cat import (
    Ft891CatError,
    encode_read_frequency,
    encode_read_mode,
    encode_set_frequency,
    encode_set_mode,
    parse_frequency_reply,
    parse_mode_reply,
)
from rolling_thunder.radio import RadioBand, RadioConnectionError

Clock = Callable[[], datetime]

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
    return datetime.now(UTC)


class Ft891Radio:
    """Hardware adapter implementing the safe Rolling Thunder radio boundary."""

    def __init__(self, transport: CatTransport, *, clock: Clock = _utc_now) -> None:
        self._transport = transport
        self._clock = clock
        self._state = RadioState(
            connection_state=RadioConnectionState.DISCONNECTED,
            updated_at=self._timestamp(),
        )

    def connect(self) -> RadioState:
        """Open CAT and read the current frequency and mode."""
        try:
            self._transport.open()
            frequency = parse_frequency_reply(
                self._transport.query(encode_read_frequency())
            )
            mode = parse_mode_reply(self._transport.query(encode_read_mode()))
        except (RadioConnectionError, Ft891CatError) as error:
            error_message = str(error) or error.__class__.__name__
            try:
                self._transport.close()
            except RadioConnectionError as close_error:
                error_message = (
                    f"{error_message}; additionally failed to close CAT transport: "
                    f"{close_error}"
                )

            self._state = RadioState(
                connection_state=RadioConnectionState.ERROR,
                transmitting=False,
                updated_at=self._timestamp(),
                last_error=error_message,
            )
            if isinstance(error, RadioConnectionError):
                raise
            raise RadioConnectionError(
                f"Could not connect to FT-891: {error}"
            ) from error

        self._state = RadioState(
            connection_state=RadioConnectionState.CONNECTED,
            frequency=frequency,
            mode=mode,
            transmitting=False,
            updated_at=self._timestamp(),
        )
        return self._state

    def disconnect(self) -> RadioState:
        """Close CAT and report a disconnected state."""
        self._transport.close()
        self._state = RadioState(
            connection_state=RadioConnectionState.DISCONNECTED,
            transmitting=False,
            updated_at=self._timestamp(),
        )
        return self._state

    def get_state(self) -> RadioState:
        """Return the latest immutable state snapshot."""
        return self._state

    def set_frequency(self, frequency: Frequency) -> RadioState:
        """Set VFO-A frequency and return the resulting state."""
        self._require_connected()
        self._transport.command(encode_set_frequency(frequency))
        self._state = RadioState(
            connection_state=RadioConnectionState.CONNECTED,
            frequency=frequency,
            mode=self._state.mode,
            transmitting=False,
            updated_at=self._timestamp(),
        )
        return self._state

    def set_mode(self, mode: RadioMode) -> RadioState:
        """Set the main receiver mode and return the resulting state."""
        self._require_connected()
        self._transport.command(encode_set_mode(mode))
        self._state = RadioState(
            connection_state=RadioConnectionState.CONNECTED,
            frequency=self._state.frequency,
            mode=mode,
            transmitting=False,
            updated_at=self._timestamp(),
        )
        return self._state

    def change_band(self, band: RadioBand) -> RadioState:
        """Select the deterministic frequency and mode for one amateur band."""
        self._require_connected()
        frequency, mode = _BAND_DEFAULTS[band]
        self._transport.command(encode_set_mode(mode))
        self._transport.command(encode_set_frequency(frequency))
        self._state = RadioState(
            connection_state=RadioConnectionState.CONNECTED,
            frequency=frequency,
            mode=mode,
            transmitting=False,
            updated_at=self._timestamp(),
        )
        return self._state

    def _require_connected(self) -> None:
        if self._state.connection_state is not RadioConnectionState.CONNECTED:
            raise RadioConnectionError(
                "FT-891 operation requires a connected radio."
            )

    def _timestamp(self) -> datetime:
        timestamp = self._clock()
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("FT-891 clock must return a timezone-aware datetime.")
        return timestamp.astimezone(UTC)
