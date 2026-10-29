"""Uncomposed off-Tk RTCTRL/2 serial owner with expiring bounded input."""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from secrets import token_hex
from threading import Event as StopEvent
from threading import Lock, Thread
from time import monotonic
from typing import Protocol, cast

import serial

from rolling_thunder.control_protocol import ControlProtocolError
from rolling_thunder.control_protocol_v2 import parse_v2_line
from rolling_thunder.control_session_v2 import ControlSessionError, ControlSessionV2
from rolling_thunder.control_transport_health import (
    ControlTransportHealthPolicy,
    TransportHealthSnapshot,
    TransportHealthState,
)
from rolling_thunder.physical_controls import ControlInputEvent
from rolling_thunder.serial_control_source import SerialControlError


class RecoveryPort(Protocol):
    """Adapter promises nonblocking read/write and bounded open/close."""

    @property
    def in_waiting(self) -> int: ...
    def read(self, size: int) -> bytes: ...
    def write(self, data: bytes) -> int: ...
    def reset_input_buffer(self) -> None: ...
    def close(self) -> None: ...


def _open_port(device: Path, baud: int) -> RecoveryPort:
    port = serial.Serial(port=None, baudrate=baud, timeout=0, write_timeout=0)
    # Request deasserted lines before opening. Driver/board glitches still require
    # physical acceptance; never force an ESP32 reset as recovery policy.
    port.dtr = False
    port.rts = False
    port.port = str(device)
    try:
        port.open()
    except (OSError, serial.SerialException):
        port.close()
        raise
    return cast(RecoveryPort, port)


@dataclass(frozen=True)
class RecoverySnapshot:
    """Published immutable status; port presence alone never means healthy."""

    health: TransportHealthSnapshot
    firmware: str | None = None
    queue_depth: int = 0
    dropped_events: int = 0
    malformed_lines: int = 0
    published_at: float = 0.0
    worker_running: bool = False
    session_nonce: str | None = None


