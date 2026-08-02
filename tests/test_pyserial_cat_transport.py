"""Tests for the pyserial CAT transport."""

from pathlib import Path
import termios

import pytest

from rolling_thunder.pyserial_cat_transport import PySerialCatTransport
from rolling_thunder.radio import RadioConnectionError


class FakeSerialPort:
    def __init__(self, reply: bytes = b"") -> None:
        self._reply = bytearray(reply)
        self.is_open = True
        self.writes: list[bytes] = []
        self.reset_count = 0
        self.reset_error: BaseException | None = None
        self.write_size: int | None = None

    def close(self) -> None:
        self.is_open = False

    def read(self, size: int = 1) -> bytes:
        if not self._reply:
            return b""
        result = bytes(self._reply[:size])
        del self._reply[:size]
        return result

    def write(self, data: bytes) -> int:
        self.writes.append(data)
        return len(data) if self.write_size is None else self.write_size

    def reset_input_buffer(self) -> None:
        self.reset_count += 1
        if self.reset_error is not None:
            raise self.reset_error


def test_query_reads_through_semicolon() -> None:
    port = FakeSerialPort(b"FA014250000;")
    transport = PySerialCatTransport(
        Path("/dev/ttyUSB0"),
        serial_factory=lambda _device, _baud, _timeout: port,
    )
    transport.open()

    reply = transport.query(b"FA;")

    assert reply == b"FA014250000;"
    assert port.writes == [b"FA;"]
    assert port.reset_count == 1


def test_query_reports_timeout() -> None:
    port = FakeSerialPort()
    transport = PySerialCatTransport(
        Path("/dev/ttyUSB0"),
        serial_factory=lambda _device, _baud, _timeout: port,
    )
    transport.open()

    with pytest.raises(RadioConnectionError, match="Timed out"):
        transport.query(b"FA;")


def test_query_normalizes_termios_disconnect_error() -> None:
    port = FakeSerialPort()
    port.reset_error = termios.error(5, "Input/output error")
    transport = PySerialCatTransport(
        Path("/dev/ttyUSB0"),
        serial_factory=lambda _device, _baud, _timeout: port,
    )
    transport.open()

    with pytest.raises(
        RadioConnectionError,
        match="Could not write to FT-891 CAT device.*Input/output error",
    ):
        transport.query(b"FA;")


def test_query_rejects_unterminated_oversized_reply() -> None:
    port = FakeSerialPort(b"12345678")
    transport = PySerialCatTransport(
        Path("/dev/ttyUSB0"),
        maximum_reply_bytes=8,
        serial_factory=lambda _device, _baud, _timeout: port,
    )
    transport.open()

    with pytest.raises(RadioConnectionError, match="exceeded 8 bytes"):
        transport.query(b"FA;")


def test_command_requires_open_transport() -> None:
    transport = PySerialCatTransport(Path("/dev/ttyUSB0"))

    with pytest.raises(RadioConnectionError, match="not open"):
        transport.command(b"MD01;")


def test_command_rejects_partial_write() -> None:
    port = FakeSerialPort()
    port.write_size = 2
    transport = PySerialCatTransport(
        Path("/dev/ttyUSB0"),
        serial_factory=lambda _device, _baud, _timeout: port,
    )
    transport.open()

    with pytest.raises(RadioConnectionError, match="Incomplete"):
        transport.command(b"MD01;")


def test_transport_validates_device_and_command() -> None:
    with pytest.raises(ValueError, match="absolute path"):
        PySerialCatTransport(Path("ttyUSB0"))

    port = FakeSerialPort()
    transport = PySerialCatTransport(
        Path("/dev/ttyUSB0"),
        serial_factory=lambda _device, _baud, _timeout: port,
    )
    transport.open()

    with pytest.raises(ValueError, match="semicolon-terminated"):
        transport.command(b"FA")
