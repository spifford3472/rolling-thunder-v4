"""No-radio channel audit: only GET_CHANNEL opcodes, no key disclosure."""

from __future__ import annotations

import hashlib
from collections import deque

import pytest

from rolling_thunder.meshcore_channel_audit import audit_channels

KEY1 = b"\x01" * 16
KEY2 = b"\x02" * 16


class AuditFakePort:
    """Push only firmware-framed channel replies after a GET_CHANNEL request."""

    def __init__(self, *, bad: bool = False) -> None:
        self.replies: deque[bytes] = deque()
        self.writes: list[bytes] = []
        self.bad = bad

    def write(self, data: bytes) -> int:
        self.writes.append(data)
        assert len(data) == 5
        assert data[:4] == b"<\x02\x00\x1f"
        slot = data[-1]
        if slot == 0:
            payload = (
                bytes([0x12, 0])
                + b"Public\x00".ljust(32, b"\xff") + KEY1
            )
        elif slot == 1:
            payload = (
                bytes([0x12, 1])
                + b"#traffic\x00".ljust(32, b"\x04") + KEY2
            )
        else:
            payload = b"\x01\x02"
        if self.bad and slot == 1:
            payload = bytes([0x12, 2]) + payload[2:]
        self.replies.append(
            b">" + len(payload).to_bytes(2, "little") + payload
        )
        return len(data)

    def read(self, count: int) -> bytes:
        return self.replies.popleft() if self.replies else b""

    def close(self) -> None:
        pass


def test_audit_only_queries_slots_and_never_returns_secrets() -> None:
    fake = AuditFakePort()
    items = audit_channels(fake, max_slot=2)
    assert [i.name for i in items] == ["Public", "#traffic"]
    assert [i.slot for i in items] == [0, 1]
    assert items[0].secret_sha256 == hashlib.sha256(KEY1).hexdigest()
    assert items[1].secret_sha256 == hashlib.sha256(KEY2).hexdigest()
    assert KEY1.hex() not in repr(items)
    assert KEY2.hex() not in repr(items)
    assert fake.writes == [
        b"<\x02\x00\x1f\x00",
        b"<\x02\x00\x1f\x01",
        b"<\x02\x00\x1f\x02",
    ]


def test_wrong_slot_fails_closed() -> None:
    with pytest.raises(ValueError, match="identity"):
        audit_channels(AuditFakePort(bad=True), max_slot=1)


@pytest.mark.parametrize("slot,delay", [(-1, 1.0), (8, 1.0), (2, 0.01)])
def test_invalid_bounds_refused(slot: int, delay: float) -> None:
    with pytest.raises(ValueError):
        audit_channels(AuditFakePort(), max_slot=slot, timeout_s=delay)
