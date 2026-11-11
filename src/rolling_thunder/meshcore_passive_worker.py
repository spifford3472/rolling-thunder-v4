"""Opt-in, transport-free bounded work queue for passive MeshCore observations.

The worker owns neither USB nor radio. A future verified read-only adapter may
submit already-deframed push payloads; no transport bootstrap is implemented.
"""

import logging
import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from rolling_thunder.gps import GPSState
from rolling_thunder.meshcore_passive import (
    MeshcoreObservation,
    parse_passive_notification,
)

_LOGGER = logging.getLogger(__name__)


class ObservationSink(Protocol):
    """Small persistence boundary for a replaceable/testable writer."""

    def record(
        self, event: MeshcoreObservation, received_at: datetime, gps_state: GPSState | None
    ) -> int:
        """Write one observation and return its identifier."""
        ...


@dataclass(frozen=True, slots=True)
class MeshcoreWorkerStatus:
    """Immutable telemetry, suitable for future read-only UI consumption."""

    running: bool
    received: int
    stored: int
    dropped: int
    malformed_or_unsupported: int
    write_errors: int
    queued: int


@dataclass(frozen=True, slots=True)
class _ReceivedFrame:
    payload: bytes
    received_at: datetime
    gps_state: GPSState | None


class MeshcorePassiveWorker:
    """Bounded nonblocking collector decoupled from any serial device.

    The caller timestamps and snapshots GPS at receipt, not at disk-write time.
    """

    def __init__(
        self,
        sink: ObservationSink,
        gps_snapshot: Callable[[], GPSState | None],
        *,
        capacity: int = 256,
    ) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self._sink = sink
        self._gps_snapshot = gps_snapshot
        self._queue: queue.Queue[_ReceivedFrame] = queue.Queue(maxsize=capacity)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._received = 0
        self._stored = 0
        self._dropped = 0
        self._ignored = 0
        self._errors = 0

    def start(self) -> None:
        """Start exactly one writer; does not open or configure hardware."""
        with self._lock:
            if self._thread is not None:
                raise RuntimeError("Worker already started")
            self._stop.clear()
            thread = threading.Thread(
                target=self._run, name="meshcore-passive-writer", daemon=False
            )
            self._thread = thread
            thread.start()

    def offer(
        self, payload: bytes, *, received_at: datetime | None = None
    ) -> bool:
        """Never block a serial reader; reject when disabled or saturated."""
        received = received_at or datetime.now(UTC)
        if received.tzinfo is None or received.utcoffset() is None:
            raise ValueError("Received time must be timezone-aware")
        with self._lock:
            if self._thread is None or self._stop.is_set():
                return False
        # Obtain only the immutable shared snapshot; never read GPS hardware.
        location = self._gps_snapshot()
        frame = _ReceivedFrame(bytes(payload), received, location)
        with self._lock:
            self._received += 1
            try:
                self._queue.put_nowait(frame)
            except queue.Full:
                self._dropped += 1
                return False
        return True

    def stop(self, *, timeout_s: float = 5.0) -> None:
        """Drain in order, then shut down; surface a stuck worker."""
        if timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        with self._lock:
            thread = self._thread
            if thread is None:
                return
            self._stop.set()
        thread.join(timeout_s)
        if thread.is_alive():
            raise RuntimeError("MeshCore worker did not stop within deadline")
        with self._lock:
            self._thread = None

    def status(self) -> MeshcoreWorkerStatus:
        """Read counters without blocking on disk or serial operations."""
        with self._lock:
            thread = self._thread
            return MeshcoreWorkerStatus(
                running=thread is not None and thread.is_alive(),
                received=self._received,
                stored=self._stored,
                dropped=self._dropped,
                malformed_or_unsupported=self._ignored,
                write_errors=self._errors,
                queued=self._queue.qsize(),
            )

    def _run(self) -> None:
        while not self._stop.is_set() or not self._queue.empty():
            try:
                frame = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                parsed = parse_passive_notification(frame.payload)
                if parsed is None:
                    with self._lock:
                        self._ignored += 1
                    continue
                self._sink.record(parsed, frame.received_at, frame.gps_state)
                with self._lock:
                    self._stored += 1
            except Exception:  # noqa: BLE001 - keep writer alive on storage errors
                _LOGGER.exception("Passive MeshCore observation write failed")
                with self._lock:
                    self._errors += 1
            finally:
                self._queue.task_done()
