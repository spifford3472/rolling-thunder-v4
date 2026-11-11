"""Exercise public broker -> durable traffic ledger -> per-consumer ACK."""

from __future__ import annotations

import hashlib
import os
import threading
from datetime import UTC, datetime
from pathlib import Path

from rolling_thunder.meshcore_broker_api import MeshcoreBrokerApiServer
from rolling_thunder.meshcore_broker_config import BrokerConsumer
from rolling_thunder.meshcore_message_broker import MeshcoreMessageBroker, MessageStream
from rolling_thunder.meshcore_public_consumer import MeshcorePublicConsumer
from rolling_thunder.meshcore_public_intake_protocol import VerifiedChannel
from rolling_thunder.meshcore_public_intelligence import TrafficChannelSelection
from rolling_thunder.meshcore_traffic_ledger import TrafficLedger
from rolling_thunder.meshcore_traffic_worker import MeshcoreTrafficWorker

_NOW = datetime(2026, 11, 11, 20, 0, tzinfo=UTC)


def _frame(slot: int, text: str) -> bytes:
    return (
        bytes((0x11, 0xE0, 0, 0, slot, 0xFF, 0))
        + (1794405600).to_bytes(4, "little") + text.encode("utf-8")
    )


def test_end_to_end_retrieval_commit_ack_and_other_cursor_unchanged(
    tmp_path: Path,
) -> None:
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    credential = private / "rolling-thunder.token"
    token = "A" * 64
    credential.write_text(token + "\n")
    os.chmod(credential, 0o600)
    consumers = {
        "rolling-thunder": frozenset({MessageStream.PUBLIC}),
        "scout": frozenset({MessageStream.PUBLIC}),
        "operator": frozenset({MessageStream.PRIVATE}),
    }
    broker = MeshcoreMessageBroker(private / "broker.db", consumers=consumers)
    broker.store(
        _frame(0, "General chatter"),
        received_at=_NOW,
        verified_channels={0: VerifiedChannel(0, "Public")},
    )
    broker.store(
        _frame(1, "Accident on I-75 northbound"),
        received_at=_NOW,
        verified_channels={1: VerifiedChannel(1, "#traffic")},
    )
    broker.store(b"\x10Private DM", received_at=_NOW, verified_channels={})
    broker.store(
        _frame(1, "Accident on I-75 northbound"),
        received_at=_NOW,
        verified_channels={1: VerifiedChannel(1, "#traffic")},
    )
    app = MeshcoreBrokerApiServer(
        str(tmp_path / "broker.sock"),
        broker,
        (
            BrokerConsumer(
                "rolling-thunder", hashlib.sha256(token.encode()).hexdigest(),
                frozenset({MessageStream.PUBLIC}),
            ),
        ),
    )
    thread = threading.Thread(target=app.serve_forever)
    thread.start()
    try:
        client = MeshcorePublicConsumer(
            tmp_path / "broker.sock", credential,
        )
        ledger = TrafficLedger(
            private / "traffic.db", approved=TrafficChannelSelection(1, "#traffic"),
        )
        cycle = MeshcoreTrafficWorker(client, ledger, batch_size=10).run_once()
        assert (cycle.stored, cycle.candidates, cycle.duplicates, cycle.ignored) == (
            3, 1, 1, 1
        )
        assert cycle.acknowledged == 3
        assert broker.peek("rolling-thunder", MessageStream.PUBLIC) == ()
        assert len(broker.peek("scout", MessageStream.PUBLIC)) == 3
        assert len(broker.peek("operator", MessageStream.PRIVATE)) == 1
        assert ledger.counts() == {"candidate": 1, "duplicate": 1, "ignored": 1}
        # A repeat with no new public data is a bounded no-op.
        assert MeshcoreTrafficWorker(client, ledger).run_once().stored == 0
    finally:
        app.shutdown()
        app.server_close()
        thread.join(timeout=2)
