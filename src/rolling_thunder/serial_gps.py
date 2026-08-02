"""Read-only serial GPS adapter for NMEA GGA position sentences."""

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, cast

import serial

from rolling_thunder.domain import GPSFixState, GPSPosition
from rolling_thunder.gps import GPSConnectionError, GPSConnectionState, GPSError, GPSState


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
_SUPPORTED_GGA_SENTENCE_TYPES = frozenset({"GPGGA", "GNGGA"})
_DEFAULT_MAXIMUM_SENTENCES_PER_REFRESH = 32


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


class SerialGPSReceiver:
    """GPSReceiver implementation backed by a read-only NMEA serial stream."""

    def __init__(
        self,
        device: Path,
        *,
        baud_rate: int = 9_600,
        timeout_s: float = 2.0,
        maximum_sentences_per_refresh: int = _DEFAULT_MAXIMUM_SENTENCES_PER_REFRESH,
        serial_factory: SerialFactory = _open_serial,
        clock: Clock = _utc_now,
    ) -> None:
        if not device.is_absolute():
            raise ValueError("GPS serial device must be an absolute path.")
        if baud_rate <= 0:
            raise ValueError("GPS baud rate must be positive.")
        if timeout_s <= 0:
            raise ValueError("GPS timeout must be positive.")
        if maximum_sentences_per_refresh <= 0:
            raise ValueError("Maximum GPS sentences per refresh must be positive.")
        self._device = device
        self._baud_rate = baud_rate
        self._timeout_s = timeout_s
        self._maximum_sentences_per_refresh = maximum_sentences_per_refresh
        self._serial_factory = serial_factory
        self._clock = clock
        self._port: SerialLinePort | None = None
        self._state = GPSState(
            connection_state=GPSConnectionState.DISCONNECTED,
            position=None,
            updated_at=self._clock(),
        )

    def connect(self) -> GPSState:
        """Open the receiver and read its first supported position sentence."""
        if self._port is None or not self._port.is_open:
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
                if sentence_type not in _SUPPORTED_GGA_SENTENCE_TYPES:
                    continue
                position = parse_gga_sentence(sentence, updated_at=self._clock())
            except GPSParseError as error:
                self._publish_error(str(error))
                raise

            self._state = GPSState(
                connection_state=GPSConnectionState.CONNECTED,
                position=position,
                updated_at=position.updated_at,
            )
            return self._state

        message = (
            "Did not receive a supported GPGGA or GNGGA sentence within "
            f"{self._maximum_sentences_per_refresh} NMEA sentences from "
            f"GPS device {self._device}."
        )
        self._publish_error(message)
        raise GPSConnectionError(message)

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
