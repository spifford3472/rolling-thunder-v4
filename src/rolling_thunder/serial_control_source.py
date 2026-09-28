"""Nonblocking pyserial source for versioned ESP32 control events."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol, cast

import serial

from rolling_thunder.control_protocol import (
    ControlProtocolError,
    parse_control_event_line,
)
from rolling_thunder.physical_controls import ControlInputEvent


class SerialControlError(RuntimeError):
    """Raised when the ESP32 control serial transport cannot operate safely."""


class ControlSerialPort(Protocol):
    """Minimal nonblocking serial surface required by the control source."""

    @property
    def is_open(self) -> bool:
        """Return whether the serial port is open."""

    @property
    def in_waiting(self) -> int:
        """Return the number of bytes currently available without blocking."""

    def close(self) -> None:
        """Close the serial port."""

    def read(self, size: int = 1) -> bytes:
        """Read up to size currently available bytes."""


SerialFactory = Callable[[Path, int], ControlSerialPort]


def _open_serial(device: Path, baud_rate: int) -> ControlSerialPort:
    """Open a conventional 8-N-1 serial device in nonblocking mode."""
    port = serial.Serial(
        port=str(device),
        baudrate=baud_rate,
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        timeout=0,
    )
    return cast(ControlSerialPort, port)


class SerialControlSource:
    """Drain complete RTCTRL event lines from a nonblocking serial stream."""

    def __init__(
        self,
        device: Path,
        *,
        baud_rate: int = 115_200,
        maximum_line_bytes: int = 256,
        maximum_read_bytes: int = 4_096,
        maximum_events_per_drain: int = 32,
        serial_factory: SerialFactory = _open_serial,
    ) -> None:
        if not device.is_absolute():
            raise ValueError("Control serial device must be an absolute path.")
        if baud_rate <= 0:
            raise ValueError("Control serial baud rate must be positive.")
        if maximum_line_bytes < 1:
            raise ValueError("Control maximum_line_bytes must be positive.")
        if maximum_read_bytes < 1:
            raise ValueError("Control maximum_read_bytes must be positive.")
        if maximum_events_per_drain < 1:
            raise ValueError("Control maximum_events_per_drain must be positive.")

        self._device = device
        self._baud_rate = baud_rate
        self._maximum_line_bytes = maximum_line_bytes
        self._maximum_read_bytes = maximum_read_bytes
        self._maximum_events_per_drain = maximum_events_per_drain
        self._serial_factory = serial_factory
        self._port: ControlSerialPort | None = None
        self._buffer = bytearray()
        self._last_error: str | None = None

    @property
    def is_connected(self) -> bool:
        """Return whether a serial port is currently open."""
        return self._port is not None and self._port.is_open

    @property
    def last_error(self) -> str | None:
        """Return the latest rejected-line or transport error message."""
        return self._last_error

    def open(self) -> None:
        """Open the configured serial device without reading from it."""
        if self.is_connected:
            return
        try:
            self._port = self._serial_factory(self._device, self._baud_rate)
        except (OSError, serial.SerialException) as error:
            self._port = None
            self._last_error = (
                f"Could not open ESP32 control device {self._device}: {error}"
            )
            raise SerialControlError(self._last_error) from error
        self._buffer.clear()
        self._last_error = None

    def close(self) -> None:
        """Close the serial device and discard any incomplete message."""
        port = self._port
        self._port = None
        self._buffer.clear()
        if port is None:
            return
        try:
            port.close()
        except (OSError, serial.SerialException) as error:
            self._last_error = (
                f"Could not close ESP32 control device {self._device}: {error}"
            )
            raise SerialControlError(self._last_error) from error

    def drain(self) -> tuple[ControlInputEvent, ...]:
        """Return currently available valid events without blocking."""
        port = self._port
        if port is None or not port.is_open:
            return ()

        try:
            available = max(0, port.in_waiting)
            read_size = min(available, self._maximum_read_bytes)
            if read_size:
                self._buffer.extend(port.read(read_size))
        except (OSError, serial.SerialException) as error:
            self._disconnect_after_error(
                f"Could not read ESP32 control device {self._device}: {error}"
            )
            return ()

        events: list[ControlInputEvent] = []
        while len(events) < self._maximum_events_per_drain:
            newline_index = self._buffer.find(b"\n")
            if newline_index < 0:
                break
            raw_line = bytes(self._buffer[: newline_index + 1])
            del self._buffer[: newline_index + 1]
            try:
                events.append(
                    parse_control_event_line(
                        raw_line,
                        maximum_line_bytes=self._maximum_line_bytes,
                    )
                )
            except ControlProtocolError as error:
                self._last_error = str(error)

        if len(self._buffer) > self._maximum_line_bytes:
            self._buffer.clear()
            self._last_error = (
                "Incomplete ESP32 control line exceeded "
                f"the {self._maximum_line_bytes}-byte limit."
            )

        return tuple(events)

    def _disconnect_after_error(self, message: str) -> None:
        port = self._port
        self._port = None
        self._buffer.clear()
        self._last_error = message
        if port is not None:
            try:
                port.close()
            except (OSError, serial.SerialException):
                pass
