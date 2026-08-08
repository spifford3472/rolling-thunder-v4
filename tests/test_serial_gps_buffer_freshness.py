"""Tests that physical GPS refreshes do not timestamp queued NMEA as fresh."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
import serial

from rolling_thunder.gps import GPSConnectionState
from rolling_thunder.serial_gps import GPSConnectionError, SerialGPSReceiver

_FIXED_TIME = datetime(2026, 8, 8, 23, 9, 30, tzinfo=UTC)


def _sentence(payload: str) -> bytes:
    checksum = 0
    for character in payload:
        checksum ^= ord(character)
    return f"${payload}*{checksum:02X}\r\n".encode("ascii")


def _rmc(second: int) -> bytes:
    return _sentence(
        f"GNRMC,2309{second:02d}.000,A,3931.4668,N,08403.7491,W,"
        "0.07,0.00,080826,,,D"
    )


def _gga(second: int) -> bytes:
    return _sentence(
        f"GNGGA,2309{second:02d}.000,3931.4668,N,08403.7491,W,"
        "2,15,0.68,271.6,M,-33.3,M,,"
    )


class BufferedSerialPort:
    def __init__(self, stale: list[bytes], live: list[bytes]) -> None:
        self._stale = list(stale)
        self._live = list(live)
        self._active = self._stale
        self._is_open = True
        self.reset_calls = 0

    @property
    def is_open(self) -> bool:
        return self._is_open

    def close(self) -> None:
        self._is_open = False

    def reset_input_buffer(self) -> None:
        self.reset_calls += 1
        self._stale.clear()
        self._active = self._live

    def readline(self) -> bytes:
        if not self._active:
            return b""
        return self._active.pop(0)


class FailingResetPort(BufferedSerialPort):
    def reset_input_buffer(self) -> None:
        raise serial.SerialException("reset failed")


def test_refresh_discards_queued_nmea_before_recording_utc_receipt() -> None:
    port = BufferedSerialPort(
        stale=[_rmc(20), _gga(20)],
        live=[_rmc(30), _gga(30)],
    )
    receiver = SerialGPSReceiver(
        Path("/dev/serial/by-id/gps"),
        serial_factory=lambda _device, _baud, _timeout: port,
        clock=lambda: _FIXED_TIME,
        monotonic_clock=lambda: 100.0,
    )

    state = receiver.connect()

    assert port.reset_calls == 1
    assert state.connection_state is GPSConnectionState.CONNECTED
    assert state.utc.value == datetime(2026, 8, 8, 23, 9, 30, tzinfo=UTC)
    assert state.utc.received_monotonic_s == pytest.approx(100.0)


def test_buffer_reset_failure_closes_port_and_reports_connection_error() -> None:
    port = FailingResetPort(stale=[], live=[])
    receiver = SerialGPSReceiver(
        Path("/dev/serial/by-id/gps"),
        serial_factory=lambda _device, _baud, _timeout: port,
        clock=lambda: _FIXED_TIME,
    )

    with pytest.raises(GPSConnectionError, match="discard buffered GPS data"):
        receiver.connect()

    assert port.is_open is False
    assert receiver.get_state().connection_state is GPSConnectionState.ERROR
