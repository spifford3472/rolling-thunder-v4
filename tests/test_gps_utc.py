"""Tests for receiver UTC parsing and trust qualification."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from rolling_thunder.domain import GPSFixState
from rolling_thunder.gps import GPSUTCSource
from rolling_thunder.serial_gps import GPSParseError, SerialGPSReceiver, parse_rmc_sentence


def _sentence(payload: str) -> str:
    checksum = 0
    for character in payload:
        checksum ^= ord(character)
    return f"${payload}*{checksum:02X}\r\n"


class FakeSerialPort:
    def __init__(self, replies: list[bytes]) -> None:
        self.replies = replies
        self._is_open = True

    @property
    def is_open(self) -> bool:
        return self._is_open

    def close(self) -> None:
        self._is_open = False

    def readline(self) -> bytes:
        if not self.replies:
            return b""
        return self.replies.pop(0)


def _gga(*, second: int, fix_quality: int = 2) -> bytes:
    if fix_quality == 0:
        payload = f"GNGGA,1316{second:02d}.000,,,,,0,00,99.9,,,,,,"
    else:
        payload = (
            f"GNGGA,1316{second:02d}.000,3931.4668,N,08403.7491,W,"
            f"{fix_quality},15,0.68,271.6,M,-33.3,M,,"
        )
    return _sentence(payload).encode("ascii")


def _rmc(*, second: int, status: str = "A") -> bytes:
    if status == "V":
        payload = f"GNRMC,1316{second:02d}.000,V,,,,,,,020826,,,N"
    else:
        payload = (
            f"GNRMC,1316{second:02d}.000,A,3931.4668,N,08403.7491,W,"
            "0.07,0.00,020826,,,D"
        )
    return _sentence(payload).encode("ascii")


def test_parse_rmc_exposes_receiver_utc_without_host_clock() -> None:
    observation = parse_rmc_sentence(
        _sentence("GNRMC,131645.250,A,3931.4668,N,08403.7491,W,12.5,87.3,020826,,,D")
    )

    assert observation.utc == datetime(2026, 8, 2, 13, 16, 45, 250_000, tzinfo=UTC)
    assert observation.fix_valid is True


def test_parse_void_rmc_keeps_utc_but_marks_fix_invalid() -> None:
    observation = parse_rmc_sentence(
        _sentence("GNRMC,131645.000,V,,,,,,,020826,,,N")
    )

    assert observation.utc == datetime(2026, 8, 2, 13, 16, 45, tzinfo=UTC)
    assert observation.fix_valid is False
    assert observation.speed_m_s is None
    assert observation.heading_degrees is None


@pytest.mark.parametrize(
    "payload",
    [
        "GNRMC,136145.000,A,3931.4668,N,08403.7491,W,0.0,0.0,020826,,,D",
        "GNRMC,131645.000,A,3931.4668,N,08403.7491,W,0.0,0.0,320826,,,D",
        "GNRMC,131645.bad,A,3931.4668,N,08403.7491,W,0.0,0.0,020826,,,D",
    ],
)
def test_parse_rmc_rejects_malformed_utc(payload: str) -> None:
    with pytest.raises(GPSParseError, match="RMC"):
        parse_rmc_sentence(_sentence(payload))


def test_first_valid_rmc_is_not_trusted_until_utc_advances() -> None:
    monotonic_now = [100.0]
    receiver = SerialGPSReceiver(
        Path("/dev/serial/by-id/gps"),
        serial_factory=lambda _device, _baud, _timeout: FakeSerialPort(
            [_rmc(second=45), _gga(second=45), _rmc(second=46), _gga(second=46)]
        ),
        clock=lambda: datetime(2026, 1, 1, tzinfo=UTC),
        monotonic_clock=lambda: monotonic_now[0],
    )

    first = receiver.connect()

    assert first.utc.value == datetime(2026, 8, 2, 13, 16, 45, tzinfo=UTC)
    assert first.utc.source is GPSUTCSource.RMC
    assert first.utc.valid is True
    assert first.utc.fix_valid is True
    assert first.utc.advancing is False
    assert first.utc.fresh is True
    assert first.utc.trusted is False

    monotonic_now[0] = 101.0
    second = receiver.refresh_state()

    assert second.utc.value == datetime(2026, 8, 2, 13, 16, 46, tzinfo=UTC)
    assert second.utc.age_s == pytest.approx(0.0)
    assert second.utc.advancing is True
    assert second.utc.fresh is True
    assert second.utc.trusted is True


def test_duplicate_rmc_does_not_refresh_sample_age() -> None:
    monotonic_now = [100.0]
    port = FakeSerialPort(
        [
            _rmc(second=45),
            _gga(second=45),
            _rmc(second=46),
            _gga(second=46),
            _rmc(second=46),
            _gga(second=47),
            _gga(second=48),
        ]
    )
    receiver = SerialGPSReceiver(
        Path("/dev/serial/by-id/gps"),
        maximum_utc_age_s=5.0,
        serial_factory=lambda _device, _baud, _timeout: port,
        clock=lambda: datetime(2026, 1, 1, tzinfo=UTC),
        monotonic_clock=lambda: monotonic_now[0],
    )
    receiver.connect()

    monotonic_now[0] = 101.0
    assert receiver.refresh_state().utc.trusted is True

    monotonic_now[0] = 102.0
    duplicate = receiver.refresh_state()
    assert duplicate.utc.age_s == pytest.approx(1.0)
    assert duplicate.utc.trusted is True

    monotonic_now[0] = 107.0
    stale = receiver.refresh_state()
    assert stale.utc.age_s == pytest.approx(6.0)
    assert stale.utc.fresh is False
    assert stale.utc.trusted is False


def test_backward_rmc_breaks_advancing_sequence() -> None:
    monotonic_now = [100.0]
    receiver = SerialGPSReceiver(
        Path("/dev/serial/by-id/gps"),
        serial_factory=lambda _device, _baud, _timeout: FakeSerialPort(
            [
                _rmc(second=45),
                _gga(second=45),
                _rmc(second=46),
                _gga(second=46),
                _rmc(second=44),
                _gga(second=47),
            ]
        ),
        clock=lambda: datetime(2026, 1, 1, tzinfo=UTC),
        monotonic_clock=lambda: monotonic_now[0],
    )
    receiver.connect()

    monotonic_now[0] = 101.0
    assert receiver.refresh_state().utc.trusted is True

    monotonic_now[0] = 102.0
    regressed = receiver.refresh_state()

    assert regressed.utc.value == datetime(2026, 8, 2, 13, 16, 46, tzinfo=UTC)
    assert regressed.utc.advancing is False
    assert regressed.utc.trusted is False


def test_valid_rmc_utc_is_not_trusted_without_active_gga_fix() -> None:
    monotonic_now = [100.0]
    receiver = SerialGPSReceiver(
        Path("/dev/serial/by-id/gps"),
        serial_factory=lambda _device, _baud, _timeout: FakeSerialPort(
            [
                _rmc(second=45),
                _gga(second=45),
                _rmc(second=46),
                _gga(second=46, fix_quality=0),
            ]
        ),
        clock=lambda: datetime(2026, 1, 1, tzinfo=UTC),
        monotonic_clock=lambda: monotonic_now[0],
    )
    receiver.connect()

    monotonic_now[0] = 101.0
    no_fix = receiver.refresh_state()

    assert no_fix.position is not None
    assert no_fix.position.fix_state is GPSFixState.NO_FIX
    assert no_fix.utc.valid is True
    assert no_fix.utc.advancing is True
    assert no_fix.utc.fresh is True
    assert no_fix.utc.fix_valid is False
    assert no_fix.utc.trusted is False


def test_receiver_validates_maximum_utc_age() -> None:
    with pytest.raises(ValueError, match="UTC age"):
        SerialGPSReceiver(Path("/dev/serial/by-id/gps"), maximum_utc_age_s=0)
