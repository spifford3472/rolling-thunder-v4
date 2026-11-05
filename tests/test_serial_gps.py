"""Tests for the read-only serial NMEA GPS adapter."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
import serial

from rolling_thunder.domain import GPSFixState
from rolling_thunder.gps import GPSConnectionError, GPSConnectionState
from rolling_thunder.serial_gps import (
    GPSParseError,
    SerialGPSReceiver,
    parse_gga_sentence,
    parse_rmc_sentence,
)

_FIXED_TIME = datetime(2026, 7, 26, 14, 30, tzinfo=UTC)


def _sentence(payload: str) -> str:
    checksum = 0
    for character in payload:
        checksum ^= ord(character)
    return f"${payload}*{checksum:02X}\r\n"


class FakeSerialPort:
    def __init__(
        self,
        replies: list[bytes | BaseException],
        *,
        is_open: bool = True,
    ) -> None:
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
        reply = self.replies.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        return reply


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
    sentence = _sentence("GNGGA,123519,3351.000,S,15112.000,W,1,10,0.8,12.5,M,0.0,M,,")

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


def test_parse_valid_rmc_movement() -> None:
    movement = parse_rmc_sentence(
        _sentence("GNRMC,131645.000,A,3931.4668,N,08403.7491,W,12.5,87.3,020826,,,D")
    )

    assert movement.speed_m_s == pytest.approx(6.43055)
    assert movement.heading_degrees == pytest.approx(87.3)


def test_parse_void_rmc_clears_movement() -> None:
    movement = parse_rmc_sentence(_sentence("GNRMC,131645.000,V,,,,,,,020826,,,N"))

    assert movement.speed_m_s is None
    assert movement.heading_degrees is None


def test_parse_rejects_valid_fix_without_altitude() -> None:
    sentence = _sentence("GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,,M,46.9,M,,")

    with pytest.raises(GPSParseError, match="must include altitude"):
        parse_gga_sentence(sentence, updated_at=_FIXED_TIME)


def test_receiver_connects_reads_and_disconnects() -> None:
    sentence = _sentence("GNGGA,123519,3931.854,N,08405.196,W,1,09,0.8,262.0,M,0.0,M,,")
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


def test_receiver_skips_live_stream_sentences_until_gga() -> None:
    gga = _sentence("GNGGA,131645.000,3931.4668,N,08403.7491,W,2,15,0.68,271.6,M,-33.3,M,,")
    replies = [
        _sentence("GNRMC,131645.000,A,3931.4668,N,08403.7491,W,0.07,0.00,020826,,,D").encode(
            "ascii"
        ),
        _sentence("GPGSA,A,3,21,11,05,20,25,15,12,06,18,,,,0.97,0.68,0.68").encode("ascii"),
        gga.encode("ascii"),
    ]
    receiver = SerialGPSReceiver(
        Path("/dev/ttyUSB3"),
        serial_factory=lambda _device, _baud, _timeout: FakeSerialPort(replies),
        clock=lambda: _FIXED_TIME,
    )

    state = receiver.connect()

    assert state.connection_state is GPSConnectionState.CONNECTED
    assert state.position is not None
    assert state.position.latitude == pytest.approx(39.5244467)
    assert state.position.longitude == pytest.approx(-84.062485)
    assert state.position.satellites == 15
    assert state.position.speed_m_s == pytest.approx(0.03601108)
    assert state.position.heading_degrees == pytest.approx(0.0)


def test_receiver_skips_truncated_and_non_ascii_startup_fragments() -> None:
    gga = _sentence("GNGGA,131646.000,3931.4668,N,08403.7492,W,2,15,0.68,271.6,M,-33.3,M,,")
    receiver = SerialGPSReceiver(
        Path("/dev/ttyUSB3"),
        serial_factory=lambda _device, _baud, _timeout: FakeSerialPort(
            [b"1644.000,1,1.53,-1.81,*53\r\n", b"\xff\n", gga.encode("ascii")]
        ),
        clock=lambda: _FIXED_TIME,
    )

    state = receiver.connect()

    assert state.connection_state is GPSConnectionState.CONNECTED
    assert state.position is not None
    assert state.position.longitude == pytest.approx(-84.0624867)


def test_receiver_rejects_bad_checksum_in_unsupported_sentence() -> None:
    first_gga = _sentence("GNGGA,131645.000,3931.4668,N,08403.7491,W,2,15,0.68,271.6,M,-33.3,M,,")
    port = FakeSerialPort(
        [
            first_gga.encode("ascii"),
            b"$GNRMC,131646.000,A,3931.4668,N,08403.7492,W,0.03,0.00,020826,,,D*00\r\n",
        ]
    )
    receiver = SerialGPSReceiver(
        Path("/dev/ttyUSB3"),
        serial_factory=lambda _device, _baud, _timeout: port,
        clock=lambda: _FIXED_TIME,
    )
    receiver.connect()

    with pytest.raises(GPSParseError, match="checksum mismatch"):
        receiver.refresh_state()

    assert receiver.get_state().connection_state is GPSConnectionState.ERROR


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


def test_receiver_reports_missing_gga_within_bounded_scan() -> None:
    receiver = SerialGPSReceiver(
        Path("/dev/ttyUSB3"),
        maximum_sentences_per_refresh=2,
        serial_factory=lambda _device, _baud, _timeout: FakeSerialPort(
            [
                _sentence("GNRMC,131645.000,A,,,,,,,020826,,,N").encode("ascii"),
                _sentence("GNZDA,131645.000,02,08,2026,,").encode("ascii"),
            ]
        ),
        clock=lambda: _FIXED_TIME,
    )

    with pytest.raises(GPSConnectionError, match="within 2 NMEA sentences"):
        receiver.connect()


def test_receiver_reopens_after_physical_disconnect() -> None:
    first_gga = _sentence("GNGGA,131645.000,3931.4668,N,08403.7491,W,2,15,0.68,271.6,M,-33.3,M,,")
    recovered_gga = _sentence(
        "GNGGA,131700.000,3931.5000,N,08403.7000,W,2,14,0.75,272.0,M,-33.3,M,,"
    )
    first_port = FakeSerialPort(
        [first_gga.encode("ascii"), serial.SerialException("device disconnected")]
    )
    recovered_port = FakeSerialPort([recovered_gga.encode("ascii")])
    ports = iter([first_port, recovered_port])

    receiver = SerialGPSReceiver(
        Path("/dev/serial/by-id/gps"),
        serial_factory=lambda _device, _baud, _timeout: next(ports),
        clock=lambda: _FIXED_TIME,
    )
    receiver.connect()

    with pytest.raises(GPSConnectionError, match="device disconnected"):
        receiver.refresh_state()

    assert first_port.closed is True
    assert receiver.get_state().connection_state is GPSConnectionState.ERROR

    recovered = receiver.connect()

    assert recovered.connection_state is GPSConnectionState.CONNECTED
    assert recovered.position is not None
    assert recovered.position.latitude == pytest.approx(39.525)
    assert recovered.position.longitude == pytest.approx(-84.0616667)


def test_receiver_requires_absolute_device_path() -> None:
    with pytest.raises(ValueError, match="absolute path"):
        SerialGPSReceiver(Path("ttyUSB1"))


def test_receiver_validates_serial_settings() -> None:
    with pytest.raises(ValueError, match="baud rate"):
        SerialGPSReceiver(Path("/dev/ttyUSB1"), baud_rate=0)
    with pytest.raises(ValueError, match="timeout"):
        SerialGPSReceiver(Path("/dev/ttyUSB1"), timeout_s=0)
    with pytest.raises(ValueError, match="sentences per refresh"):
        SerialGPSReceiver(Path("/dev/ttyUSB1"), maximum_sentences_per_refresh=0)


def test_gga_hdop_supplies_conservative_county_uncertainty() -> None:
    sentence = _sentence("GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,")
    position = parse_gga_sentence(sentence, updated_at=_FIXED_TIME)
    assert position.accuracy_m == 100.0


def test_gga_missing_hdop_keeps_county_uncertainty_unknown() -> None:
    sentence = _sentence("GPGGA,123519,4807.038,N,01131.000,E,1,08,,545.4,M,46.9,M,,")
    position = parse_gga_sentence(sentence, updated_at=_FIXED_TIME)
    assert position.accuracy_m is None


def test_gga_invalid_hdop_rejected() -> None:
    sentence = _sentence("GPGGA,123519,4807.038,N,01131.000,E,1,08,nan,545.4,M,46.9,M,,")
    with pytest.raises(GPSParseError):
        parse_gga_sentence(sentence, updated_at=_FIXED_TIME)
