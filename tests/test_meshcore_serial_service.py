"""No-hardware tests of the opt-in MeshCore serial receive service."""

from pathlib import Path
from threading import Event

import pytest

from rolling_thunder.meshcore_passive_worker import MeshcorePassiveWorker
from rolling_thunder.meshcore_serial_service import (
    MeshcorePassiveSerialService,
    validate_meshcore_usb_path,
    _require_supported_usb_identity,
)


class CapturingSink:
    def __init__(self) -> None:
        self.events: list[object] = []
        self.done = Event()

    def record(self, event, received_at, gps_state) -> int:
        self.events.append(event)
        self.done.set()
        return len(self.events)


class FakeReader:
    def __init__(self, frame: bytes) -> None:
        self.frame = frame
        self.closed = False
        self.read_calls = 0

    def read(self, size: int) -> bytes:
        self.read_calls += 1
        if self.read_calls == 1:
            return self.frame
        return b""

    def close(self) -> None:
        self.closed = True

    def write(self, payload: bytes) -> None:
        raise AssertionError("Passive collector tried to write to serial")


def test_existing_tty_and_by_id_are_never_accepted():
    for selector in ("/dev/ttyUSB0", "/dev/serial/by-id/CP2102_0001"):
        with pytest.raises(ValueError):
            validate_meshcore_usb_path(Path(selector))


def test_fake_reader_receives_one_event_without_writing():
    sink = CapturingSink()
    worker = MeshcorePassiveWorker(sink, lambda: None)
    payload = b"\x80" + bytes(range(32))
    frame = b">" + len(payload).to_bytes(2, "little") + payload
    fake = FakeReader(frame)
    service = MeshcorePassiveSerialService(
        worker,
        Path("/dev/serial/by-path/not-present"),
        reader_factory=lambda _: fake,
    )
    service.start()
    assert sink.done.wait(2), "Expected record from asynchronous reader"
    service.stop()
    assert len(sink.events) == 1
    assert fake.closed
    assert service.status().worker.stored == 1
    assert not service.status().running


def test_missing_device_degrades_without_interrupting_services():
    worker = MeshcorePassiveWorker(CapturingSink(), lambda: None)
    service = MeshcorePassiveSerialService(
        worker, Path("/dev/serial/by-path/missing"),
        reader_factory=lambda _: (_ for _ in ()).throw(OSError("not present")),
    )
    service.start()
    for _ in range(100):
        if service.status().last_error:
            break
        Event().wait(0.01)
    assert service.status().last_error == "OSError"
    service.stop()
    assert not service.status().running


@pytest.mark.parametrize(
    ("tty", "vid", "pid"),
    [
        ("ttyUSB2", "10c4", "ea60"),
        ("ttyACM0", "303a", "0002"),
    ],
)
def test_supported_meshcore_usb_interfaces(
    tmp_path: Path, tty: str, vid: str, pid: str
) -> None:
    """Accept V3 bridge and V4 native CDC by expected transport family."""
    usb = tmp_path / "usb-device"
    iface = usb / "1-1.1.1:1.0"
    iface.mkdir(parents=True)
    (usb / "idVendor").write_text(vid, encoding="utf-8")
    (usb / "idProduct").write_text(pid, encoding="utf-8")
    _require_supported_usb_identity(tty, iface)


@pytest.mark.parametrize(
    ("tty", "vid", "pid"),
    [
        ("ttyUSB2", "303a", "0002"),
        ("ttyACM0", "10c4", "ea60"),
        ("ttyACM0", "2341", "0043"),
        ("ttyUSB2", "ffff", "0000"),
    ],
)
def test_reject_other_or_mismatched_usb_identity(
    tmp_path: Path, tty: str, vid: str, pid: str
) -> None:
    """Do not claim any arbitrary serial adapter as MeshCore."""
    usb = tmp_path / "usb-device"
    iface = usb / "1-1.1.1:1.0"
    iface.mkdir(parents=True)
    (usb / "idVendor").write_text(vid, encoding="utf-8")
    (usb / "idProduct").write_text(pid, encoding="utf-8")
    with pytest.raises(ValueError, match="USB family"):
        _require_supported_usb_identity(tty, iface)


def test_missing_usb_descriptors_fail_closed(tmp_path: Path) -> None:
    """A half-enumerated USB device cannot be used for collection."""
    with pytest.raises(OSError, match="descriptor"):
        _require_supported_usb_identity("ttyACM0", tmp_path)
