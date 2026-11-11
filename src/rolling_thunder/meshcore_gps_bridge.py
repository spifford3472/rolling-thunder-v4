"""Best-effort publication of Rolling Thunder's existing GPS state.

The GPS polling listener only enqueues; an isolated worker serializes a
bounded snapshot to an atomic file. No extra GPS receiver is created.
"""
from __future__ import annotations

import json
import logging
import os
import queue
import threading
from datetime import UTC, datetime
from pathlib import Path

from rolling_thunder.domain import GPSFixState, GPSPosition
from rolling_thunder.gps import GPSConnectionState, GPSState

_LOGGER = logging.getLogger(__name__)


class MeshcoreGpsPublisher:
    """Nonblocking snapshot sink isolated from GPS/radio polling."""

    def __init__(self, target: Path) -> None:
        self._target = target
        self._pending: queue.Queue[GPSState] = queue.Queue(maxsize=1)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the file I/O worker, not another GPS pipeline."""
        if self._thread is not None:
            raise RuntimeError("GPS snapshot publisher already started")
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="meshcore-gps-publisher", daemon=True
        )
        self._thread.start()

    def offer(self, state: GPSState) -> None:
        """Take newest state without blocking the GPS polling scheduler."""
        if self._thread is None or self._stop.is_set():
            return
        try:
            self._pending.put_nowait(state)
        except queue.Full:
            try:
                self._pending.get_nowait()
                self._pending.task_done()
            except queue.Empty:
                pass
            try:
                self._pending.put_nowait(state)
            except queue.Full:
                pass

    def stop(self) -> None:
        """Stop publishing; stale fixes are rejected by the reader."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                state = self._pending.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                position = state.position
                payload = {
                    "connection": state.connection_state.value,
                    "published_at": datetime.now(UTC).isoformat(),
                    "fix": position.fix_state.value if position else None,
                    "latitude": position.latitude if position else None,
                    "longitude": position.longitude if position else None,
                    "accuracy_m": position.accuracy_m if position else None,
                    "updated_at": position.updated_at.isoformat() if position else None,
                }
                self._target.parent.mkdir(parents=True, exist_ok=True)
                temporary = self._target.with_name(self._target.name + ".tmp")
                with temporary.open("w", encoding="utf-8") as output:
                    json.dump(payload, output, allow_nan=False)
                os.chmod(temporary, 0o600)
                temporary.replace(self._target)
            except (OSError, ValueError, TypeError) as error:
                _LOGGER.warning("MeshCore GPS publication unavailable: %s", error)
            finally:
                self._pending.task_done()


def read_meshcore_gps_snapshot(source: Path) -> GPSState | None:
    """Read an existing GPS snapshot; reject stale or invalid published data."""
    try:
        if source.stat().st_size > 2048:
            return None
        data = json.loads(source.read_text(encoding="utf-8"))
        published_at = datetime.fromisoformat(data["published_at"])
        if published_at.tzinfo is None:
            return None
        age = (datetime.now(UTC) - published_at).total_seconds()
        if age < 0 or age > 10:
            return None
        if data["connection"] != GPSConnectionState.CONNECTED.value:
            return None
        if data["fix"] not in (
            GPSFixState.TWO_DIMENSIONAL.value,
            GPSFixState.THREE_DIMENSIONAL.value,
        ):
            return None
        position = GPSPosition(
            fix_state=GPSFixState(data["fix"]),
            latitude=data["latitude"],
            longitude=data["longitude"],
            accuracy_m=data["accuracy_m"],
            updated_at=datetime.fromisoformat(data["updated_at"]),
        )
        return GPSState(
            connection_state=GPSConnectionState.CONNECTED,
            position=position,
            updated_at=published_at,
        )
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return None
