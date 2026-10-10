"""Tests for the FT-891 radio adapter."""

from datetime import UTC, datetime

import pytest

from rolling_thunder.domain import Frequency, RadioConnectionState, RadioMode
from rolling_thunder.ft891_cat import Ft891SsbBfo
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
            b"MC;": b"MC003;",
            b"PC;": b"PC100;",
            b"EX1107;": b"EX11072;",
            b"PA0;": b"PA01;",
            b"NA0;": b"NA00;",
            b"NB0;": b"NB00;",
        }
        self.open_error: RadioConnectionError | None = None
        self.query_errors: dict[bytes, RadioConnectionError] = {}
        self.command_errors: dict[bytes, RadioConnectionError] = {}

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
        error = self.command_errors.get(command)
        if error is not None:
            raise error


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


def test_ft8_receiver_settings_set_and_verify_readback() -> None:
    transport = FakeTransport()
    radio = Ft891Radio(transport, clock=fixed_clock)
    radio.connect()

    assert radio.set_preamp_enabled(True) is True
    assert transport.commands[-2:] == [b"PA01;", b"PA0;"]

    assert radio.set_narrow_enabled(False) is False
    assert transport.commands[-2:] == [b"NA00;", b"NA0;"]

    assert radio.set_noise_blanker_enabled(False) is False
    assert transport.commands[-2:] == [b"NB00;", b"NB0;"]


def test_power_set_and_readback_are_verified() -> None:
    transport = FakeTransport()
    radio = Ft891Radio(transport, clock=fixed_clock)
    radio.connect()
    transport.replies[b"PC;"] = b"PC020;"

    verified = radio.set_power_watts(20)

    assert verified == 20
    assert transport.commands[-2:] == [b"PC020;", b"PC;"]


def test_power_wrong_readback_raises_verification_error() -> None:
    transport = FakeTransport()
    radio = Ft891Radio(transport, clock=fixed_clock)
    radio.connect()
    transport.replies[b"PC;"] = b"PC100;"

    with pytest.raises(
        RadioVerificationError,
        match="requested 20 W but read back 100 W",
    ):
        radio.set_power_watts(20)

    assert transport.commands[-2:] == [b"PC020;", b"PC;"]


def test_ssb_bfo_set_and_readback_are_verified() -> None:
    transport = FakeTransport()
    radio = Ft891Radio(transport, clock=fixed_clock)
    radio.connect()
    transport.replies[b"EX1107;"] = b"EX11070;"

    verified = radio.set_ssb_bfo(Ft891SsbBfo.USB)

    assert verified is Ft891SsbBfo.USB
    assert transport.commands[-2:] == [b"EX11070;", b"EX1107;"]


def test_ssb_bfo_wrong_readback_raises_verification_error() -> None:
    transport = FakeTransport()
    radio = Ft891Radio(transport, clock=fixed_clock)
    radio.connect()
    transport.replies[b"EX1107;"] = b"EX11072;"

    with pytest.raises(
        RadioVerificationError,
        match="requested USB but read back AUTO",
    ):
        radio.set_ssb_bfo(Ft891SsbBfo.USB)

    assert transport.commands[-2:] == [b"EX11070;", b"EX1107;"]


def test_power_and_ssb_bfo_configuration_require_connection() -> None:
    radio = Ft891Radio(FakeTransport(), clock=fixed_clock)

    with pytest.raises(RadioConnectionError, match="requires a connected radio"):
        radio.set_power_watts(20)
    with pytest.raises(RadioConnectionError, match="requires a connected radio"):
        radio.set_ssb_bfo(Ft891SsbBfo.USB)


def test_select_band_recalls_mapped_memory_before_verification_reads() -> None:
    transport = FakeTransport()
    radio = Ft891Radio(transport, clock=fixed_clock)
    radio.connect()
    transport.replies[b"MC;"] = b"MC003;"
    transport.replies[b"FA;"] = b"FA007200000;"
    transport.replies[b"MD0;"] = b"MD01;"

    state = radio.select_band(RadioBand.BAND_40M)

    assert transport.commands[-5:] == [
        b"MC003;",
        b"MC;",
        b"MA;",
        b"FA;",
        b"MD0;",
    ]
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


