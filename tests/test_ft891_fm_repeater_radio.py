"""Tests for atomic FT-891 six-meter FM repeater configuration."""

from datetime import UTC, datetime
from decimal import Decimal
from threading import Event, Thread

import pytest

from rolling_thunder.domain import Frequency, RadioMode, RadioState
from rolling_thunder.fm_repeater import (
    FmRepeaterConfigurableRadio,
    FmRepeaterConfigurationRequest,
    FmRepeaterConfigurationStatus,
    FmRepeaterShiftDirection,
    FmRepeaterUnsupportedReason,
)
from rolling_thunder.ft891_radio import Ft891Radio
from rolling_thunder.radio import RadioError, RadioVerificationError


class StatefulRepeaterTransport:
    """Deterministic CAT transport that mirrors accepted set commands into reads."""

    def __init__(self) -> None:
        self.opened = False
        self.commands: list[bytes] = []
        self.replies: dict[bytes, bytes] = {
            b"FA;": b"FA014250000;",
            b"MD0;": b"MD02;",
            b"MC;": b"MC010;",
            b"IF;": b"IF010050125000+000000400000;",
            b"OS0;": b"OS00;",
            b"EX0905;": b"EX09050000;",
            b"CN00;": b"CN00000;",
            b"CT0;": b"CT00;",
        }
        self.force_replies: dict[bytes, bytes] = {}

    def open(self) -> None:
        self.opened = True

    def close(self) -> None:
        self.opened = False

    def command(self, command: bytes) -> None:
        self.commands.append(command)
        if command.startswith(b"MC") and command != b"MC;":
            self.replies[b"MC;"] = command
        elif command == b"MA;":
            self.replies[b"FA;"] = b"FA050125000;"
            self.replies[b"MD0;"] = b"MD02;"
            self.replies[b"IF;"] = b"IF010050125000+000000200000;"
        elif command.startswith(b"FA") and command != b"FA;":
            self.replies[b"FA;"] = command
        elif command.startswith(b"MD0") and command != b"MD0;":
            self.replies[b"MD0;"] = command
        elif command.startswith(b"OS0") and command != b"OS0;":
            self.replies[b"OS0;"] = command
        elif command.startswith(b"EX0905") and command != b"EX0905;":
            self.replies[b"EX0905;"] = command
        elif command.startswith(b"CN00") and command != b"CN00;":
            self.replies[b"CN00;"] = command
        elif command.startswith(b"CT0") and command != b"CT0;":
            self.replies[b"CT0;"] = command

    def query(self, command: bytes) -> bytes:
        self.commands.append(command)
        return self.force_replies.get(command, self.replies[command])


def fixed_clock() -> datetime:
    return datetime(2026, 8, 11, 23, 30, tzinfo=UTC)


def repeater_request(
    *,
    rx_frequency_hz: int = 52_525_000,
    shift: FmRepeaterShiftDirection = FmRepeaterShiftDirection.MINUS,
    offset_hz: int = 1_000_000,
    rx_tone: str | None = None,
    tx_tone: str | None = "131.8",
) -> FmRepeaterConfigurationRequest:
    return FmRepeaterConfigurationRequest(
        rx_frequency=Frequency(hz=rx_frequency_hz),
        shift_direction=shift,
        offset_hz=offset_hz,
        rx_tone_hz=Decimal(rx_tone) if rx_tone is not None else None,
        tx_tone_hz=Decimal(tx_tone) if tx_tone is not None else None,
    )


def connected_radio() -> tuple[Ft891Radio, StatefulRepeaterTransport]:
    transport = StatefulRepeaterTransport()
    radio = Ft891Radio(transport, clock=fixed_clock)
    radio.connect()
    return radio, transport


def test_ft891_adapter_satisfies_typed_repeater_capability() -> None:
    radio, _transport = connected_radio()

    assert isinstance(radio, FmRepeaterConfigurableRadio)


def test_encode_only_repeater_configuration_uses_exact_verified_sequence() -> None:
    radio, transport = connected_radio()
    transport.commands.clear()

    outcome = radio.configure_fm_repeater(repeater_request())

    assert outcome.status is FmRepeaterConfigurationStatus.CONFIGURED
    assert outcome.state is not None
    assert outcome.state.frequency == Frequency(hz=52_525_000)
    assert outcome.state.mode is RadioMode.FM
    assert outcome.manual_band_confirmation_required is True
    assert transport.commands == [
        b"MC010;",
        b"MC;",
        b"MA;",
        b"FA;",
        b"MD0;",
        b"IF;",
        b"FA052525000;",
        b"FA;",
        b"MD04;",
        b"MD0;",
        b"OS02;",
        b"OS0;",
        b"EX09051000;",
        b"EX0905;",
        b"CN00020;",
        b"CN00;",
        b"CT02;",
        b"CT0;",
    ]


def test_equal_tone_configuration_uses_shared_encode_decode() -> None:
    radio, transport = connected_radio()
    transport.commands.clear()

    outcome = radio.configure_fm_repeater(
        repeater_request(rx_tone="131.8", tx_tone="131.8")
    )

    assert outcome.status is FmRepeaterConfigurationStatus.CONFIGURED
    assert transport.commands[-4:] == [b"CN00020;", b"CN00;", b"CT01;", b"CT0;"]


def test_no_tone_configuration_turns_ctcss_off_without_changing_tone_number() -> None:
    radio, transport = connected_radio()
    transport.commands.clear()

    outcome = radio.configure_fm_repeater(
        repeater_request(rx_tone=None, tx_tone=None)
    )

    assert outcome.status is FmRepeaterConfigurationStatus.CONFIGURED
    assert b"CN00;" not in transport.commands
    assert transport.commands[-2:] == [b"CT00;", b"CT0;"]


