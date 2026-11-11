"""Exclusive MeshCore serial owner for passive observations and optional inbox.

By default it is receive-only. Explicit opt-in permits only firmware-local
channel-identity queries and saved-message dequeue; never any RF send opcode.
"""

import logging
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

import serial

from rolling_thunder.meshcore_broker_drain import MeshcoreBrokerDrain
from rolling_thunder.meshcore_inbound_frames import MeshcoreInboundFrames
from rolling_thunder.meshcore_passive_worker import (
    MeshcorePassiveWorker,
    MeshcoreWorkerStatus,
)

_LOGGER = logging.getLogger(__name__)
_TTY_PATTERN = re.compile(r"tty(?:USB|ACM)[0-9]+")
# Validated USB transport identities; do not treat an arbitrary CDC port as MeshCore.
_ALLOWED_USB_IDENTITIES = {
    ("ttyUSB", "10c4", "ea60"),  # Legacy Heltec V3 CP2102 bridge.
    ("ttyACM", "303a", "0002"),  # Heltec V4 ESP32-S3 native USB CDC.
}


def validate_meshcore_usb_path(device_path: Path) -> Path:
    """Validate an explicit MeshCore physical-port selector and USB family.

    The earlier Heltec V3 reused a generic CP2102 serial identifier. The
    replacement Heltec V4 presents native Espressif CDC ACM. Refuse numbered
    ports, by-id aliases and mismatched USB descriptor/tty combinations.
    This cannot establish the installed firmware role or version.
    """
    if device_path.parent != Path("/dev/serial/by-path"):
        raise ValueError("MeshCore must use /dev/serial/by-path device identity")
    if not device_path.is_symlink():
        raise OSError("MeshCore USB path is not present")
    resolved = device_path.resolve(strict=True)
    if resolved.parent != Path("/dev") or not _TTY_PATTERN.fullmatch(resolved.name):
        raise ValueError("MeshCore path does not identify a USB serial interface")

    sys_dev = (Path("/sys/class/tty") / resolved.name / "device").resolve(strict=True)
    _require_supported_usb_identity(resolved.name, sys_dev)
    return resolved


def _require_supported_usb_identity(tty_name: str, sys_dev: Path) -> None:
    """Match USB vendor/product and tty transport without trusting by-id links."""
    # The physical USB device is an ancestor of the interface/tty adapter.
    candidate = sys_dev
    for _ in range(8):
        vendor = candidate / "idVendor"
        product = candidate / "idProduct"
        if vendor.is_file() and product.is_file():
            tty_kind = "ttyACM" if tty_name.startswith("ttyACM") else "ttyUSB"
            identity = (
                tty_kind,
                vendor.read_text(encoding="utf-8").strip().lower(),
                product.read_text(encoding="utf-8").strip().lower(),
            )
            if identity not in _ALLOWED_USB_IDENTITIES:
                raise ValueError("Configured MeshCore port USB family is not allowed")
            return
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


@runtime_checkable
class LocalCommandPort(ByteReader, Protocol):
    """Optional host-local companion command capability; no RF interface."""

    def write(self, payload: bytes) -> int | None:
        """Write a single pre-approved, framed local firmware request."""
        ...


def open_meshcore_read_only(device_path: Path) -> ByteReader:
    """Open a validated USB serial interface without emitting command frames.

    Legacy CP2102 uses DTR low; the V4 native ESP32 CDC requires DTR high
    before sending replies. This is USB control signaling, not an RF command.
    Parked hardware acceptance remains required.
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
    port.dtr = resolved.name.startswith("ttyACM")
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
        broker_drain: MeshcoreBrokerDrain | None = None,
    ) -> None:
        self._worker = worker
        self._device_path = device_path
        self._reader_factory = reader_factory
        self._broker_drain = broker_drain
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
                # The opt-in broker cannot assume that every fake/read-only
                # adapter has a write method. No command is issued by default.
                if self._broker_drain is not None:
                    if not isinstance(reader, LocalCommandPort):
                        raise ValueError("Broker requires a local serial writer")
                    self._broker_drain.connected()
                decoder = MeshcoreInboundFrames()
                with self._lock:
                    self._connected = True
                    self._last_error = None
                while not self._stop.is_set():
                    data = reader.read(256)
                    if data:
                        for payload in decoder.feed(data):
                            if (
                                self._broker_drain is not None
                                and self._broker_drain.receive(payload)
                            ):
                                continue
                            self._worker.offer(payload)
                    if (
                        self._broker_drain is not None
                        and isinstance(reader, LocalCommandPort)
                    ):
                        self._broker_drain.tick(reader)
                    if not data:
                        self._stop.wait(0.05)
            except (OSError, ValueError, serial.SerialException) as error:
                with self._lock:
                    self._last_error = type(error).__name__
                _LOGGER.warning("MeshCore receiver unavailable: %s", error)
            finally:
                if self._broker_drain is not None:
                    self._broker_drain.disconnected()
                with self._lock:
                    self._connected = False
                if reader is not None:
                    reader.close()
            if not self._stop.is_set():
                self._stop.wait(5.0)