class RecoveringControlSource:
    """One worker owns every serial operation; drain/close do no device I/O.

    Explicit serial_v2 configuration selects this source and its bounded
    session-aware gate. Legacy serial stays the default. Hardware commissioning
    remains required before enabling the matching firmware/configuration.
    """

    def __init__(
        self,
        device: Path,
        inputs: frozenset[str],
        *,
        baud_rate: int = 115_200,
        capacity: int = 32,
        poll_interval_s: float = 0.01,
        settle_s: float = 1.0,
        port_factory: Callable[[Path, int], RecoveryPort] = _open_port,
        clock: Callable[[], float] = monotonic,
        nonce_factory: Callable[[], str] = lambda: token_hex(16),
    ) -> None:
        if not device.is_absolute() or baud_rate <= 0 or not 1 <= capacity <= 1024:
            raise ValueError("Invalid recovery device/baud/capacity")
        if not 0.001 <= poll_interval_s <= 0.1:
            raise ValueError("Invalid recovery polling interval")
        if isinstance(settle_s, bool) or not math.isfinite(settle_s) or not 0 <= settle_s <= 2:
            raise ValueError("Invalid controller settling interval")
        self._settle = settle_s
        self._device = device
        self._inputs = inputs
        self._baud = baud_rate
        self._capacity = capacity
        self._interval = poll_interval_s
        self._factory = port_factory
        self._clock = clock
        self._nonce = nonce_factory
        self._lock = Lock()
        self._stop = StopEvent()
        self._stop.set()
        self._thread: Thread | None = None
        self._queue: deque[tuple[float, int, ControlInputEvent]] = deque()
        self._policy = ControlTransportHealthPolicy()
        self._published = RecoverySnapshot(self._policy.snapshot)
        self._close_fault = False
        self._worker_time = 0.0
        self._dropped = 0
        self._malformed = 0

    @property
    def snapshot(self) -> RecoverySnapshot:
        """Read status without waiting for serial I/O or a worker response."""
        with self._lock:
            return self._snapshot_locked()

    def _snapshot_locked(self) -> RecoverySnapshot:
        snap = self._published
        health = snap.health
        if self._stop.is_set():
            health = replace(
                health, state=TransportHealthState.STOPPED, generation=None, next_retry_at=None
            )
        elif (
            health.state is TransportHealthState.SYNCHRONIZING
            and self._clock() - snap.published_at >= 3
        ):
            health = replace(health, state=TransportHealthState.STALE, generation=None)
        elif (
            health.state is TransportHealthState.HEALTHY and health.last_valid_health_at is not None
        ):
            now = self._clock()
            if (
                not math.isfinite(now)
                or now < health.last_valid_health_at
                or now - health.last_valid_health_at >= 3
            ):
                health = replace(health, state=TransportHealthState.STALE, generation=None)
        return replace(
            snap,
            health=health,
            queue_depth=len(self._queue),
            dropped_events=self._dropped,
            worker_running=self._thread is not None and self._thread.is_alive(),
            session_nonce=snap.session_nonce
            if health.state is TransportHealthState.HEALTHY
            else None,
        )

    def open(self) -> None:
        """Start a worker only; never open a device in the calling/UI thread."""
        with self._lock:
            if self._close_fault:
                raise SerialControlError("Controller close failed; manual recovery is required")
            if self._thread is not None and self._thread.is_alive():
                if self._stop.is_set():
                    raise SerialControlError("Controller shutdown is still pending")
                return
            self._stop = StopEvent()
            self._queue.clear()
            self._thread = Thread(
                target=self._run, args=(self._stop,), daemon=True, name="rt-control-v2"
            )
            self._thread.start()

    def close(self) -> None:
        """Cancel publication immediately; the serial owner closes its own port."""
        with self._lock:
            self._stop.set()
            self._queue.clear()

    def wait_closed(self, timeout_s: float = 1.0) -> bool:
        """Bounded join for tests/non-UI teardown; never call on Tk refresh."""
        if isinstance(timeout_s, bool) or not math.isfinite(timeout_s) or not 0 <= timeout_s <= 5:
            raise ValueError("Shutdown wait must be finite and within0..5seconds")
        thread = self._thread
        if thread is not None:
            thread.join(timeout_s)
        return thread is None or not thread.is_alive()

    def drain(self) -> tuple[ControlInputEvent, ...]:
        """Return only current healthy-generation input before its age deadline."""
        with self._lock:
            snap = self._snapshot_locked()
            if snap.health.state is not TransportHealthState.HEALTHY:
                self._queue.clear()
                return ()
            now = self._clock()
            events: list[ControlInputEvent] = []
            while self._queue:
                expires, generation, event = self._queue.popleft()
                if generation == snap.health.generation and now < expires:
                    events.append(event)
                else:
                    self._dropped += 1
            return tuple(events)

    def _run(self, stop: StopEvent) -> None:
        policy = self._policy

        def worker_now() -> float:
            now = self._clock()
            if isinstance(now, bool) or not math.isfinite(now) or now < self._worker_time:
                raise ControlSessionError("Invalid worker clock")
            self._worker_time = now
            return now

        port: RecoveryPort | None = None
        session: ControlSessionV2 | None = None
        token: int | None = None
        buffer = bytearray()
        discarding = False
        next_ping = 0.0
        terminal_error: str | None = None
        try:
            policy.start(worker_now())
            while not stop.is_set():
                try:
                    now = worker_now()
                    policy.advance(now)
                    if port is not None and policy.snapshot.generation is None:
                        port.close()
                        port = None
                        session = None
                        buffer.clear()
                        discarding = False
                        self._clear_queue()
                    if port is None:
                        token = policy.attempt_if_due(now)
                        if token is not None:
                            with self._lock:
                                if not stop.is_set():
                                    self._published = RecoverySnapshot(
                                        policy.snapshot, published_at=now
                                    )
                            port = self._factory(self._device, self._baud)
                            if stop.wait(self._settle):
                                break
                            policy.advance(worker_now())
                            if policy.snapshot.generation != token:
                                continue
                            port.reset_input_buffer()
                            session = ControlSessionV2(self._nonce(), worker_now(), self._inputs)
                            self._write(port, session.hello)
                            next_ping = self._worker_time
                    if port is not None and session is not None and token is not None:
                        session.check_deadline(worker_now())
                        data = port.read(min(max(port.in_waiting, 0), 4096))
                        for byte in data:
                            if discarding:
                                if byte == 10:
                                    discarding = False
                                continue
                            buffer.append(byte)
                            if len(buffer) > 256:
                                buffer.clear()
                                discarding = byte != 10
                                self._malformed += 1
                                continue
                            if byte != 10:
                                continue
                            raw = bytes(buffer)
                            buffer.clear()
                            try:
                                frame = parse_v2_line(raw)
                            except ControlProtocolError:
                                self._malformed += 1
                                continue
                            result = session.accept(frame, worker_now())
                            if result.health:
                                if policy.snapshot.state is TransportHealthState.SYNCHRONIZING:
                                    policy.validated_session(token, worker_now())
                                else:
                                    policy.heartbeat(token, worker_now())
                            if result.event is not None:
                                with self._lock:
                                    if not stop.is_set():
                                        if len(self._queue) >= self._capacity:
                                            raise ControlSessionError(
                                                "Controller input queue overflow"
                                            )
                                        expires = min(result.expires_at, worker_now() + 0.25)
                                        self._queue.append((expires, token, replace(result.event, expires_at_s=expires)))
                        if (
                            policy.snapshot.state is TransportHealthState.HEALTHY
                            and session.can_ping
                            and worker_now() >= next_ping
                        ):
                            self._write(port, session.ping(worker_now()))
                            next_ping = worker_now() + 0.25
                except (OSError, serial.SerialException, ControlSessionError, ValueError) as error:
                    if token is not None:
                        policy.failed(token, self._worker_time, str(error))
                    self._clear_queue()
                    if port is not None:
                        try:
                            port.close()
                        except (OSError, serial.SerialException) as close_error:
                            terminal_error = f"Could not close controller port: {close_error}"[:256]
                            stop.set()
                    port = None
                    session = None
                    buffer.clear()
                    discarding = False
                with self._lock:
                    if not stop.is_set():
                        self._published = RecoverySnapshot(
                            policy.snapshot,
                            session.firmware if session else None,
                            len(self._queue),
                            self._dropped,
                            self._malformed,
                            self._worker_time,
                            session_nonce=session.nonce if session else None,
                        )
                stop.wait(self._interval)
        finally:
            policy.stop(self._worker_time)
            self._clear_queue()
            if port is not None:
                try:
                    port.close()
                except (OSError, serial.SerialException) as close_error:
                    terminal_error = f"Could not close controller port: {close_error}"[:256]
            with self._lock:
                self._close_fault = terminal_error is not None
                self._published = RecoverySnapshot(
                    replace(
                        policy.snapshot, last_error=terminal_error or policy.snapshot.last_error
                    ),
                    dropped_events=self._dropped,
                    malformed_lines=self._malformed,
                )

    def _clear_queue(self) -> None:
        with self._lock:
            self._dropped += len(self._queue)
            self._queue.clear()

    @staticmethod
    def _write(port: RecoveryPort, data: bytes) -> None:
        if port.write(data) != len(data):
            raise ControlSessionError("Partial controller health write")
