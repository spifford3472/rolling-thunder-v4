"""Off-Tk serial lifecycle and expiring queue tests using bounded fake devices."""

from collections import deque
from pathlib import Path
from threading import Event, Lock, get_ident
from time import monotonic, sleep

import pytest

from rolling_thunder.control_transport_health import TransportHealthState as State
from rolling_thunder.recovering_control_source import RecoveringControlSource
from rolling_thunder.serial_control_source import SerialControlError

N = "a" * 32
B = "b" * 16


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class Port:
    def __init__(self, clock: Clock) -> None:
        self.clock = clock
        self.data = bytearray()
        self.lock = Lock()
        self.owners: set[int] = set()
        self.closed = False
        self.fail = False
        self.respond = True
        self.partial_write = False
        self.nonce = N
        self.seq = 0
        self.writes: list[bytes] = []

    @property
    def in_waiting(self) -> int:
        self.owners.add(get_ident())
        if self.fail:
            raise OSError("unplugged")
        with self.lock:
            return len(self.data)

    def read(self, size: int) -> bytes:
        self.owners.add(get_ident())
        with self.lock:
            value = bytes(self.data[:size])
            del self.data[:size]
            return value

    def write(self, data: bytes) -> int:
        self.owners.add(get_ident())
        if self.partial_write:
            return 0
        self.writes.append(data)
        fields = data.decode().split()
        uptime = int(self.clock() * 1000)
        if fields[1] == "HELLO":
            self.nonce = fields[2]
            self.seq = 0
            self.feed(f"RTCTRL/2 READY {self.nonce} {B} 2.0.0 0 {uptime}\n".encode())
        elif self.respond:
            self.feed(f"RTCTRL/2 PONG {self.nonce} {B} {fields[3]} {self.seq} {uptime}\n".encode())
        return len(data)

    def reset_input_buffer(self) -> None:
        self.owners.add(get_ident())
        with self.lock:
            self.data.clear()

    def close(self) -> None:
        self.owners.add(get_ident())
        self.closed = True

    def feed(self, data: bytes) -> None:
        with self.lock:
            self.data.extend(data)

    def emit(self, sequence: int = 1, *, nonce: str | None = None) -> None:
        self.seq = max(self.seq, sequence)
        self.feed(
            f"RTCTRL/2 EVENT {nonce or self.nonce} {B} {sequence} {int(self.clock() * 1000)} voice-button\n".encode()
        )


def wait_for(check) -> None:
    deadline = monotonic() + 2
    while not check():
        if monotonic() >= deadline:
            raise AssertionError("Fake worker did not reach expected state")
        sleep(0.001)


def source(clock: Clock, factory, **kwargs) -> RecoveringControlSource:
    return RecoveringControlSource(
        Path("/dev/fake-controls"),
        frozenset({"voice-button"}),
        port_factory=factory,
        clock=clock,
        settle_s=0,
        poll_interval_s=0.001,
        nonce_factory=lambda: N,
        **kwargs,
    )


def test_open_failure_recovery_and_every_io_runs_off_caller_thread() -> None:
    clock = Clock()
    port = Port(clock)
    attempts = []

    def factory(_device, _baud):
        attempts.append(get_ident())
        if len(attempts) == 1:
            raise OSError("not present")
        return port

    s = source(clock, factory)
    try:
        s.open()
        wait_for(lambda: s.snapshot.health.next_retry_at == 0.5)
        clock.now = 0.5
        wait_for(lambda: s.snapshot.health.state is State.HEALTHY)
        port.emit()
        wait_for(lambda: s.snapshot.queue_depth == 1)
        assert [e.input_id for e in s.drain()] == ["voice-button"]
        port.emit()
        wait_for(lambda: not port.data)
        assert s.drain() == ()
    finally:
        s.close()
        assert s.wait_closed()
    assert len(set(attempts)) == 1 and attempts[0] != get_ident()
    assert port.owners == set(attempts)
    assert port.closed


