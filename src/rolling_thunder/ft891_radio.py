"""FT-891 radio adapter built on the typed CAT transport boundary."""

from collections.abc import Callable
from datetime import UTC, datetime
from threading import Lock

from rolling_thunder.cat_transport import CatTransport
from rolling_thunder.domain import (
    Frequency,
    RadioConnectionState,
    RadioMode,
    RadioState,
)
from rolling_thunder.ft891_cat import (
    Ft891CatError,
    encode_memory_to_vfo_a,
    encode_read_frequency,
    encode_read_memory_channel,
    encode_read_mode,
    encode_select_band_memory,
    encode_set_frequency,
    encode_set_mode,
    memory_channel_for_band,
    parse_frequency_reply,
    parse_memory_channel_reply,
    parse_mode_reply,
)
from rolling_thunder.radio import (
    BandChangeRequiredError,
    RadioBand,
    RadioConnectionError,
    RadioVerificationError,
)
from rolling_thunder.radio_band import (
    RadioBandResolutionError,
    resolve_radio_band,
)

Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


class Ft891Radio:
    """Hardware adapter implementing the safe Rolling Thunder radio boundary."""

    def __init__(self, transport: CatTransport, *, clock: Clock = _utc_now) -> None:
        self._transport = transport
        self._clock = clock
        self._operation_lock = Lock()
        self._state = RadioState(
            connection_state=RadioConnectionState.DISCONNECTED,
            updated_at=self._timestamp(),
        )

    def connect(self) -> RadioState:
        """Open CAT and read the current frequency and mode."""
        with self._operation_lock:
            try:
                self._transport.open()
                frequency, mode = self._read_hardware_state()
            except (RadioConnectionError, Ft891CatError) as error:
                error_message = self._close_after_failure(
                    str(error) or error.__class__.__name__
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
        with self._operation_lock:
            self._transport.close()
            self._state = RadioState(
                connection_state=RadioConnectionState.DISCONNECTED,
                transmitting=False,
                updated_at=self._timestamp(),
            )
            return self._state

    def get_state(self) -> RadioState:
        """Return the latest immutable state snapshot."""
        with self._operation_lock:
            return self._state

    def refresh_state(self) -> RadioState:
        """Read current frequency and mode, detecting CAT device loss."""
        with self._operation_lock:
            self._require_connected()
            previous_frequency = self._state.frequency
            previous_mode = self._state.mode
            try:
                frequency, mode = self._read_hardware_state()
            except (RadioConnectionError, Ft891CatError) as error:
                error_message = self._close_after_failure(
                    str(error) or error.__class__.__name__
                )
                self._state = RadioState(
                    connection_state=RadioConnectionState.ERROR,
                    frequency=previous_frequency,
                    mode=previous_mode,
                    transmitting=False,
                    updated_at=self._timestamp(),
                    last_error=error_message,
                )
                if isinstance(error, RadioConnectionError):
                    raise
                raise RadioConnectionError(
                    f"Could not refresh FT-891 state: {error}"
                ) from error

            self._state = RadioState(
                connection_state=RadioConnectionState.CONNECTED,
                frequency=frequency,
                mode=mode,
                transmitting=False,
                updated_at=self._timestamp(),
            )
            return self._state

    def set_frequency(self, frequency: Frequency) -> RadioState:
        """Set and verify VFO-A frequency without implicitly changing bands."""
        with self._operation_lock:
            self._require_connected()
            current_frequency = self._current_frequency()
            target_band = resolve_radio_band(frequency)

            try:
                current_band = resolve_radio_band(current_frequency)
            except RadioBandResolutionError as error:
                raise BandChangeRequiredError(
                    "Current FT-891 frequency does not identify a supported amateur "
                    f"band; select {target_band.value} before setting frequency."
                ) from error

            if current_band is not target_band:
                raise BandChangeRequiredError(
                    f"Select {target_band.value} before changing frequency from "
                    f"{current_band.value}."
                )

            self._transport.command(encode_set_frequency(frequency))
            verified_frequency = parse_frequency_reply(
                self._transport.query(encode_read_frequency())
            )

            self._state = RadioState(
                connection_state=RadioConnectionState.CONNECTED,
                frequency=verified_frequency,
                mode=self._state.mode,
                transmitting=False,
                updated_at=self._timestamp(),
            )

            if verified_frequency != frequency:
                raise RadioVerificationError(
                    "FT-891 frequency verification failed: requested "
                    f"{frequency.hz} Hz but read back {verified_frequency.hz} Hz."
                )

            return self._state

    def set_mode(self, mode: RadioMode) -> RadioState:
        """Set and verify the main receiver mode."""
        with self._operation_lock:
            self._require_connected()
            self._transport.command(encode_set_mode(mode))
            verified_mode = parse_mode_reply(
                self._transport.query(encode_read_mode())
            )

            self._state = RadioState(
                connection_state=RadioConnectionState.CONNECTED,
                frequency=self._state.frequency,
                mode=verified_mode,
                transmitting=False,
                updated_at=self._timestamp(),
            )

            if verified_mode is not mode:
                raise RadioVerificationError(
                    "FT-891 mode verification failed: requested "
                    f"{mode.value} but read back {verified_mode.value}."
                )

            return self._state

    def select_band(self, band: RadioBand) -> RadioState:
        """Recall the dedicated band memory to VFO-A and verify the result."""
        with self._operation_lock:
            self._require_connected()
            expected_memory = memory_channel_for_band(band)

            self._transport.command(encode_select_band_memory(band))
            selected_memory = parse_memory_channel_reply(
                self._transport.query(encode_read_memory_channel())
            )
            if selected_memory != expected_memory:
                raise RadioVerificationError(
                    "FT-891 band-memory verification failed: requested memory "
                    f"{expected_memory:03d} for {band.value} but read back "
                    f"{selected_memory:03d}."
                )

            self._transport.command(encode_memory_to_vfo_a())
            frequency, mode = self._read_hardware_state()

            self._state = RadioState(
                connection_state=RadioConnectionState.CONNECTED,
                frequency=frequency,
                mode=mode,
                transmitting=False,
                updated_at=self._timestamp(),
            )

            try:
                verified_band = resolve_radio_band(frequency)
            except RadioBandResolutionError as error:
                raise RadioVerificationError(
                    "FT-891 band-memory verification failed because the recalled "
                    f"VFO-A frequency {frequency.hz} Hz is outside supported bands."
                ) from error

            if verified_band is not band:
                raise RadioVerificationError(
                    "FT-891 band-memory verification failed: requested "
                    f"{band.value} via memory {expected_memory:03d} but recalled "
                    f"{verified_band.value}."
                )

            return self._state

    def _read_hardware_state(self) -> tuple[Frequency, RadioMode]:
        frequency = parse_frequency_reply(
            self._transport.query(encode_read_frequency())
        )
        mode = parse_mode_reply(self._transport.query(encode_read_mode()))
        return frequency, mode

    def _close_after_failure(self, error_message: str) -> str:
        try:
            self._transport.close()
        except RadioConnectionError as close_error:
            return (
                f"{error_message}; additionally failed to close CAT transport: "
                f"{close_error}"
            )
        return error_message

    def _require_connected(self) -> None:
        if self._state.connection_state is not RadioConnectionState.CONNECTED:
            raise RadioConnectionError(
                "FT-891 operation requires a connected radio."
            )

    def _current_frequency(self) -> Frequency:
        frequency = self._state.frequency
        if frequency is None:
            raise RadioConnectionError(
                "FT-891 operation requires a known current frequency."
            )
        return frequency

    def _timestamp(self) -> datetime:
        timestamp = self._clock()
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("FT-891 clock must return a timezone-aware datetime.")
        return timestamp.astimezone(UTC)
