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
        self.replies: dict[bytes, bytes] = {
            b"FA;": b"FA014250000;",
            b"MD0;": b"MD02;",
        }
        self.open_error: RadioConnectionError | None = None
        self.query_errors: dict[bytes, RadioConnectionError] = {}

    def open(self) -> None:
        if self.open_error is not None:
            raise self.open_error
        self.opened = True

    def close(self) -> None:
        self.opened = False

    def query(self, command: bytes) -> bytes:
        self.commands.append(command)
        error = self.query_errors.get(command)
        if error is not None:
            raise error
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


def test_refresh_reads_unchanged_hardware_state() -> None:
    transport = FakeTransport()
    radio = Ft891Radio(transport, clock=fixed_clock)
    connected = radio.connect()

    refreshed = radio.refresh_state()

    assert refreshed is not connected
    assert refreshed.connection_state is RadioConnectionState.CONNECTED
    assert refreshed.frequency == connected.frequency
    assert refreshed.mode is connected.mode
    assert transport.commands[-2:] == [b"FA;", b"MD0;"]


def test_refresh_detects_manual_frequency_and_mode_changes() -> None:
    transport = FakeTransport()
    radio = Ft891Radio(transport, clock=fixed_clock)
    radio.connect()
    transport.replies[b"FA;"] = b"FA007255000;"
    transport.replies[b"MD0;"] = b"MD01;"

    state = radio.refresh_state()

    assert state.frequency == Frequency(hz=7_255_000)
    assert state.mode is RadioMode.LSB
    assert state.connection_state is RadioConnectionState.CONNECTED


def test_refresh_malformed_reply_enters_error_with_last_known_state() -> None:
    transport = FakeTransport()
    radio = Ft891Radio(transport, clock=fixed_clock)
    radio.connect()
    transport.replies[b"FA;"] = b"FA-not-valid;"

    with pytest.raises(RadioConnectionError, match="Could not refresh"):
        radio.refresh_state()

    state = radio.get_state()
    assert transport.opened is False
    assert state.connection_state is RadioConnectionState.ERROR
    assert state.frequency == Frequency(hz=14_250_000)
    assert state.mode is RadioMode.USB
    assert state.last_error is not None
    assert "Malformed FT-891 frequency reply" in state.last_error


def test_refresh_device_loss_enters_error_with_last_known_state() -> None:
    transport = FakeTransport()
    radio = Ft891Radio(transport, clock=fixed_clock)
    radio.connect()
    transport.query_errors[b"FA;"] = RadioConnectionError("USB serial device disappeared")

    with pytest.raises(RadioConnectionError, match="device disappeared"):
        radio.refresh_state()

    state = radio.get_state()
    assert transport.opened is False
    assert state.connection_state is RadioConnectionState.ERROR
    assert state.frequency == Frequency(hz=14_250_000)
    assert state.mode is RadioMode.USB
    assert state.last_error == "USB serial device disappeared"


def test_refresh_requires_connection() -> None:
    radio = Ft891Radio(FakeTransport(), clock=fixed_clock)

    with pytest.raises(RadioConnectionError, match="requires a connected radio"):
        radio.refresh_state()


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