@pytest.mark.parametrize(
    ("configuration", "reason"),
    [
        (
            repeater_request(rx_tone="131.8", tx_tone="151.4"),
            FmRepeaterUnsupportedReason.INDEPENDENT_CTCSS_TONES,
        ),
        (
            repeater_request(rx_tone="131.8", tx_tone=None),
            FmRepeaterUnsupportedReason.RECEIVE_ONLY_CTCSS,
        ),
        (
            repeater_request(rx_tone=None, tx_tone="123.4"),
            FmRepeaterUnsupportedReason.CTCSS_TONE_UNSUPPORTED,
        ),
        (
            repeater_request(offset_hz=4_010_000),
            FmRepeaterUnsupportedReason.OFFSET_OUT_OF_RANGE,
        ),
        (
            repeater_request(offset_hz=1_005_000),
            FmRepeaterUnsupportedReason.OFFSET_STEP_UNSUPPORTED,
        ),
        (
            repeater_request(rx_frequency_hz=29_600_000),
            FmRepeaterUnsupportedReason.UNSUPPORTED_BAND,
        ),
    ],
)
def test_unsupported_configuration_returns_manual_handoff_before_any_cat_write(
    configuration: FmRepeaterConfigurationRequest,
    reason: FmRepeaterUnsupportedReason,
) -> None:
    radio, transport = connected_radio()
    commands_before = list(transport.commands)

    outcome = radio.configure_fm_repeater(configuration)

    assert outcome.status is FmRepeaterConfigurationStatus.UNSUPPORTED_MANUAL_HANDOFF
    assert outcome.unsupported_reason is reason
    assert outcome.manual_handoff is not None
    assert transport.commands == commands_before


def test_vfo_verification_failure_stops_before_exact_frequency() -> None:
    radio, transport = connected_radio()
    transport.commands.clear()
    transport.force_replies[b"IF;"] = b"IF010050125000+000000210000;"

    with pytest.raises(RadioVerificationError, match="VFO verification failed"):
        radio.configure_fm_repeater(repeater_request())

    assert transport.commands == [
        b"MC010;",
        b"MC;",
        b"MA;",
        b"FA;",
        b"MD0;",
        b"IF;",
    ]


def test_shift_readback_mismatch_stops_before_offset_and_ctcss() -> None:
    radio, transport = connected_radio()
    transport.commands.clear()
    transport.force_replies[b"OS0;"] = b"OS01;"

    with pytest.raises(RadioVerificationError, match="repeater-shift verification failed"):
        radio.configure_fm_repeater(repeater_request())

    assert b"EX09051000;" not in transport.commands
    assert b"CN00020;" not in transport.commands
    assert b"CT02;" not in transport.commands


def test_offset_readback_mismatch_stops_before_ctcss() -> None:
    radio, transport = connected_radio()
    transport.commands.clear()
    transport.force_replies[b"EX0905;"] = b"EX09050600;"

    with pytest.raises(RadioVerificationError, match="repeater-offset verification failed"):
        radio.configure_fm_repeater(repeater_request())

    assert b"CN00020;" not in transport.commands
    assert b"CT02;" not in transport.commands


def test_ctcss_tone_readback_mismatch_stops_before_enabling_ctcss() -> None:
    radio, transport = connected_radio()
    transport.commands.clear()
    transport.force_replies[b"CN00;"] = b"CN00024;"

    with pytest.raises(RadioVerificationError, match="CTCSS-tone verification failed"):
        radio.configure_fm_repeater(repeater_request())

    assert b"CT02;" not in transport.commands


class BlockingRepeaterTransport(StatefulRepeaterTransport):
    def __init__(self) -> None:
        super().__init__()
        self.offset_read_started = Event()
        self.release_offset_read = Event()

    def query(self, command: bytes) -> bytes:
        if command != b"EX0905;":
            return super().query(command)

        self.commands.append(command)
        self.offset_read_started.set()
        if not self.release_offset_read.wait(timeout=2.0):
            raise RuntimeError("timed out waiting to release repeater offset read")
        return self.force_replies.get(command, self.replies[command])


def test_refresh_cannot_interleave_with_atomic_repeater_configuration() -> None:
    transport = BlockingRepeaterTransport()
    radio = Ft891Radio(transport, clock=fixed_clock)
    radio.connect()
    transport.commands.clear()

    configure_results: list[object] = []
    refresh_results: list[RadioState] = []
    errors: list[RadioError] = []

    def configure() -> None:
        try:
            configure_results.append(radio.configure_fm_repeater(repeater_request()))
        except RadioError as error:
            errors.append(error)

    def refresh() -> None:
        try:
            refresh_results.append(radio.refresh_state())
        except RadioError as error:
            errors.append(error)

    configure_thread = Thread(target=configure)
    configure_thread.start()
    assert transport.offset_read_started.wait(timeout=1.0)

    refresh_thread = Thread(target=refresh)
    refresh_thread.start()
    refresh_thread.join(timeout=0.2)

    assert refresh_thread.is_alive()
    assert transport.commands[-1] == b"EX0905;"

    transport.release_offset_read.set()
    configure_thread.join(timeout=1.0)
    refresh_thread.join(timeout=1.0)

    assert not configure_thread.is_alive()
    assert not refresh_thread.is_alive()
    assert errors == []
    assert len(configure_results) == 1
    assert len(refresh_results) == 1
    assert transport.commands[-2:] == [b"FA;", b"MD0;"]
