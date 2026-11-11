"""Proof of durable, independent and idempotent traffic worker processing."""

from __future__ import annotations

import os
import sqlite3
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from rolling_thunder.meshcore_public_consumer import PublicBrokerMessage
from rolling_thunder.meshcore_public_intelligence import TrafficChannelSelection
from rolling_thunder.meshcore_traffic_ledger import (
    TrafficDisposition,
    TrafficLedger,
    TrafficLedgerError,
)
from rolling_thunder.meshcore_traffic_worker import MeshcoreTrafficWorker

_NOW = datetime(2026, 11, 11, 20, 0, tzinfo=UTC)
_APPROVED = TrafficChannelSelection(1, "#traffic")


def _record(
    number: int, *, text: str = "Crash I-75 northbound",
    channel_name: str = "#traffic", channel_slot: int = 1,
    when: datetime = _NOW,
) -> PublicBrokerMessage:
    return PublicBrokerMessage(number, channel_name, channel_slot, text, when, None)


@pytest.fixture
def ledger_path(tmp_path: Path) -> Path:
    base = tmp_path / "ledger"
    base.mkdir(mode=0o700)
    return base / "records.db"


class FakeQueue:
    """Represent broker cursor advancement for one public consumer."""

    def __init__(self, messages: tuple[PublicBrokerMessage, ...]) -> None:
        self.messages = messages
        self.cursor = 0
        self.failed_ack = False
        self.acked: list[int] = []

    def preview(self, *, limit: int = 25) -> tuple[PublicBrokerMessage, ...]:
        return tuple(
            item for item in self.messages if item.message_id > self.cursor
        )[:limit]

    def acknowledge_processed(self, message_id: int) -> None:
        if self.failed_ack:
            raise OSError("ack unexpectedly interrupted")
        self.cursor = max(self.cursor, message_id)
        self.acked.append(message_id)


def test_commit_before_ack_and_independent_message_results(
    ledger_path: Path,
) -> None:
    ledger = TrafficLedger(ledger_path, approved=_APPROVED)
    queue = FakeQueue((
        _record(1),
        _record(2, text="Crash I-75 northbound"),
        _record(3, text="Public chat", channel_name="Public", channel_slot=0),
        _record(4, text="Construction on SR-73"),
    ))
    outcome = MeshcoreTrafficWorker(queue, ledger, batch_size=10).run_once()
    assert outcome.stored == 4
    assert outcome.candidates == 2
    assert outcome.duplicates == 1
    assert outcome.ignored == 1
    assert queue.acked == [1, 2, 3, 4]
    assert ledger.counts() == {"candidate": 2, "duplicate": 1, "ignored": 1}
    assert stat.S_IMODE(ledger_path.stat().st_mode) == 0o600


def test_ack_failed_after_commit_replay_is_idempotent(
    ledger_path: Path,
) -> None:
    ledger = TrafficLedger(ledger_path, approved=_APPROVED)
    queue = FakeQueue((_record(1),))
    queue.failed_ack = True
    with pytest.raises(OSError):
        MeshcoreTrafficWorker(queue, ledger).run_once()
    assert queue.cursor == 0
    assert ledger.counts()["candidate"] == 1
    queue.failed_ack = False
    result = MeshcoreTrafficWorker(queue, TrafficLedger(
        ledger_path, approved=_APPROVED
    )).run_once()
    assert result.stored == 1
    assert result.acknowledged == 1
    assert queue.cursor == 1
    assert ledger.counts()["candidate"] == 1


def test_storage_capacity_stops_before_ack(ledger_path: Path) -> None:
    ledger = TrafficLedger(ledger_path, approved=_APPROVED, max_records=1)
    queue = FakeQueue((_record(1), _record(2)))
    with pytest.raises(TrafficLedgerError, match="full"):
        MeshcoreTrafficWorker(queue, ledger).run_once()
    assert queue.acked == [1]
    assert queue.cursor == 1
    assert ledger.counts()["candidate"] == 1


def test_duplicate_window_expires(ledger_path: Path) -> None:
    ledger = TrafficLedger(
        ledger_path, approved=_APPROVED, duplicate_window=timedelta(minutes=30)
    )
    first = ledger.process(_record(1))
    second = ledger.process(_record(2, when=_NOW + timedelta(minutes=15)))
    third = ledger.process(_record(3, when=_NOW + timedelta(minutes=31)))
    assert first.disposition == TrafficDisposition.CANDIDATE
    assert second.disposition == TrafficDisposition.DUPLICATE
    # Dedup is based on the most recently observed matching report.
    assert third.disposition == TrafficDisposition.DUPLICATE


def test_traffic_report_reused_id_with_changed_text_fails_closed(
    ledger_path: Path,
) -> None:
    ledger = TrafficLedger(ledger_path, approved=_APPROVED)
    ledger.process(_record(9))
    with pytest.raises(TrafficLedgerError, match="changed"):
        ledger.process(_record(9, text="Road clear"))
    assert ledger.counts()["candidate"] == 1


def test_nontraffic_public_messages_are_durably_ignored(
    ledger_path: Path,
) -> None:
    ledger = TrafficLedger(ledger_path, approved=_APPROVED)
    ignored = ledger.process(_record(1, channel_name="Public", channel_slot=0))
    assert ignored.disposition == TrafficDisposition.IGNORED
    assert ignored.category is None
    with sqlite3.connect(ledger_path) as connection:
        assert connection.execute(
            "SELECT event_fingerprint,category FROM traffic_records"
        ).fetchone() == (None, None)


def test_no_raw_message_text_or_private_payload_in_ledger(
    ledger_path: Path,
) -> None:
    ledger = TrafficLedger(ledger_path, approved=_APPROVED)
    ledger.process(_record(1, text="Crash I-75 Northbound unique-text-xyz"))
    data = ledger_path.read_bytes()
    assert b"unique-text-xyz" not in data
    assert b"private" not in data


def test_restart_is_durable_and_does_not_delete_broker_messages(
    ledger_path: Path,
) -> None:
    ledger = TrafficLedger(ledger_path, approved=_APPROVED)
    ledger.process(_record(1))
    restarted = TrafficLedger(ledger_path, approved=_APPROVED)
    result = restarted.process(_record(1))
    assert result.disposition == TrafficDisposition.CANDIDATE
    assert restarted.counts()["candidate"] == 1


def test_fail_closed_on_insecure_storage(tmp_path: Path) -> None:
    parent = tmp_path / "bad"
    parent.mkdir(mode=0o755)
    os.chmod(parent, 0o755)
    with pytest.raises(TrafficLedgerError):
        TrafficLedger(parent / "ledger.db", approved=_APPROVED)
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    p = private / "ledger.db"
    p.write_bytes(b"malformed")
    os.chmod(p, 0o644)
    with pytest.raises(TrafficLedgerError):
        TrafficLedger(p, approved=_APPROVED)
    symlink = private / "symlink.db"
    symlink.symlink_to(p)
    with pytest.raises(TrafficLedgerError):
        TrafficLedger(symlink, approved=_APPROVED)


@pytest.mark.parametrize("seconds", [0, 86401])
def test_invalid_dedup_window_fails(ledger_path: Path, seconds: int) -> None:
    with pytest.raises(ValueError):
        TrafficLedger(
            ledger_path, approved=_APPROVED,
            duplicate_window=timedelta(seconds=seconds),
        )