def test_wrong_selected_memory_stops_before_memory_to_vfo() -> None:
    transport = FakeTransport()
    radio = Ft891Radio(transport, clock=fixed_clock)
    radio.connect()
    transport.replies[b"MC;"] = b"MC005;"

    with pytest.raises(
        RadioVerificationError,
        match="requested memory 003 for 40m but read back 005",
    ):
        radio.select_band(RadioBand.BAND_40M)

    assert transport.commands[-2:] == [b"MC003;", b"MC;"]
    assert b"MA;" not in transport.commands


def test_wrong_recalled_band_fails_after_memory_to_vfo_read_back() -> None:
    transport = FakeTransport()
    radio = Ft891Radio(transport, clock=fixed_clock)
    radio.connect()
    transport.replies[b"MC;"] = b"MC003;"

    with pytest.raises(
        RadioVerificationError,
        match="requested 40m via memory 003 but recalled 20m",
    ):
        radio.select_band(RadioBand.BAND_40M)

    assert transport.commands[-5:] == [
        b"MC003;",
        b"MC;",
        b"MA;",
        b"FA;",
        b"MD0;",
    ]


def test_unsupported_60m_band_selection_sends_no_command() -> None:
    transport = FakeTransport()
    radio = Ft891Radio(transport, clock=fixed_clock)
    radio.connect()
    commands_before = list(transport.commands)

    with pytest.raises(
        RadioError,
        match="memory band selection does not support 60m",
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


def test_cp6_cat_ptt_keys_and_releases_through_existing_radio_owner() -> None:
    transport = FakeTransport()
    radio = Ft891Radio(transport, clock=fixed_clock)
    radio.connect()
    capability = radio.create_cp6_cat_ptt_capability()

    capability.key()
    capability.release()

    assert transport.commands[-2:] == [b"TX1;", b"TX0;"]


def test_cp6_cat_ptt_key_is_idempotent_while_asserted() -> None:
    transport = FakeTransport()
    radio = Ft891Radio(transport, clock=fixed_clock)
    radio.connect()
    capability = radio.create_cp6_cat_ptt_capability()

    capability.key()
    capability.key()
    capability.release()

    assert transport.commands[-2:] == [b"TX1;", b"TX0;"]


def test_cp6_cat_ptt_release_is_noop_until_ptt_was_asserted() -> None:
    transport = FakeTransport()
    radio = Ft891Radio(transport, clock=fixed_clock)
    radio.connect()
    capability = radio.create_cp6_cat_ptt_capability()
    commands_before = list(transport.commands)

    capability.release()
    capability.release()

    assert transport.commands == commands_before


def test_cp6_cat_ptt_release_sends_receive_once_after_assertion() -> None:
    transport = FakeTransport()
    radio = Ft891Radio(transport, clock=fixed_clock)
    radio.connect()
    capability = radio.create_cp6_cat_ptt_capability()

    capability.key()
    capability.release()
    commands_after_release = list(transport.commands)
    capability.release()

    assert commands_after_release[-2:] == [b"TX1;", b"TX0;"]
    assert transport.commands == commands_after_release


def test_cp6_cat_ptt_failed_key_attempts_immediate_release() -> None:
    transport = FakeTransport()
    radio = Ft891Radio(transport, clock=fixed_clock)
    radio.connect()
    transport.command_errors[b"TX1;"] = RadioConnectionError("CAT write failed")
    capability = radio.create_cp6_cat_ptt_capability()

    with pytest.raises(RadioConnectionError, match="CAT write failed"):
        capability.key()

    assert transport.commands[-2:] == [b"TX1;", b"TX0;"]


def test_cp6_cat_ptt_cancel_and_close_release_receive() -> None:
    transport = FakeTransport()
    radio = Ft891Radio(transport, clock=fixed_clock)
    radio.connect()
    capability = radio.create_cp6_cat_ptt_capability()

    capability.key()
    capability.cancel()
    capability.key()
    capability.close()
    capability.close()

    assert transport.commands[-4:] == [b"TX1;", b"TX0;", b"TX1;", b"TX0;"]


def test_disconnect_releases_cp6_cat_ptt_before_closing_transport() -> None:
    transport = FakeTransport()
    radio = Ft891Radio(transport, clock=fixed_clock)
    radio.connect()
    capability = radio.create_cp6_cat_ptt_capability()
    capability.key()

    radio.disconnect()

    assert transport.commands[-2:] == [b"TX1;", b"TX0;"]
    assert transport.opened is False


def test_cp6_tx_meters_read_alc_power_and_swr() -> None:
    transport = FakeTransport()
    transport.replies[b"RM4;"] = b"RM4123;"
    transport.replies[b"RM5;"] = b"RM5045;"
    transport.replies[b"RM6;"] = b"RM6007;"
    radio = Ft891Radio(transport, clock=fixed_clock)
    radio.connect()

    alc, power, swr = radio.read_cp6_tx_meters()

    assert (alc, power, swr) == (123, 45, 7)
    assert transport.commands[-3:] == [b"RM4;", b"RM5;", b"RM6;"]


def test_cp6_tx_meter_selector_mismatch_is_rejected() -> None:
    transport = FakeTransport()
    transport.replies[b"RM4;"] = b"RM5123;"
    radio = Ft891Radio(transport, clock=fixed_clock)
    radio.connect()

    with pytest.raises(RadioError, match="selector mismatch"):
        radio.read_cp6_tx_meters()


@pytest.mark.parametrize("value, digit", [("mic", b"0"), ("rear", b"1")])
def test_ssb_mic_select_adapter_verifies_readback(value: str, digit: bytes) -> None:
    from rolling_thunder.ft891_cat import Ft891SsbMicSelect

    transport = FakeTransport()
    radio = Ft891Radio(transport, clock=fixed_clock)
    radio.connect()
    transport.replies[b"EX1105;"] = b"EX1105" + digit + b";"
    typed = Ft891SsbMicSelect(value)
    assert radio.set_ssb_mic_select(typed) is typed
    assert transport.commands[-2:] == [b"EX1105" + digit + b";", b"EX1105;"]
    assert radio.read_ssb_mic_select() is typed


def test_ssb_mic_select_adapter_rejects_wrong_readback_and_disconnection() -> None:
    from rolling_thunder.ft891_cat import Ft891SsbMicSelect

    transport = FakeTransport()
    radio = Ft891Radio(transport, clock=fixed_clock)
    with pytest.raises(RadioConnectionError):
        radio.set_ssb_mic_select(Ft891SsbMicSelect.REAR)
    with pytest.raises(RadioConnectionError):
        radio.read_ssb_mic_select()
    radio.connect()
    transport.replies[b"EX1105;"] = b"EX11050;"
    with pytest.raises(RadioVerificationError, match="requested REAR but read back MIC"):
        radio.set_ssb_mic_select(Ft891SsbMicSelect.REAR)


def test_cp6_failed_release_keeps_retryable_tx_state() -> None:
    transport = FakeTransport()
    radio = Ft891Radio(transport, clock=fixed_clock)
    radio.connect()
    capability = radio.create_cp6_cat_ptt_capability()
    capability.key()
    transport.command_errors[b"TX0;"] = RadioConnectionError("CAT release timeout")
    with pytest.raises(RadioConnectionError):
        capability.release()
    del transport.command_errors[b"TX0;"]
    capability.cancel()
    assert transport.commands.count(b"TX0;") == 2


def test_failed_key_and_failed_compensating_release_remain_retryable() -> None:
    transport = FakeTransport()
    radio = Ft891Radio(transport, clock=fixed_clock)
    radio.connect()
    ptt = radio.create_cp6_cat_ptt_capability()
    transport.command_errors[b"TX1;"] = RadioConnectionError("TX on uncertain")
    transport.command_errors[b"TX0;"] = RadioConnectionError("TX off failed")
    with pytest.raises(RadioConnectionError, match="TX on uncertain"):
        ptt.key()
    del transport.command_errors[b"TX0;"]
    ptt.cancel()
    assert transport.commands.count(b"TX0;") == 2
