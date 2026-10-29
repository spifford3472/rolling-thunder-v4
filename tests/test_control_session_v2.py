"""Freshness, replay and wire-contract regressions without hardware."""

import pytest

from rolling_thunder.control_protocol import ControlProtocolError
from rolling_thunder.control_protocol_v2 import Event, Pong, Ready, parse_v2_line
from rolling_thunder.control_session_v2 import ControlSessionError, ControlSessionV2

N = "a" * 32
B = "b" * 16
INPUT = "voice-button"


@pytest.mark.parametrize(
    "line,expected",
    [
        (f"RTCTRL/2 READY {N} {B} 2.0.0 0 1000\n", Ready(N, B, "2.0.0", 0, 1000)),
        (f"RTCTRL/2 PONG {N} {B} 1 0 1000\n", Pong(N, B, 1, 0, 1000)),
        (f"RTCTRL/2 EVENT {N} {B} 1 1000 voice-button\r\n", Event(N, B, 1, 1000, INPUT)),
    ],
)
def test_wire_frames(line: str, expected: Ready | Pong | Event) -> None:
    assert parse_v2_line(line.encode()) == expected


@pytest.mark.parametrize(
    "change",
    [
        lambda s: s.rstrip("\n"),
        lambda s: s.replace(" 1 ", " 01 "),
        lambda s: s.replace(" 1 ", " -1 "),
        lambda s: s.replace(" 1 ", " 18446744073709551616 "),
        lambda s: s.replace(N, N.upper()),
        lambda s: s.replace(" PONG ", " PONG  "),
        lambda s: s.replace("\n", "\r\r\n"),
        lambda s: s.replace("\n", "\x00\n"),
        lambda s: "X" * 256 + s,
        lambda s: s.replace("PONG", "BOGUS"),
    ],
)
def test_strict_wire_rejects_malformed(change) -> None:
    with pytest.raises(ControlProtocolError):
        parse_v2_line(change(f"RTCTRL/2 PONG {N} {B} 1 0 1000\n").encode())


def session() -> ControlSessionV2:
    s = ControlSessionV2(N, 10, frozenset({INPUT}))
    assert s.accept(Ready(N, B, "2.0.0", 0, 1000), 10.01).health
    return s


def test_challenge_and_event_age_use_send_bound_not_receive_time() -> None:
    s = session()
    assert s.hello == f"RTCTRL/2 HELLO {N}\n".encode()
    assert s.ping(10.1) == f"RTCTRL/2 PING {N} 1\n".encode()
    assert s.accept(Pong(N, B, 1, 0, 1100), 10.2).health
    result = s.accept(Event(N, B, 1, 1200, INPUT), 10.3)
    assert result.event is not None and result.event.input_id == INPUT
    assert result.expires_at == pytest.approx(10.7)
    assert s.accept(Event(N, B, 1, 1200, INPUT), 10.31).event is None
    with pytest.raises(ControlSessionError):
        s.accept(Event(N, B, 2, 1201, INPUT), 10.71)


def test_wrong_nonce_unknown_input_and_duplicate_cannot_create_actions() -> None:
    s = session()
    assert not s.accept(Event("c" * 32, B, 1, 1010, INPUT), 10.02).health
    assert s.accept(Event(N, B, 1, 1010, "unknown"), 10.02).event is None
    assert s.accept(Event(N, B, 1, 1010, INPUT), 10.02).event is None


@pytest.mark.parametrize(
    "frame",
    [
        Ready(N, B, "2.0.0", 0, 1000),
        Pong(N, B, 77, 0, 1000),
        Event(N, "c" * 16, 1, 1010, INPUT),
        Event(N, B, 1, 999, INPUT),
        Event(N, B, 1, 99999, INPUT),
    ],
)
def test_session_conflicts_fail_closed(frame: Ready | Pong | Event) -> None:
    s = session()
    with pytest.raises(ControlSessionError):
        s.accept(frame, 10.02)


def test_handshake_ping_timeouts_and_clock_regression() -> None:
    s = ControlSessionV2(N, 10, frozenset({INPUT}))
    with pytest.raises(ControlSessionError):
        s.accept(Ready(N, B, "2.0.0", 0, 1000), 10.5)
    s = session()
    s.ping(10.1)
    with pytest.raises(ControlSessionError):
        s.ping(10.2)
    with pytest.raises(ControlSessionError):
        s.accept(Pong(N, B, 1, 0, 1100), 10.6)
    with pytest.raises(ControlSessionError):
        s.check_deadline(9)


@pytest.mark.parametrize("integer", ["0", "18446744073709551615"])
def test_uint64_wire_boundaries(integer: str) -> None:
    frame = parse_v2_line(f"RTCTRL/2 EVENT {N} {B} {integer} {integer} voice-button\n".encode())
    assert isinstance(frame, Event) and frame.sequence == int(integer)


@pytest.mark.parametrize(
    "raw",
    [
        b"\xff\n",
        b"\n",
        b"",
        b"RTCTRL/2 READY\n",
        f"RTCTRL/2 READY {N} {B} 2.0.0 0 0 extra\n".encode(),
        f"RTCTRL/2 EVENT {N} {B} 1 1 {'x' * 65}\n".encode(),
    ],
)
def test_remaining_wire_constraints(raw: bytes) -> None:
    with pytest.raises(ControlProtocolError):
        parse_v2_line(raw)


def test_long_session_keeps_constant_state_and_duplicate_watermark() -> None:
    s = session()
    fields = set(vars(s))
    for i in range(1, 20_001):
        now = 10.01 + i / 1000
        if i % 200 == 0:
            s.ping(now)
            assert s.accept(Pong(N, B, i // 200, i - 1, 1000 + i), now).health
        event = Event(N, B, i, 1000 + i, INPUT)
        assert s.accept(event, now).event is not None
        assert s.accept(event, now).event is None
    assert set(vars(s)) == fields
    assert not any(isinstance(value, (list, dict, set)) for value in vars(s).values())
