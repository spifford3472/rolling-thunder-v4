"""End-to-end simulated USB framing, safe dequeue, and SQLite durability."""

from __future__ import annotations

import hashlib
import threading
import time
from collections import deque
from datetime import UTC, datetime
from pathlib import Path

from rolling_thunder.meshcore_broker_drain import MeshcoreBrokerDrain
from rolling_thunder.meshcore_message_broker import (
    MeshcoreMessageBroker,
    MessageStream,
)
from rolling_thunder.meshcore_passive_worker import MeshcorePassiveWorker
from rolling_thunder.meshcore_public_intake_protocol import ApprovedPublicChannel
from rolling_thunder.meshcore_serial_service import MeshcorePassiveSerialService


SECRET = bytes(range(16))
APPROVED = ApprovedPublicChannel(
    3, "#traffic", hashlib.sha256(SECRET).hexdigest(), True
)
INFO = bytes((0x12, 3)) + b"#traffic".ljust(32, b"\x00") + SECRET
STAMP = 1794405600
PUBLIC = (
    bytes((0x11, 0xE0, 0, 0, 3, 0xFF, 0))
    + STAMP.to_bytes(4, "little") + b"Accident I-71"
)
PRIVATE = b"\x10private message for operator"


class NullSink:
    """Passive observation pipeline remains independent and unused in this test."""

    def record(self, event: object, received_at: datetime, gps_state: object) -> int:
        return 1

    def record_signal(
        self, sample: object, received_at: datetime, gps_state: object
    ) -> int:
        return 1


class FakeDuplex:
    """Return real firmware-framed replies only when local opcodes arrive."""

    def __init__(self) -> None:
        self.queue: deque[bytes] = deque()
        self.lock = threading.Lock()
        self.commands: list[bytes] = []
        self.frames = deque((PRIVATE, PUBLIC, b"\x0a"))
        self.closed = False

    def write(self, request: bytes) -> int:
        with self.lock:
            self.commands.append(request)
            if request == b"<\x02\x00\x1f\x03":
                payload = INFO
            elif request == b"<\x01\x00\x0a":
                payload = self.frames.popleft()
            else:
                raise AssertionError("Unexpected or RF-capable serial opcode")
            self.queue.append(b">" + len(payload).to_bytes(2, "little") + payload)
        return len(request)

    def read(self, size: int) -> bytes:
        with self.lock:
            return self.queue.popleft() if self.queue else b""

    def close(self) -> None:
        self.closed = True


def test_serial_owner_drains_private_and_public_to_separate_cursors(
    tmp_path: Path,
) -> None:
    base = tmp_path / "private"
    base.mkdir(mode=0o700)
    inbox = MeshcoreMessageBroker(
        base / "messages.db",
        consumers={
            "scout": frozenset({MessageStream.PUBLIC}),
            "operator": frozenset({MessageStream.PRIVATE}),
        },
    )
    drain = MeshcoreBrokerDrain(inbox, (APPROVED,))
    fake = FakeDuplex()
    worker = MeshcorePassiveWorker(NullSink(), lambda: None)
    service = MeshcorePassiveSerialService(
        worker, Path("/dev/serial/by-path/fake"),
        reader_factory=lambda _: fake, broker_drain=drain,
    )
    service.start()
    try:
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and drain.status().saved != 2:
            time.sleep(0.01)
        assert drain.status().saved == 2
        assert drain.status().fault is None
        assert inbox.peek("operator", MessageStream.PRIVATE)[0].payload == PRIVATE
        assert inbox.peek("scout", MessageStream.PUBLIC)[0].payload == "Accident I-71"
        assert fake.commands == [
            b"<\x02\x00\x1f\x03",
            b"<\x01\x00\x0a",
            b"<\x01\x00\x0a",
            b"<\x01\x00\x0a",
        ]
        assert service.status().device_connected
    finally:
        service.stop()
    assert fake.closed
    assert MeshcoreMessageBroker(
        base / "messages.db",
        consumers={"operator": frozenset({MessageStream.PRIVATE})},
    ).peek("operator", MessageStream.PRIVATE)[0].payload == PRIVATE
