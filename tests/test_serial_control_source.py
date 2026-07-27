"""Tests for the nonblocking ESP32 serial control source."""

from collections import deque
from pathlib import Path

import pytest
import serial

from rolling_thunder.serial_control_source import (
    SerialControlError,
    SerialControlSource,
)


class FakeSerialPort:
    def __init__(self, chunks: tuple[bytes, ...] = ()) -> None:
        self.is_open = True
        self._chunks = deque(chunks)
        self.closed = False
        self.read_error: Exception | None = None
        self.close_error: Exception | None = None

    @property
    def in_waiting(self) -> int:
        if self.read_error is not None:
            raise self.read_error
        return len(self._chunks[0]) if self._chunks else 0

    def read(self, size: int = 1) -> bytes:
        if self.read_error is not None:
            raise self.read_error
        if not self._chunks:
            return b""
        chunk = self._chunks.popleft()
        if len(chunk) <= size:
            return chunk
        self._chunks.appendleft(chunk[size:])
        return chunk[:size]

    def close(self) -> None:
        if self.close_error is not None:
            raise self.close_error
        self.closed = True
        self.is_open = False


def make_source(
    port: FakeSerialPort,
    **kwargs: object,
) -> SerialControlSource:
    return SerialControlSource(
        Path("/dev/ttyACM0"),
        serial_factory=lambda _device, _baud_rate: port,
        **kwargs,
    )


def test_open_uses_configured_device_and_baud_rate() -> None:
    calls: list[tuple[Path, int]] = []
    port = FakeSerialPort()

    source = SerialControlSource(
        Path("/dev/ttyUSB7"),
        baud_rate=230_400,
        serial_factory=lambda device, baud_rate: (
            calls.append((device, baud_rate)) or port
        ),
    )

    source.open()

    assert calls == [(Path("/dev/ttyUSB7"), 230_400)]
    assert source.is_connected is True
    assert source.last_error is None


def test_open_is_idempotent_while_connected() -> None:
    calls: list[None] = []
    port = FakeSerialPort()
    source = SerialControlSource(
        Path("/dev/ttyACM0"),
        serial_factory=lambda _device, _baud_rate: (
            calls.append(None) or port
        ),
    )

    source.open()
    source.open()

    assert calls == [None]


def test_drain_returns_complete_valid_events_without_blocking() -> None:
    port = FakeSerialPort(
        (
            b"RTCTRL/1 EVENT voice-button boot-1 1.250\n"
            b"RTCTRL/1 EVENT commit-button boot-2 2.500\n",
        )
    )
    source = make_source(port)
    source.open()

    events = source.drain()

    assert [(event.input_id, event.event_id, event.occurred_at_s) for event in events] == [
        ("voice-button", "boot-1", 1.25),
        ("commit-button", "boot-2", 2.5),
    ]


def test_drain_preserves_partial_line_until_completed() -> None:
    port = FakeSerialPort((b"RTCTRL/1 EVENT voice-button boot-1 ", b"3.750\n"))
    source = make_source(port)
    source.open()

    assert source.drain() == ()
    events = source.drain()

    assert len(events) == 1
    assert events[0].input_id == "voice-button"
    assert events[0].occurred_at_s == 3.75


def test_malformed_line_is_rejected_and_later_valid_line_survives() -> None:
    port = FakeSerialPort(
        (
            b"RTCTRL/1 ACTION commit boot-1 1.0\n"
            b"RTCTRL/1 EVENT discard-button boot-2 2.0\n",
        )
    )
    source = make_source(port)
    source.open()

    events = source.drain()

    assert len(events) == 1
    assert events[0].input_id == "discard-button"
    assert source.last_error is not None
    assert "message type" in source.last_error


def test_drain_is_bounded_by_event_limit() -> None:
    port = FakeSerialPort(
        (
            b"RTCTRL/1 EVENT one e1 1\n"
            b"RTCTRL/1 EVENT two e2 2\n"
            b"RTCTRL/1 EVENT three e3 3\n",
        )
    )
    source = make_source(port, maximum_events_per_drain=2)
    source.open()

    first = source.drain()
    second = source.drain()

    assert [event.input_id for event in first] == ["one", "two"]
    assert [event.input_id for event in second] == ["three"]


def test_drain_is_bounded_by_read_limit() -> None:
    line = b"RTCTRL/1 EVENT voice-button boot-1 1.0\n"
    port = FakeSerialPort((line,))
    source = make_source(port, maximum_read_bytes=10)
    source.open()

    assert source.drain() == ()
    assert source.drain() == ()


def test_oversized_incomplete_line_is_discarded() -> None:
    port = FakeSerialPort((b"X" * 20,))
    source = make_source(port, maximum_line_bytes=10)
    source.open()

    assert source.drain() == ()
    assert source.last_error == "Incomplete ESP32 control line exceeded the 10-byte limit."


def test_read_error_disconnects_and_fails_closed() -> None:
    port = FakeSerialPort()
    source = make_source(port)
    source.open()
    port.read_error = serial.SerialException("device removed")

    assert source.drain() == ()
    assert source.is_connected is False
    assert port.closed is True
    assert source.last_error is not None
    assert "device removed" in source.last_error


def test_close_discards_partial_data() -> None:
    port = FakeSerialPort((b"RTCTRL/1 EVENT voice-button boot-1 ",))
    source = make_source(port)
    source.open()
    assert source.drain() == ()

    source.close()

    assert source.is_connected is False
    assert port.closed is True


def test_open_error_is_actionable() -> None:
    def fail_open(_device: Path, _baud_rate: int) -> FakeSerialPort:
        raise serial.SerialException("permission denied")

    source = SerialControlSource(
        Path("/dev/ttyACM0"),
        serial_factory=fail_open,
    )

    with pytest.raises(SerialControlError, match="permission denied"):
        source.open()

    assert source.is_connected is False


def test_close_error_is_actionable() -> None:
    port = FakeSerialPort()
    source = make_source(port)
    source.open()
    port.close_error = serial.SerialException("close failed")

    with pytest.raises(SerialControlError, match="close failed"):
        source.close()

    assert source.is_connected is False


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"device": Path("ttyACM0")}, "absolute path"),
        ({"baud_rate": 0}, "baud rate"),
        ({"maximum_line_bytes": 0}, "maximum_line_bytes"),
        ({"maximum_read_bytes": 0}, "maximum_read_bytes"),
        ({"maximum_events_per_drain": 0}, "maximum_events_per_drain"),
    ],
)
def test_invalid_configuration_is_rejected(
    kwargs: dict[str, object],
    message: str,
) -> None:
    device = kwargs.pop("device", Path("/dev/ttyACM0"))

    with pytest.raises(ValueError, match=message):
        SerialControlSource(device, **kwargs)  # type: ignore[arg-type]
