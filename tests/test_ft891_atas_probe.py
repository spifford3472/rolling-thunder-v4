"""Tests for the isolated FT-891 ATAS CAT bench probe."""

import pytest

from rolling_thunder.ft891_atas_probe import (
    AtasProbeDirection,
    AtasProbeOrder,
    AtasProbeRequest,
    AtasProbeSafetyError,
    run_atas_probe,
)


class FakeTransport:
    def __init__(self, replies: dict[bytes, bytes]) -> None:
        self.replies = replies
        self.events: list[tuple[str, bytes] | tuple[str]] = []
        self.opened = False

    def open(self) -> None:
        self.opened = True
        self.events.append(("open",))

    def close(self) -> None:
        self.opened = False
        self.events.append(("close",))

    def query(self, command: bytes) -> bytes:
        self.events.append(("query", command))
        return self.replies[command]

    def command(self, command: bytes) -> None:
        self.events.append(("command", command))


def _replies() -> dict[bytes, bytes]:
    return {
        b"TX;": b"TX0;",
        b"FA;": b"FA014250000;",
        b"MD0;": b"MD02;",
        b"RM6;": b"RM6007;",
        b"RM5;": b"RM5021;",
    }


def test_ptt_first_probe_orders_commands_and_forces_receive() -> None:
    transport = FakeTransport(_replies())
    tx_reads = iter((b"TX0;", b"TX1;"))

    def query(command: bytes) -> bytes:
        transport.events.append(("query", command))
        if command == b"TX;":
            return next(tx_reads)
        return transport.replies[command]

    transport.query = query  # type: ignore[method-assign]
    sleeps: list[float] = []

    result = run_atas_probe(
        transport,
        AtasProbeRequest(
            direction=AtasProbeDirection.UP,
            order=AtasProbeOrder.PTT_FIRST,
            inter_command_delay_ms=50,
            meter_settle_ms=100,
        ),
        sleeper=sleeps.append,
    )

    assert result.swr_meter_raw == 7
    assert result.power_meter_raw == 21
    assert sleeps == [0.05, 0.1]
    assert transport.events == [
        ("open",),
        ("query", b"TX;"),
        ("query", b"FA;"),
        ("query", b"MD0;"),
        ("command", b"TX1;"),
        ("command", b"UP;"),
        ("query", b"TX;"),
        ("query", b"RM6;"),
        ("query", b"RM5;"),
        ("command", b"RX;"),
        ("command", b"TX0;"),
        ("close",),
    ]


def test_control_first_probe_places_direction_before_ptt() -> None:
    transport = FakeTransport(_replies())
    tx_reads = iter((b"TX0;", b"TX1;"))

    def query(command: bytes) -> bytes:
        transport.events.append(("query", command))
        if command == b"TX;":
            return next(tx_reads)
        return transport.replies[command]

    transport.query = query  # type: ignore[method-assign]

    run_atas_probe(
        transport,
        AtasProbeRequest(
            direction=AtasProbeDirection.DOWN,
            order=AtasProbeOrder.CONTROL_FIRST,
            inter_command_delay_ms=0,
            meter_settle_ms=0,
        ),
        sleeper=lambda _seconds: None,
    )

    assert transport.events[4:6] == [
        ("command", b"DN;"),
        ("command", b"TX1;"),
    ]
    assert transport.events[-3:] == [
        ("command", b"RX;"),
        ("command", b"TX0;"),
        ("close",),
    ]


def test_probe_refuses_when_radio_is_already_transmitting() -> None:
    replies = _replies()
    replies[b"TX;"] = b"TX2;"
    transport = FakeTransport(replies)

    with pytest.raises(AtasProbeSafetyError, match="not idle before probe"):
        run_atas_probe(
            transport,
            AtasProbeRequest(
                direction=AtasProbeDirection.UP,
                order=AtasProbeOrder.PTT_FIRST,
            ),
            sleeper=lambda _seconds: None,
        )

    assert ("command", b"TX1;") not in transport.events
    assert transport.events[-1] == ("close",)


def test_probe_forces_receive_when_meter_query_fails() -> None:
    transport = FakeTransport(_replies())
    tx_reads = iter((b"TX0;", b"TX1;"))

    def query(command: bytes) -> bytes:
        transport.events.append(("query", command))
        if command == b"TX;":
            return next(tx_reads)
        if command == b"RM6;":
            raise RuntimeError("meter failure")
        return transport.replies[command]

    transport.query = query  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="meter failure"):
        run_atas_probe(
            transport,
            AtasProbeRequest(
                direction=AtasProbeDirection.UP,
                order=AtasProbeOrder.PTT_FIRST,
                inter_command_delay_ms=0,
                meter_settle_ms=0,
            ),
            sleeper=lambda _seconds: None,
        )

    assert transport.events[-3:] == [
        ("command", b"RX;"),
        ("command", b"TX0;"),
        ("close",),
    ]


@pytest.mark.parametrize(
    ("delay", "settle"),
    [(-1, 0), (501, 0), (0, -1), (0, 501)],
)
def test_probe_request_bounds_delays(delay: int, settle: int) -> None:
    with pytest.raises(ValueError):
        AtasProbeRequest(
            direction=AtasProbeDirection.UP,
            order=AtasProbeOrder.PTT_FIRST,
            inter_command_delay_ms=delay,
            meter_settle_ms=settle,
        )
