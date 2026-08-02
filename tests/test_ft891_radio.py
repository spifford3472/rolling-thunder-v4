"""Tests for the FT-891 radio adapter."""

from datetime import UTC, datetime

import pytest

from rolling_thunder.domain import Frequency, RadioConnectionState, RadioMode
from rolling_thunder.ft891_radio import Ft891Radio
from rolling_thunder.radio import (
    BandChangeRequiredError,
    Radio,
    RadioBand,
    RadioConnectionError,
    RadioError,
    RadioVerificationError,
)


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


def test_same_band_frequency_and_mode_changes_use_verified_commands() -> None:
    transport = FakeTransport()
    radio = Ft891Radio(transport, clock=fixed_clock)
    radio.connect()

    transport.replies[b"FA;"] = b"FA014300000;"
    radio.set_frequency(Frequency(hz=14_300_000))

    transport.replies[b"MD0;"] = b"MD01;"
    state = radio.set_mode(RadioMode.LSB)

    assert transport.commands[-4:] == [
        b"FA014300000;",
        b"FA;",
        b"MD01;",
        b"MD0;",
    ]
    assert state.frequency == Frequency(hz=14_300_000)
    assert state.mode is RadioMode.LSB


def test_select_band_sends_band_command_before_verification_reads() -> None:
    transport = FakeTransport()
    radio = Ft891Radio(transport, clock=fixed_clock)
    radio.connect()
    transport.replies[b"FA;"] = b"FA007200000;"
    transport.replies[b"MD0;"] = b"MD01;"

    state = radio.select_band(RadioBand.BAND_40M)

    assert transport.commands[-3:] == [b"BS03;", b"FA;", b"MD0;"]
    assert state.frequency == Frequency(hz=7_200_000)
    assert state.mode is RadioMode.LSB


def test_cross_band_frequency_change_requires_band_selection() -> None:
    transport = FakeTransport()
    radio = Ft891Radio(transport, clock=fixed_clock)
    radio.connect()
    commands_before = list(transport.commands)

    with pytest.raises(
        BandChangeRequiredError,
        match="Select 40m before changing frequency from 20m",
    ):
        radio.set_frequency(Frequency(hz=7_255_000))

    assert transport.commands == commands_before


def test_failed_band_verification_stops_after_read_back() -> None:
    transport = FakeTransport()
    radio = Ft891Radio(transport, clock=fixed_clock)
    radio.connect()

    with pytest.raises(
        RadioVerificationError,
        match="requested 40m but read back 20m",
    ):
        radio.select_band(RadioBand.BAND_40M)

    assert transport.commands[-3:] == [b"BS03;", b"FA;", b"MD0;"]


def test_unsupported_60m_band_selection_sends_no_command() -> None:
    transport = FakeTransport()
    radio = Ft891Radio(transport, clock=fixed_clock)
    radio.connect()
    commands_before = list(transport.commands)

    with pytest.raises(
        RadioError,
        match="band selection does not support 60m",
    ):
        radio.select_band(RadioBand.BAND_60M)

    assert transport.commands == commands_before


def test_frequency_read_back_must_match_request() -> None:
    transport = FakeTransport()
    radio = Ft891Radio(transport, clock=fixed_clock)
    radio.connect()

    with pytest.raises(
        RadioVerificationError,
        match="requested 14300000 Hz but read back 14250000 Hz",
    ):
        radio.set_frequency(Frequency(hz=14_300_000))

    assert transport.commands[-2:] == [b"FA014300000;", b"FA;"]


def test_mode_read_back_must_match_request() -> None:
    transport = FakeTransport()
    radio = Ft891Radio(transport, clock=fixed_clock)
    radio.connect()

    with pytest.raises(
        RadioVerificationError,
        match="requested LSB but read back USB",
    ):
        radio.set_mode(RadioMode.LSB)

    assert transport.commands[-2:] == [b"MD01;", b"MD0;"]


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
