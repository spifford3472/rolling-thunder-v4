"""Tests for the FT-891 radio adapter."""

from datetime import UTC, datetime

import pytest

from rolling_thunder.domain import Frequency, RadioConnectionState, RadioMode
from rolling_thunder.ft891_radio import Ft891Radio
from rolling_thunder.radio import Radio, RadioBand, RadioConnectionError


class FakeTransport:
    def __init__(self) -> None:
        self.opened = False
        self.commands: list[bytes] = []
        self.replies = {
            b"FA;": b"FA014250000;",
            b"MD0;": b"MD02;",
        }
        self.open_error: Exception | None = None

    def open(self) -> None:
        if self.open_error is not None:
            raise self.open_error
        self.opened = True

    def close(self) -> None:
        self.opened = False

    def query(self, command: bytes) -> bytes:
        self.commands.append(command)
        return self.replies[command]

    def command(self, command: bytes) -> None:
        self.commands.append(command)


def fixed_clock() -> datetime:
    return datetime(2026, 7, 25, 5, 0, tzinfo=UTC)


def test_adapter_satisfies_radio_protocol() -> None:
    assert isinstance(Ft891Radio(FakeTransport(), clock=fixed_clock), Radio)


def test_connect_reads_frequency_and_mode() -> None:
    transport = FakeTransport()
    radio = Ft891Radio(transport, clock=fixed_clock)

    state = radio.connect()

    assert transport.opened is True
    assert transport.commands == [b"FA;", b"MD0;"]
    assert state.connection_state is RadioConnectionState.CONNECTED
    assert state.frequency == Frequency(hz=14_250_000)
    assert state.mode is RadioMode.USB
    assert state.transmitting is False


def test_frequency_and_mode_changes_emit_safe_cat_commands() -> None:
    transport = FakeTransport()
    radio = Ft891Radio(transport, clock=fixed_clock)
    radio.connect()

    radio.set_frequency(Frequency(hz=7_255_000))
    state = radio.set_mode(RadioMode.LSB)

    assert transport.commands[-2:] == [b"FA007255000;", b"MD01;"]
    assert state.frequency == Frequency(hz=7_255_000)
    assert state.mode is RadioMode.LSB


def test_change_band_sets_mode_before_frequency() -> None:
    transport = FakeTransport()
    radio = Ft891Radio(transport, clock=fixed_clock)
    radio.connect()

    state = radio.change_band(RadioBand.BAND_40M)

    assert transport.commands[-2:] == [b"MD01;", b"FA007200000;"]
    assert state.frequency == Frequency(hz=7_200_000)
    assert state.mode is RadioMode.LSB


def test_disconnect_closes_transport_and_clears_readout() -> None:
    transport = FakeTransport()
    radio = Ft891Radio(transport, clock=fixed_clock)
    radio.connect()

    state = radio.disconnect()

    assert transport.opened is False
    assert state.connection_state is RadioConnectionState.DISCONNECTED
    assert state.frequency is None
    assert state.mode is None


def test_tuning_requires_connection() -> None:
    radio = Ft891Radio(FakeTransport(), clock=fixed_clock)

    with pytest.raises(RadioConnectionError, match="requires a connected radio"):
        radio.set_frequency(Frequency(hz=14_250_000))


def test_connect_failure_closes_transport_and_records_error() -> None:
    transport = FakeTransport()
    transport.open_error = RadioConnectionError("device unavailable")
    radio = Ft891Radio(transport, clock=fixed_clock)

    with pytest.raises(RadioConnectionError, match="device unavailable"):
        radio.connect()

    state = radio.get_state()
    assert transport.opened is False
    assert state.connection_state is RadioConnectionState.ERROR
    assert state.last_error == "device unavailable"
