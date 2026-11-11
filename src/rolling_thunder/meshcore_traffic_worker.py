"""Bounded background traffic analysis with commit-before-ACK semantics.

The worker is deliberately not composed into Tkinter or a systemd unit.
Each cycle is single-flight. Acknowledgement is permitted only after the
separate SQLite ledger has completed its synchronous commit.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from rolling_thunder.meshcore_public_consumer import PublicBrokerMessage
from rolling_thunder.meshcore_traffic_ledger import (
    TrafficDisposition,
    TrafficLedger,
)


class PublicQueue(Protocol):
    """Injected public-only broker transport; never private or serial."""

    def preview(self, *, limit: int = 25) -> tuple[PublicBrokerMessage, ...]:
        """Read a bounded batch without advancing the broker cursor."""
        ...

    def acknowledge_processed(self, message_id: int) -> None:
        """Advance only this consumer's public cursor after durable processing."""
        ...


@dataclass(frozen=True, slots=True)
class TrafficCycle:
    """Read-only counters for one worker pass; not an alert notification."""

    stored: int
    candidates: int
    duplicates: int
    ignored: int
    acknowledged: int


class MeshcoreTrafficWorker:
    """Process a maximum of one bounded batch per invocation."""

    def __init__(
        self, queue: PublicQueue, ledger: TrafficLedger, *, batch_size: int = 25
    ) -> None:
        if not 1 <= batch_size <= 100:
            raise ValueError("Invalid traffic worker batch size")
        self._queue = queue
        self._ledger = ledger
        self._batch_size = batch_size

    def run_once(self) -> TrafficCycle:
        """Fail immediately on storage or broker errors without skipping frames.

        Commit one message, ACK the exact committed ID, then continue. If ACK
        failed after commit, next run replays the idempotent SQLite entry and
        retries just that ACK. Never ACK based on classification success alone.
        """
        items = self._queue.preview(limit=self._batch_size)
        candidate = duplicate = ignored = acked = 0
        for item in items:
            entry = self._ledger.process(item)
            if entry.disposition == TrafficDisposition.CANDIDATE:
                candidate += 1
            elif entry.disposition == TrafficDisposition.DUPLICATE:
                duplicate += 1
            else:
                ignored += 1
            self._queue.acknowledge_processed(item.message_id)
            acked += 1
        return TrafficCycle(len(items), candidate, duplicate, ignored, acked)
