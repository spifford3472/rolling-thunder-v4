"""Transport-free bounded writer tests; no USB, network or real radio."""

from datetime import UTC, datetime
from threading import Event

import pytest

from rolling_thunder.meshcore_passive_worker import MeshcorePassiveWorker


class FakeSink:
    def __init__(self) -> None:
        self.saved = []
        self.block = None

    def record_signal(self, event, received_at, gps_state):
        self.saved.append((event, received_at, gps_state))
        return len(self.saved)

    def record(self, event, received_at, gps_state):
        if self.block is not None:
            self.block.wait(timeout=3)
        self.saved.append((event, received_at, gps_state))
        return len(self.saved)


def test_disabled_worker_never_writes():
    sink = FakeSink()
    worker = MeshcorePassiveWorker(sink, lambda: None)
    assert not worker.offer(b"\x80" + bytes(32))
    assert worker.status().stored == 0
    assert not sink.saved


def test_worker_records_inbound_identity_and_ignores_messages():
    sink = FakeSink()
    worker = MeshcorePassiveWorker(sink, lambda: None)
    worker.start()
    assert worker.offer(b"\x80" + bytes(range(32)))
    assert worker.offer(b"\x83" + bytes(32))
    worker.stop()
    assert len(sink.saved) == 1
    assert worker.status().stored == 1
    assert worker.status().malformed_or_unsupported == 1
    assert not worker.status().running


def test_bounded_queue_records_overflow():
    sink = FakeSink()
    block = Event()
    sink.block = block
    worker = MeshcorePassiveWorker(sink, lambda: None, capacity=1)
    worker.start()
    try:
        for n in range(100):
            worker.offer(b"\x80" + bytes(31) + bytes([n]))
    finally:
        block.set()
        worker.stop()
    assert worker.status().dropped > 0
    assert worker.status().queued == 0
    assert worker.status().received == (
        worker.status().stored + worker.status().dropped
    )


def test_gps_snapshot_taken_at_offer_not_after_delay():
    seen = []
    now = datetime(2026, 11, 11, 5, tzinfo=UTC)
    sink = FakeSink()
    worker = MeshcorePassiveWorker(sink, lambda: seen.append(1) or None)
    worker.start()
    worker.offer(b"\x80" + bytes(32), received_at=now)
    worker.stop()
    assert seen == [1]
    assert sink.saved[0][1] == now


def test_invalid_capacity():
    with pytest.raises(ValueError):
        MeshcorePassiveWorker(FakeSink(), lambda: None, capacity=0)


def test_raw_rf_payload_is_stripped_before_reaching_sink():
    """Persistence never receives raw MeshCore packet or guessed sender."""
    sink = FakeSink()
    worker = MeshcorePassiveWorker(sink, lambda: None)
    worker.start()
    raw = bytes([0x88, 0xF0, 0x9C]) + b"secret-RF-payload"
    assert worker.offer(raw)
    worker.stop()
    assert len(sink.saved) == 1
    event = sink.saved[0][0]
    assert event.rssi_dbm == -100
    assert event.snr_db == -4
    assert "secret-RF-payload" not in repr(event)
