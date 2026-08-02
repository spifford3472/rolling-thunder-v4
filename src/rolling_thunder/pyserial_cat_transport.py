"""PySerial implementation of the CAT transport boundary."""

import termios
from collections.abc import Callable
from pathlib import Path
from typing import Protocol, cast

import serial

from rolling_thunder.radio import RadioConnectionError


class SerialPort(Protocol):
    """Minimal serial-port surface required by the CAT transport."""

    @property
    def is_open(self) -> bool:
        """Return whether the port is open."""
        ...

    def close(self) -> None:
        """Close the serial port."""
        ...

    def read(self, size: int = 1) -> bytes:
        """Read up to size bytes."""
        ...

    def write(self, data: bytes) -> int:
        """Write bytes and return the number accepted."""
        ...

    def reset_input_buffer(self) -> None:
        """Discard unread inbound data."""
        ...


SerialFactory = Callable[[Path, int, float], SerialPort]


def _open_serial(device: Path, baud_rate: int, timeout_s: float) -> SerialPort:
    """Open a pyserial port using FT-891 CAT framing."""
    port = serial.Serial(
        port=str(device),
        baudrate=baud_rate,
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_TWO,
        timeout=timeout_s,
        write_timeout=timeout_s,
    )
    return cast(SerialPort, port)


class PySerialCatTransport:
    """Semicolon-terminated CAT transport backed by pyserial."""

    def __init__(
        self,
        device: Path,
        *,
        baud_rate: int = 38_400,
        timeout_s: float = 1.0,
        maximum_reply_bytes: int = 64,
        serial_factory: SerialFactory = _open_serial,
    ) -> None:
        if not device.is_absolute():
            raise ValueError("CAT serial device must be an absolute path.")
        if baud_rate <= 0:
            raise ValueError("CAT baud rate must be positive.")
        if timeout_s <= 0:
            raise ValueError("CAT timeout must be positive.")
        if maximum_reply_bytes < 2:
            raise ValueError("CAT maximum reply length must be at least 2 bytes.")

        self._device = device
        self._baud_rate = baud_rate
        self._timeout_s = timeout_s
        self._maximum_reply_bytes = maximum_reply_bytes
        self._serial_factory = serial_factory
        self._port: SerialPort | None = None

    def open(self) -> None:
        """Open the configured serial device."""
        if self._port is not None and self._port.is_open:
            return
        try:
            self._port = self._serial_factory(
                self._device,
                self._baud_rate,
                self._timeout_s,
            )
        except (OSError, serial.SerialException, termios.error) as error:
            raise RadioConnectionError(
                f"Could not open FT-891 CAT device {self._device}: {error}"
            ) from error

    def close(self) -> None:
        """Close the serial device if open."""
        port = self._port
        self._port = None
        if port is None:
            return
        try:
            port.close()
        except (OSError, serial.SerialException, termios.error) as error:
            raise RadioConnectionError(
                f"Could not close FT-891 CAT device {self._device}: {error}"
            ) from error

    def query(self, command: bytes) -> bytes:
        """Write one read command and return one complete semicolon reply."""
        port = self._require_open()
        self._write(port, command)
        reply = bytearray()
        try:
            while len(reply) < self._maximum_reply_bytes:
                chunk = port.read(1)
                if not chunk:
                    raise RadioConnectionError(
                        f"Timed out waiting for FT-891 CAT reply to {command!r}."
                    )
                reply.extend(chunk)
                if chunk == b";":
                    return bytes(reply)
        except RadioConnectionError:
            raise
        except (OSError, serial.SerialException, termios.error) as error:
            raise RadioConnectionError(
                f"Could not read from FT-891 CAT device {self._device}: {error}"
            ) from error

        raise RadioConnectionError(
            "FT-891 CAT reply exceeded "
            f"{self._maximum_reply_bytes} bytes without a terminator."
        )

    def command(self, command: bytes) -> None:
        """Write one set command."""
        self._write(self._require_open(), command)

    def _require_open(self) -> SerialPort:
        port = self._port
        if port is None or not port.is_open:
            raise RadioConnectionError("FT-891 CAT transport is not open.")
        return port

    def _write(self, port: SerialPort, command: bytes) -> None:
        if not isinstance(command, bytes) or not command.endswith(b";"):
            raise ValueError("CAT command must be semicolon-terminated bytes.")
        try:
            port.reset_input_buffer()
            written = port.write(command)
        except (OSError, serial.SerialException, termios.error) as error:
            raise RadioConnectionError(
                f"Could not write to FT-891 CAT device {self._device}: {error}"
            ) from error
        if written != len(command):
            raise RadioConnectionError(
                "Incomplete FT-891 CAT write: "
                f"expected {len(command)} bytes, wrote {written}."
            )
