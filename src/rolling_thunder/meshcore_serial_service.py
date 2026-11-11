"""Opt-in MeshCore companion serial receive service with no outgoing commands.

This adapter is intentionally read-only at the application protocol level.
Firmware-managed mesh RF is independent and owner-permitted; this implementation
cannot issue MeshCore advertisements, discovery, text, config or trace commands.
"""

import logging
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import serial

from rolling_thunder.gps import GPSState
from rolling_thunder.meshcore_inbound_frames import MeshcoreInboundFrames
from rolling_thunder.meshcore_passive_worker import (
    MeshcorePassiveWorker,
    MeshcoreWorkerStatus,
)

_LOGGER = logging.getLogger(__name__)
_TTY_PATTERN = re.compile(r"ttyUSB[0-9]+")


def validate_meshcore_usb_path(device_path: Path) -> Path:
    """Bind to a physical USB port, not a duplicate CP2102 serial number.

    The connected receiver has the same generic CP2102 serial ID as another
    device already used by Rolling Thunder. Reject `by-id` and numbered tty
    selectors to avoid stealing the FT-891/controller or GPS interface.
    """
    if device_path.parent != Path("/dev/serial/by-path"):
        raise ValueError("MeshCore must use /dev/serial/by-path device identity")
    if not device_path.is_symlink():
        raise OSError("MeshCore USB path is not present")
    resolved = device_path.resolve(strict=True)
    if resolved.parent != Path("/dev") or not _TTY_PATTERN.fullmatch(resolved.name):
        raise ValueError("MeshCore path does not identify a USB serial interface")

    sys_dev = (Path("/sys/class/tty") / resolved.name / "device").resolve(strict=True)
    # The physical USB device node is above the interface and tty adapter.
    candidate = sys_dev
    for _ in range(5):
        vendor = candidate / "idVendor"
        product = candidate / "idProduct"
        if vendor.is_file() and product.is_file():
            if vendor.read_text().strip().lower() != "10c4" or (
                product.read_text().strip().lower() != "ea60"
            ):
                raise ValueError("Configured MeshCore port is not a CP2102")
            return resolved
        if candidate.parent == candidate:
            break
        candidate = candidate.parent
    raise OSError("MeshCore USB device descriptor could not be validated")


class ByteReader(Protocol):
    """Injectable blocking read/close boundary for hardware-free tests."""

    def read(self, size: int) -> bytes:
        """Read zero or more bytes within the adapter's configured timeout."""
        ...

    def close(self) -> None:
        """Close the receive connection."""
        ...


def open_meshcore_read_only(device_path: Path) -> ByteReader:
    """Open validated UART exclusively without emitting command frames.

    DTR and RTS are deasserted before port open; some bridges may still pulse
    them during OS initialization, so parked device acceptance is required.
    """
    resolved = validate_meshcore_usb_path(device_path)
    port = serial.Serial(
        port=None,
        baudrate=115_200,
        timeout=0.25,
        exclusive=True,
        rtscts=False,
        dsrdtr=False,
    )
    port.dtr = False
    port.rts = False
    port.port = str(resolved)
    port.open()
    return port


@dataclass(frozen=True, slots=True)
class MeshcoreSerialStatus:
    """Read-only runtime health without exposing raw MeshCore messages."""

    running: bool
    device_connected: bool
    last_error: str | None
    worker: MeshcoreWorkerStatus


class MeshcorePassiveSerialService:
    """One exclusively owned serial reader feeding the bounded SQLite worker."""

    def __init__(
        self,
        worker: MeshcorePassiveWorker,
        device_path: Path,
        *,
        reader_factory: Callable[[Path], ByteReader] = open_meshcore_read_only,
    ) -> None:
        self._worker = worker
        self._device_path = device_path
        self._reader_factory = reader_factory
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._connected = False
        self._last_error: str | None = None

    def start(self) -> None:
        """Start in background so UART open/read can never block Tk startup."""
        if self._thread is not None:
            raise RuntimeError("MeshCore receiver already started")
        self._worker.start()
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._read_loop,
            name="meshcore-passive-serial",
            daemon=False,
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop serial reception first, then drain pending database writes."""
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=3.0)
            if thread.is_alive():
                raise RuntimeError("MeshCore serial reader did not exit")
            self._thread = None
        self._worker.stop(timeout_s=5.0)

    def status(self) -> MeshcoreSerialStatus:
        """Return a bounded immutable status snapshot."""
        with self._lock:
            return MeshcoreSerialStatus(
                running=self._thread is not None and self._thread.is_alive(),
                device_connected=self._connected,
                last_error=self._last_error,
                worker=self._worker.status(),
            )

    def _read_loop(self) -> None:
        while not self._stop.is_set():
            reader: ByteReader | None = None
            try:
                reader = self._reader_factory(self._device_path)
                decoder = MeshcoreInboundFrames()
                with self._lock:
                    self._connected = True
                    self._last_error = None
                while not self._stop.is_set():
                    data = reader.read(256)
                    if data:
                        for payload in decoder.feed(data):
                            self._worker.offer(payload)
                    else:
                        self._stop.wait(0.05)
            except (OSError, ValueError, serial.SerialException) as error:
                with self._lock:
                    self._last_error = type(error).__name__
                _LOGGER.warning("MeshCore receiver unavailable: %s", error)
            finally:
                with self._lock:
                    self._connected = False
                if reader is not None:
                    reader.close()
            if not self._stop.is_set():
                self._stop.wait(5.0)
