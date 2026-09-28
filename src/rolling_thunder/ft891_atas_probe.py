"""Isolated, explicit FT-891 CAT bench probe for ATAS control research.

This module is intentionally not wired into the Rolling Thunder Radio protocol,
runtime, UI, physical controls, voice controls, or ReceiveTuningService.
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from time import sleep as _sleep

from rolling_thunder.cat_transport import CatTransport
from rolling_thunder.domain import Frequency, RadioMode
from rolling_thunder.ft891_cat import (
    encode_cat_ptt_off,
    encode_cat_ptt_on,
    encode_force_receive,
    encode_mic_down,
    encode_mic_up,
    encode_read_frequency,
    encode_read_mode,
    encode_read_power_meter,
    encode_read_swr_meter,
    encode_read_tx_state,
    parse_frequency_reply,
    parse_meter_reply,
    parse_mode_reply,
    parse_tx_state_reply,
)
from rolling_thunder.radio import RadioConnectionError

Sleeper = Callable[[float], None]


class AtasProbeDirection(StrEnum):
    """Single front-panel microphone direction to test."""

    UP = "up"
    DOWN = "down"


class AtasProbeOrder(StrEnum):
    """Ordering experiment for the two CAT actions."""

    PTT_FIRST = "ptt-first"
    CONTROL_FIRST = "control-first"


@dataclass(frozen=True)
class AtasProbeRequest:
    """One deliberately bounded bench experiment."""

    direction: AtasProbeDirection
    order: AtasProbeOrder
    inter_command_delay_ms: int = 50
    keyed_duration_s: float = 3.0
    direction_repeat_interval_ms: int = 150

    def __post_init__(self) -> None:
        if not 0 <= self.inter_command_delay_ms <= 500:
            raise ValueError("inter_command_delay_ms must be between 0 and 500")
        if not 0.5 <= self.keyed_duration_s <= 3.0:
            raise ValueError("keyed_duration_s must be between 0.5 and 3.0")
        if not 100 <= self.direction_repeat_interval_ms <= 500:
            raise ValueError("direction_repeat_interval_ms must be between 100 and 500")


@dataclass(frozen=True)
class AtasProbeResult:
    """Observed state from one probe; meter values remain raw Yaesu 0-255 values."""

    frequency: Frequency
    mode: RadioMode
    tx_state_while_keyed: int
    swr_meter_raw: int
    power_meter_raw: int


class AtasProbeSafetyError(RuntimeError):
    """Raised when a bench precondition fails closed."""


def _direction_command(direction: AtasProbeDirection) -> bytes:
    return encode_mic_up() if direction is AtasProbeDirection.UP else encode_mic_down()


def run_atas_probe(
    transport: CatTransport,
    request: AtasProbeRequest,
    *,
    sleeper: Sleeper = _sleep,
) -> AtasProbeResult:
    """Run exactly one short PTT/UP-or-DOWN experiment and always force RX afterward."""
    if not isinstance(request, AtasProbeRequest):
        raise TypeError("request must be an AtasProbeRequest")

    transport.open()
    try:
        initial_tx_state = parse_tx_state_reply(transport.query(encode_read_tx_state()))
        if initial_tx_state != 0:
            raise AtasProbeSafetyError(
                f"FT-891 is not idle before probe (TX state {initial_tx_state}); aborting."
            )

        frequency = parse_frequency_reply(transport.query(encode_read_frequency()))
        mode = parse_mode_reply(transport.query(encode_read_mode()))
        direction_command = _direction_command(request.direction)

        if request.order is AtasProbeOrder.CONTROL_FIRST:
            transport.command(direction_command)
            sleeper(request.inter_command_delay_ms / 1000)

        try:
            transport.command(encode_cat_ptt_on())

            if request.order is AtasProbeOrder.PTT_FIRST:
                sleeper(request.inter_command_delay_ms / 1000)

            repeat_interval_s = request.direction_repeat_interval_ms / 1000
            remaining_s = request.keyed_duration_s
            while remaining_s > 0:
                transport.command(direction_command)
                sleep_s = min(repeat_interval_s, remaining_s)
                sleeper(sleep_s)
                remaining_s -= sleep_s

            tx_state = parse_tx_state_reply(transport.query(encode_read_tx_state()))
            if tx_state != 1:
                raise AtasProbeSafetyError(
                    f"CAT PTT did not read back as TX1 (reported TX{tx_state}); aborting."
                )

            swr_raw = parse_meter_reply(
                transport.query(encode_read_swr_meter()),
                expected_meter=6,
            )
            power_raw = parse_meter_reply(
                transport.query(encode_read_power_meter()),
                expected_meter=5,
            )
        finally:
            _force_receive(transport)

        return AtasProbeResult(
            frequency=frequency,
            mode=mode,
            tx_state_while_keyed=tx_state,
            swr_meter_raw=swr_raw,
            power_meter_raw=power_raw,
        )
    finally:
        transport.close()


def _force_receive(transport: CatTransport) -> None:
    """Best-effort double unkey: bench-verified RX plus documented TX0."""
    errors: list[Exception] = []
    for command in (encode_force_receive(), encode_cat_ptt_off()):
        try:
            transport.command(command)
        except (RadioConnectionError, OSError) as error:
            errors.append(error)
    if len(errors) == 2:
        raise RadioConnectionError(
            "FT-891 emergency unkey commands both failed: "
            + "; ".join(str(error) for error in errors)
        )
