"""Read-only serial GPS adapter for NMEA position, movement, and UTC sentences."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import Protocol, cast

import serial

from rolling_thunder.domain import GPSFixState, GPSPosition
from rolling_thunder.gps import (
    GPSConnectionError,
    GPSConnectionState,
    GPSError,
    GPSState,
    GPSUTCObservation,
    GPSUTCSource,
)


class GPSParseError(GPSError):
    """Raised when a supported NMEA sentence is malformed or inconsistent."""


class SerialLinePort(Protocol):
    """Minimal read-only serial surface required by the GPS adapter."""

    @property
    def is_open(self) -> bool:
        """Return whether the serial port is open."""
        ...

    def close(self) -> None:
        """Close the serial port."""
        ...

    def readline(self) -> bytes:
        """Read one newline-terminated NMEA sentence."""
        ...


SerialFactory = Callable[[Path, int, float], SerialLinePort]
Clock = Callable[[], datetime]
MonotonicClock = Callable[[], float]
_SUPPORTED_GGA_SENTENCE_TYPES = frozenset({"GPGGA", "GNGGA"})
_SUPPORTED_RMC_SENTENCE_TYPES = frozenset({"GPRMC", "GNRMC"})
_KNOTS_TO_METRES_PER_SECOND = 0.514444
_DEFAULT_MAXIMUM_SENTENCES_PER_REFRESH = 32
_DEFAULT_MAXIMUM_UTC_AGE_S = 5.0


def _open_serial(device: Path, baud_rate: int, timeout_s: float) -> SerialLinePort:
    """Open a conventional 8-N-1 NMEA serial device."""
    port = serial.Serial(
        port=str(device),
        baudrate=baud_rate,
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        timeout=timeout_s,
    )
    return cast(SerialLinePort, port)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _validate_checksum(sentence: str) -> str:
    if not sentence.startswith("$") or "*" not in sentence:
        raise GPSParseError("NMEA sentence must start with '$' and include a checksum.")
    payload, checksum_text = sentence[1:].split("*", 1)
    if len(checksum_text) != 2:
        raise GPSParseError("NMEA checksum must contain exactly two hexadecimal digits.")
    try:
        expected = int(checksum_text, 16)
    except ValueError as error:
        raise GPSParseError("NMEA checksum is not hexadecimal.") from error

    actual = 0
    for character in payload:
        actual ^= ord(character)
    if actual != expected:
        raise GPSParseError(
            f"NMEA checksum mismatch: expected {expected:02X}, calculated {actual:02X}."
        )
    return payload


def _parse_coordinate(value: str, hemisphere: str, *, latitude: bool) -> float:
    if not value:
        raise GPSParseError("NMEA coordinate is missing.")
    degree_digits = 2 if latitude else 3
    if len(value) <= degree_digits:
        raise GPSParseError("NMEA coordinate is too short.")
    try:
        degrees = int(value[:degree_digits])
        minutes = float(value[degree_digits:])
    except ValueError as error:
        raise GPSParseError(f"Invalid NMEA coordinate {value!r}.") from error
    if not 0 <= minutes < 60:
        raise GPSParseError(f"Invalid NMEA coordinate minutes {minutes!r}.")

    coordinate = degrees + minutes / 60
    valid_hemispheres = {"N", "S"} if latitude else {"E", "W"}
    if hemisphere not in valid_hemispheres:
        raise GPSParseError(f"Invalid NMEA hemisphere {hemisphere!r}.")
    if hemisphere in {"S", "W"}:
        coordinate = -coordinate
    return coordinate


def _parse_rmc_utc(time_text: str, date_text: str) -> datetime | None:
    """Parse RMC UTC time/date without consulting the host wall clock."""
    if not time_text or not date_text:
        return None

    if len(date_text) != 6 or not date_text.isdigit():
        raise GPSParseError("RMC date must use DDMMYY digits.")

    whole_time, separator, fraction = time_text.partition(".")
    if len(whole_time) != 6 or not whole_time.isdigit():
        raise GPSParseError("RMC UTC time must use HHMMSS with optional fractional seconds.")
    if separator:
        if not fraction or not fraction.isdigit() or len(fraction) > 6:
            raise GPSParseError("RMC fractional seconds must contain one to six digits.")
        microsecond = int(fraction.ljust(6, "0"))
    else:
        microsecond = 0

    day = int(date_text[0:2])
    month = int(date_text[2:4])
    year_two_digits = int(date_text[4:6])
    year = 2000 + year_two_digits if year_two_digits < 80 else 1900 + year_two_digits
    hour = int(whole_time[0:2])
    minute = int(whole_time[2:4])
    second = int(whole_time[4:6])

    try:
        return datetime(
            year,
            month,
            day,
            hour,
            minute,
            second,
            microsecond,
            tzinfo=UTC,
        )
    except ValueError as error:
        raise GPSParseError("RMC UTC time/date is outside the valid calendar range.") from error


def parse_gga_sentence(sentence: str, *, updated_at: datetime) -> GPSPosition:
    """Parse one checksummed GGA sentence into a validated position snapshot."""
    normalized = sentence.strip()
    payload = _validate_checksum(normalized)
    fields = payload.split(",")
    if len(fields) < 15 or fields[0] not in _SUPPORTED_GGA_SENTENCE_TYPES:
        raise GPSParseError("Expected a supported GPGGA or GNGGA sentence.")

    try:
        fix_quality = int(fields[6])
        satellites = int(fields[7]) if fields[7] else None
    except ValueError as error:
        raise GPSParseError("GGA fix quality or satellite count is invalid.") from error

    if fix_quality == 0:
        return GPSPosition(
            fix_state=GPSFixState.NO_FIX,
            satellites=satellites,
            updated_at=updated_at,
        )
    if fix_quality < 0:
        raise GPSParseError("GGA fix quality cannot be negative.")

    latitude = _parse_coordinate(fields[2], fields[3], latitude=True)
    longitude = _parse_coordinate(fields[4], fields[5], latitude=False)
    if fields[10] and fields[10] != "M":
        raise GPSParseError("GGA altitude units must be metres.")
    try:
        altitude_m = float(fields[9]) if fields[9] else None
    except ValueError as error:
        raise GPSParseError("GGA altitude is invalid.") from error
    if altitude_m is None:
        raise GPSParseError("A valid GGA fix must include altitude.")

    return GPSPosition(
        fix_state=GPSFixState.THREE_DIMENSIONAL,
        latitude=latitude,
        longitude=longitude,
        altitude_m=altitude_m,
        satellites=satellites,
        updated_at=updated_at,
    )


@dataclass(frozen=True)
class RmcMovement:
    """Validated movement and UTC data from one supported RMC sentence."""

    speed_m_s: float | None
    heading_degrees: float | None
    utc: datetime | None = None
    fix_valid: bool = False


def parse_rmc_sentence(sentence: str) -> RmcMovement:
    """Parse one checksummed RMC sentence into movement and receiver UTC data."""
    normalized = sentence.strip()
    payload = _validate_checksum(normalized)
    fields = payload.split(",")
    if len(fields) < 10 or fields[0] not in _SUPPORTED_RMC_SENTENCE_TYPES:
        raise GPSParseError("Expected a supported GPRMC or GNRMC sentence.")

    status = fields[2]
    if status not in {"A", "V"}:
        raise GPSParseError("RMC status must be 'A' or 'V'.")

    utc = _parse_rmc_utc(fields[1], fields[9])
    if status == "V":
        return RmcMovement(
            speed_m_s=None,
            heading_degrees=None,
            utc=utc,
            fix_valid=False,
        )

    try:
        speed_m_s = float(fields[7]) * _KNOTS_TO_METRES_PER_SECOND if fields[7] else None
        heading_degrees = float(fields[8]) if fields[8] else None
    except ValueError as error:
        raise GPSParseError("RMC speed or course is invalid.") from error

    if speed_m_s is not None and speed_m_s < 0:
        raise GPSParseError("RMC speed cannot be negative.")
    if heading_degrees is not None and not 0 <= heading_degrees < 360:
        raise GPSParseError("RMC course must be between 0 and 360 degrees.")

    return RmcMovement(
        speed_m_s=speed_m_s,
        heading_degrees=heading_degrees,
        utc=utc,
        fix_valid=True,
    )


class SerialGPSReceiver:
    """GPSReceiver implementation backed by a read-only NMEA serial stream."""

    def __init__(
        self,
        device: Path,
        *,
        baud_rate: int = 9_600,
        timeout_s: float = 2.0,
        maximum_sentences_per_refresh: int = _DEFAULT_MAXIMUM_SENTENCES_PER_REFRESH,
        maximum_utc_age_s: float = _DEFAULT_MAXIMUM_UTC_AGE_S,
        serial_factory: SerialFactory = _open_serial,
        clock: Clock = _utc_now,
        monotonic_clock: MonotonicClock = monotonic,
    ) -> None:
        if not device.is_absolute():
            raise ValueError("GPS serial device must be an absolute path.")
        if baud_rate <= 0:
            raise ValueError("GPS baud rate must be positive.")
        if timeout_s <= 0:
            raise ValueError("GPS timeout must be positive.")
        if maximum_sentences_per_refresh <= 0:
            raise ValueError("Maximum GPS sentences per refresh must be positive.")
        if maximum_utc_age_s <= 0:
            raise ValueError("Maximum GPS UTC age must be positive.")
        self._device = device
        self._baud_rate = baud_rate
        self._timeout_s = timeout_s
        self._maximum_sentences_per_refresh = maximum_sentences_per_refresh
        self._maximum_utc_age_s = maximum_utc_age_s
        self._serial_factory = serial_factory
        self._clock = clock
        self._monotonic_clock = monotonic_clock
        self._port: SerialLinePort | None = None
        self._latest_speed_m_s: float | None = None
        self._latest_heading_degrees: float | None = None
        self._latest_utc_value: datetime | None = None
        self._latest_utc_received_monotonic: float | None = None
        self._latest_utc_source_fix_valid = False
        self._utc_advancing = False
        self._state = GPSState(
            connection_state=GPSConnectionState.DISCONNECTED,
            position=None,
            updated_at=self._clock(),
        )

    def connect(self) -> GPSState:
        """Open the receiver and read its first supported position sentence."""
        if self._port is None or not self._port.is_open:
            self._latest_speed_m_s = None
            self._latest_heading_degrees = None
            self._reset_utc_tracking()
            try:
                self._port = self._serial_factory(
                    self._device,
                    self._baud_rate,
                    self._timeout_s,
                )
            except (OSError, serial.SerialException) as error:
                message = f"Could not open GPS device {self._device}: {error}"
                self._publish_error(message)
                raise GPSConnectionError(message) from error

        try:
            return self.refresh_state()
        except GPSError as error:
            message = f"Could not initialize GPS device {self._device}: {error}"
            self._publish_error(message)
            raise GPSConnectionError(message) from error

    def disconnect(self) -> GPSState:
        """Close the receiver and clear its position snapshot."""
        port = self._port
        self._port = None
        if port is not None:
            try:
                port.close()
            except (OSError, serial.SerialException) as error:
                message = f"Could not close GPS device {self._device}: {error}"
                self._publish_error(message)
                raise GPSConnectionError(message) from error
        self._latest_speed_m_s = None
        self._latest_heading_degrees = None
        self._reset_utc_tracking()
        self._state = GPSState(
            connection_state=GPSConnectionState.DISCONNECTED,
            position=None,
            updated_at=self._clock(),
        )
        return self._state

    def get_state(self) -> GPSState:
        """Return the latest immutable receiver snapshot without performing I/O."""
        return self._state

    def refresh_state(self) -> GPSState:
        """Scan a bounded mixed NMEA stream for the next supported GGA sentence."""
        port = self._port
        if port is None or not port.is_open:
            message = "GPS receiver is not connected."
            self._publish_error(message)
            raise GPSConnectionError(message)

        self._discard_buffered_input(port)

        for _ in range(self._maximum_sentences_per_refresh):
            try:
                raw_sentence = port.readline()
            except (OSError, serial.SerialException) as error:
                self._close_failed_port()
                message = f"Could not read from GPS device {self._device}: {error}"
                self._publish_error(message)
                raise GPSConnectionError(message) from error

            if not raw_sentence:
                message = f"Timed out waiting for NMEA data from GPS device {self._device}."
                self._publish_error(message)
                raise GPSConnectionError(message)

            try:
                sentence = raw_sentence.decode("ascii").strip()
            except UnicodeDecodeError:
                continue

            # Opening a live serial stream can begin in the middle of one sentence.
            # Ignore only incomplete framing fragments; complete NMEA candidates still
            # receive strict checksum validation below.
            if not sentence.startswith("$") or "*" not in sentence:
                continue

            try:
                payload = _validate_checksum(sentence)
                sentence_type = payload.split(",", 1)[0]
                if sentence_type in _SUPPORTED_RMC_SENTENCE_TYPES:
                    movement = parse_rmc_sentence(sentence)
                    self._latest_speed_m_s = movement.speed_m_s
                    self._latest_heading_degrees = movement.heading_degrees
                    self._record_utc_sample(movement)
                    continue
                if sentence_type not in _SUPPORTED_GGA_SENTENCE_TYPES:
                    continue
                position = parse_gga_sentence(sentence, updated_at=self._clock())
                if position.fix_state is not GPSFixState.NO_FIX:
                    position = GPSPosition.model_validate(
                        {
                            **position.model_dump(),
                            "speed_m_s": self._latest_speed_m_s,
                            "heading_degrees": self._latest_heading_degrees,
                        }
                    )
            except GPSParseError as error:
                self._publish_error(str(error))
                raise

            self._state = GPSState(
                connection_state=GPSConnectionState.CONNECTED,
                position=position,
                updated_at=position.updated_at,
                utc=self._build_utc_observation(position),
            )
            return self._state

        message = (
            "Did not receive a supported GPGGA or GNGGA sentence within "
            f"{self._maximum_sentences_per_refresh} NMEA sentences from "
            f"GPS device {self._device}."
        )
        self._publish_error(message)
        raise GPSConnectionError(message)

    def _discard_buffered_input(self, port: SerialLinePort) -> None:
        """Discard queued serial bytes so UTC receipt timing reflects live NMEA data."""
        reset_input_buffer = getattr(port, "reset_input_buffer", None)
        if reset_input_buffer is None:
            return
        try:
            reset_input_buffer()
        except (OSError, serial.SerialException) as error:
            self._close_failed_port()
            message = f"Could not discard buffered GPS data from {self._device}: {error}"
            self._publish_error(message)
            raise GPSConnectionError(message) from error

    def _record_utc_sample(self, movement: RmcMovement) -> None:
        sample = movement.utc
        if sample is None:
            return

        received_at = self._monotonic_clock()
        current = self._latest_utc_value
        if current is None:
            self._latest_utc_value = sample
            self._latest_utc_received_monotonic = received_at
            self._latest_utc_source_fix_valid = movement.fix_valid
            self._utc_advancing = False
            return

        if sample > current:
            self._latest_utc_value = sample
            self._latest_utc_received_monotonic = received_at
            self._latest_utc_source_fix_valid = movement.fix_valid
            self._utc_advancing = True
            return

        if sample == current:
            # A duplicate sentence does not make an old timestamp fresh again.
            self._latest_utc_source_fix_valid = movement.fix_valid
            return

        # A backward UTC sample invalidates the advancing-sequence criterion. Keep the
        # latest newer value so a subsequent sample must actually move beyond it.
        self._latest_utc_source_fix_valid = movement.fix_valid
        self._utc_advancing = False

    def _build_utc_observation(self, position: GPSPosition) -> GPSUTCObservation:
        value = self._latest_utc_value
        received_at = self._latest_utc_received_monotonic
        if value is None or received_at is None:
            return GPSUTCObservation.unavailable()

        age_s = max(0.0, self._monotonic_clock() - received_at)
        return GPSUTCObservation(
            value=value,
            source=GPSUTCSource.RMC,
            valid=True,
            fix_valid=(
                self._latest_utc_source_fix_valid
                and position.fix_state is not GPSFixState.NO_FIX
            ),
            advancing=self._utc_advancing,
            fresh=age_s <= self._maximum_utc_age_s,
            age_s=age_s,
            received_monotonic_s=received_at,
        )

    def _reset_utc_tracking(self) -> None:
        self._latest_utc_value = None
        self._latest_utc_received_monotonic = None
        self._latest_utc_source_fix_valid = False
        self._utc_advancing = False

    def _publish_error(self, message: str) -> GPSState:
        self._state = GPSState(
            connection_state=GPSConnectionState.ERROR,
            position=None,
            updated_at=self._clock(),
            last_error=message,
        )
        return self._state

    def _close_failed_port(self) -> None:
        port = self._port
        self._port = None
        if port is None:
            return
        try:
            port.close()
        except (OSError, serial.SerialException):
            pass
