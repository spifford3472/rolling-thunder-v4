"""Tests for the read-only serial NMEA GPS adapter."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from rolling_thunder.domain import GPSFixState
from rolling_thunder.gps import GPSConnectionError, GPSConnectionState
from rolling_thunder.serial_gps import GPSParseError, SerialGPSReceiver, parse_gga_sentence

_FIXED_TIME = datetime(2026, 7, 26, 14, 30, tzinfo=UTC)


def _sentence(payload: str) -> str:
    checksum = 0
    for character in payload:
        checksum ^= ord(character)
    return f"${payload}*{checksum:02X}\r\n"


class FakeSerialPort:
    def __init__(self, replies: list[bytes], *, is_open: bool = True) -> None:
        self.replies = replies
        self._is_open = is_open
        self.closed = False

    @property
    def is_open(self) -> bool:
        return self._is_open

    def close(self) -> None:
        self.closed = True
        self._is_open = False

    def readline(self) -> bytes:
        if not self.replies:
            return b""
        return self.replies.pop(0)


def test_parse_valid_gga_fix() -> None:
    position = parse_gga_sentence(
        "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47",
        updated_at=_FIXED_TIME,
    )

    assert position.fix_state is GPSFixState.THREE_DIMENSIONAL
    assert position.latitude == pytest.approx(48.1173)
    assert position.longitude == pytest.approx(11.5166667)
    assert position.altitude_m == pytest.approx(545.4)
    assert position.satellites == 8
    assert position.updated_at == _FIXED_TIME


def test_parse_southern_western_coordinates() -> None:
    sentence = _sentence(
        "GNGGA,123519,3351.000,S,15112.000,W,1,10,0.8,12.5,M,0.0,M,,"
    )

    position = parse_gga_sentence(sentence, updated_at=_FIXED_TIME)

    assert position.latitude == pytest.approx(-33.85)
    assert position.longitude == pytest.approx(-151.2)


def test_parse_no_fix_clears_coordinates() -> None:
    sentence = _sentence("GPGGA,123519,,,,,0,00,99.9,,,,,,")

    position = parse_gga_sentence(sentence, updated_at=_FIXED_TIME)

    assert position.fix_state is GPSFixState.NO_FIX
    assert position.latitude is None
    assert position.longitude is None
    assert position.altitude_m is None
    assert position.satellites == 0


def test_parse_rejects_checksum_mismatch() -> None:
    with pytest.raises(GPSParseError, match="checksum mismatch"):
        parse_gga_sentence(
            "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*00",
            updated_at=_FIXED_TIME,
        )


def test_parse_rejects_unsupported_sentence() -> None:
    sentence = _sentence("GPRMC,123519,A,4807.038,N,01131.000,E,0.0,0.0,230394,,")

    with pytest.raises(GPSParseError, match="GPGGA or GNGGA"):
        parse_gga_sentence(sentence, updated_at=_FIXED_TIME)


def test_parse_rejects_valid_fix_without_altitude() -> None:
    sentence = _sentence("GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,,M,46.9,M,,")

    with pytest.raises(GPSParseError, match="must include altitude"):
        parse_gga_sentence(sentence, updated_at=_FIXED_TIME)


def test_receiver_connects_reads_and_disconnects() -> None:
    sentence = _sentence(
        "GNGGA,123519,3931.854,N,08405.196,W,1,09,0.8,262.0,M,0.0,M,,"
    )
    port = FakeSerialPort([sentence.encode("ascii")])
    observed: list[tuple[Path, int, float]] = []

    def factory(device: Path, baud_rate: int, timeout_s: float) -> FakeSerialPort:
        observed.append((device, baud_rate, timeout_s))
        return port

    receiver = SerialGPSReceiver(
        Path("/dev/ttyUSB1"),
        serial_factory=factory,
        clock=lambda: _FIXED_TIME,
    )

    connected = receiver.connect()

    assert observed == [(Path("/dev/ttyUSB1"), 9_600, 2.0)]
    assert connected.connection_state is GPSConnectionState.CONNECTED
    assert connected.position is not None
    assert connected.position.latitude == pytest.approx(39.5309)
    assert connected.position.longitude == pytest.approx(-84.0866)
    assert receiver.get_state() is connected

    disconnected = receiver.disconnect()

    assert port.closed is True
    assert disconnected.connection_state is GPSConnectionState.DISCONNECTED
    assert disconnected.position is None


def test_receiver_rejects_refresh_before_connect() -> None:
    receiver = SerialGPSReceiver(
        Path("/dev/ttyUSB1"),
        serial_factory=lambda _device, _baud, _timeout: FakeSerialPort([]),
        clock=lambda: _FIXED_TIME,
    )

    with pytest.raises(GPSConnectionError, match="not connected"):
        receiver.refresh_state()


def test_receiver_reports_timeout_during_connect() -> None:
    receiver = SerialGPSReceiver(
        Path("/dev/ttyUSB1"),
        serial_factory=lambda _device, _baud, _timeout: FakeSerialPort([]),
        clock=lambda: _FIXED_TIME,
    )

    with pytest.raises(GPSConnectionError, match="Timed out waiting for NMEA data"):
        receiver.connect()

    state = receiver.get_state()
    assert state.connection_state is GPSConnectionState.ERROR
    assert state.last_error is not None
    assert "/dev/ttyUSB1" in state.last_error


def test_receiver_reports_non_ascii_input() -> None:
    receiver = SerialGPSReceiver(
        Path("/dev/ttyUSB1"),
        serial_factory=lambda _device, _baud, _timeout: FakeSerialPort([b"\xff\n"]),
        clock=lambda: _FIXED_TIME,
    )

    with pytest.raises(GPSConnectionError, match="not ASCII"):
        receiver.connect()


def test_receiver_requires_absolute_device_path() -> None:
    with pytest.raises(ValueError, match="absolute path"):
        SerialGPSReceiver(Path("ttyUSB1"))


def test_receiver_validates_serial_settings() -> None:
    with pytest.raises(ValueError, match="baud rate"):
        SerialGPSReceiver(Path("/dev/ttyUSB1"), baud_rate=0)
    with pytest.raises(ValueError, match="timeout"):
        SerialGPSReceiver(Path("/dev/ttyUSB1"), timeout_s=0)