def test_ui_stall_expires_queue_without_replaying_input() -> None:
    clock = Clock()
    port = Port(clock)
    s = source(clock, lambda *_: port)
    try:
        s.open()
        wait_for(lambda: s.snapshot.health.state is State.HEALTHY)
        port.emit()
        wait_for(lambda: s.snapshot.queue_depth == 1)
        clock.now = 0.3
        assert s.drain() == ()
        assert s.snapshot.dropped_events >= 1
    finally:
        s.close()
        assert s.wait_closed()


def test_disconnect_clears_queue_and_uses_fresh_session_on_reopen() -> None:
    clock = Clock()
    ports = deque([Port(clock), Port(clock)])
    first, second = ports
    nonces = iter([N, "c" * 32])
    s = RecoveringControlSource(
        Path("/dev/fake"),
        frozenset({"voice-button"}),
        port_factory=lambda *_: ports.popleft(),
        clock=clock,
        nonce_factory=lambda: next(nonces),
        settle_s=0,
        poll_interval_s=0.001,
    )
    try:
        s.open()
        wait_for(lambda: s.snapshot.health.state is State.HEALTHY)
        first.emit()
        wait_for(lambda: s.snapshot.queue_depth == 1)
        first.fail = True
        wait_for(lambda: s.snapshot.health.state is State.BACKOFF)
        assert s.drain() == () and first.closed
        clock.now = 0.5
        wait_for(lambda: s.snapshot.health.state is State.HEALTHY)
        second.emit(nonce=N)
        second.emit(sequence=2)
        wait_for(lambda: s.snapshot.queue_depth == 1)
        events = s.drain()
        assert len(events) == 1 and events[0].event_id.startswith("c" * 32)
    finally:
        s.close()
        assert s.wait_closed()


def test_stop_during_blocked_open_returns_promptly_no_second_owner_or_late_publish() -> None:
    clock = Clock()
    port = Port(clock)
    entered, release = Event(), Event()

    def factory(*_):
        entered.set()
        assert release.wait(2)
        return port

    s = source(clock, factory)
    s.open()
    assert entered.wait(1)
    clock.now = 3.1
    assert s.snapshot.health.state is State.STALE
    assert s.drain() == ()
    started = monotonic()
    s.close()
    assert monotonic() - started < 0.1
    with pytest.raises(SerialControlError, match="shutdown"):
        s.open()
    release.set()
    assert s.wait_closed()
    assert port.closed and s.snapshot.health.state is State.STOPPED
    assert s.drain() == ()


def test_queue_overflow_discards_batch_and_disconnects() -> None:
    clock = Clock()
    port = Port(clock)
    s = source(clock, lambda *_: port, capacity=2)
    try:
        s.open()
        wait_for(lambda: s.snapshot.health.state is State.HEALTHY)
        for i in range(1, 4):
            port.emit(i)
        wait_for(lambda: s.snapshot.health.state is State.BACKOFF)
        assert s.drain() == () and s.snapshot.queue_depth == 0
        assert "overflow" in (s.snapshot.health.last_error or "")
    finally:
        s.close()
        assert s.wait_closed()


def test_oversized_line_tail_cannot_become_an_action() -> None:
    clock = Clock()
    port = Port(clock)
    s = source(clock, lambda *_: port)
    try:
        s.open()
        wait_for(lambda: s.snapshot.health.state is State.HEALTHY)
        port.feed(b"x" * 300 + f"RTCTRL/2 EVENT {N} {B} 1 0 voice-button\n".encode())
        port.emit(2)
        wait_for(lambda: s.snapshot.queue_depth == 1)
        assert s.snapshot.malformed_lines == 1
        assert s.drain()[0].event_id.endswith(":2")
    finally:
        s.close()
        assert s.wait_closed()


@pytest.mark.parametrize("partial", [False, True])
def test_missing_health_or_partial_write_fails_closed(partial: bool) -> None:
    clock = Clock()
    port = Port(clock)
    port.partial_write = partial
    port.respond = False
    s = source(clock, lambda *_: port)
    try:
        s.open()
        if not partial:
            wait_for(lambda: s.snapshot.health.state is State.HEALTHY)
            clock.now = 0.5
        wait_for(lambda: s.snapshot.health.state is State.BACKOFF)
        assert s.drain() == () and port.closed
    finally:
        s.close()
        assert s.wait_closed()


def test_restart_keeps_generation_unique_and_disconnected_status_is_nonblocking() -> None:
    clock = Clock()
    ports = deque([Port(clock), Port(clock)])
    nonces = iter([N, "c" * 32])
    s = RecoveringControlSource(
        Path("/dev/fake"),
        frozenset({"voice-button"}),
        port_factory=lambda *_: ports.popleft(),
        clock=clock,
        nonce_factory=lambda: next(nonces),
        settle_s=0,
        poll_interval_s=0.001,
    )
    s.open()
    wait_for(lambda: s.snapshot.health.state is State.HEALTHY)
    first = s.snapshot.health.generation
    s.close()
    assert s.wait_closed()
    s.open()
    try:
        wait_for(lambda: s.snapshot.health.state is State.HEALTHY)
        second = s.snapshot.health.generation
        assert first is not None and second is not None and second > first
    finally:
        s.close()
        assert s.wait_closed()


@pytest.mark.parametrize("timeout", [-1, 6, float("nan"), float("inf"), True])
def test_shutdown_wait_cannot_be_unbounded(timeout: float) -> None:
    clock = Clock()
    s = source(clock, lambda *_: Port(clock))
    with pytest.raises(ValueError):
        s.wait_closed(timeout)


def test_failed_close_stops_recovery_instead_of_opening_another_descriptor() -> None:
    clock = Clock()

    class BadClose(Port):
        def close(self) -> None:
            raise OSError("close failed")

    port = BadClose(clock)
    calls = []

    def factory(*_):
        calls.append(1)
        return port

    s = source(clock, factory)
    s.open()
    wait_for(lambda: s.snapshot.health.state is State.HEALTHY)
    port.fail = True
    wait_for(lambda: s.snapshot.health.state is State.STOPPED)
    assert s.wait_closed()
    assert len(calls) == 1
    assert "close" in (s.snapshot.health.last_error or "")

    with pytest.raises(SerialControlError, match="close failed"):
        s.open()


def test_slow_open_does_not_consume_firmware_challenge_deadline() -> None:
    clock = Clock()
    port = Port(clock)

    def factory(*_):
        clock.now = 0.6
        return port

    s = source(clock, factory)
    try:
        s.open()
        wait_for(lambda: s.snapshot.health.state is State.HEALTHY)
        assert s.snapshot.health.last_valid_health_at == 0.6
    finally:
        s.close()
        assert s.wait_closed()


def test_default_settling_wait_is_cancellable_without_sending_a_challenge() -> None:
    clock = Clock()
    port = Port(clock)
    entered = Event()

    def factory(*_):
        entered.set()
        return port

    s = RecoveringControlSource(
        Path("/dev/fake"),
        frozenset({"voice-button"}),
        port_factory=factory,
        clock=clock,
        poll_interval_s=0.001,
    )
    s.open()
    assert entered.wait(1)
    s.close()
    assert s.wait_closed(0.2)
    assert port.closed and port.writes == []


def test_factory_gate_dispatches_once_only_while_published_session_is_current() -> None:
    from rolling_thunder.config import PhysicalControlsConfig
    from rolling_thunder.control_source_factory import build_control_gate

    clock = Clock()
    port = Port(clock)
    s = source(clock, lambda *_: port)
    config = PhysicalControlsConfig(mappings={"voice-button": "voice"}, repeat_suppression_s=0)
    gate = build_control_gate(config, s)
    try:
        s.open()
        wait_for(lambda: s.snapshot.health.state is State.HEALTHY)
        assert s.snapshot.session_nonce == N
        port.emit()
        wait_for(lambda: s.snapshot.queue_depth == 1)
        event = s.drain()[0]
        assert gate.accept(event)
        assert not gate.accept(event)
        s.close()
        assert not gate.accept(event)
    finally:
        s.close()
        assert s.wait_closed()
