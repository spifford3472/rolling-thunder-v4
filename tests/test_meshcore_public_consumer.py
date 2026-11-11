"""MeshCore public consumer integration and privacy regression coverage."""

from __future__ import annotations

import hashlib
import os
import socket
import stat
import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest

from rolling_thunder.meshcore_broker_api import MeshcoreBrokerApiServer
from rolling_thunder.meshcore_broker_config import BrokerConsumer
from rolling_thunder.meshcore_message_broker import MeshcoreMessageBroker, MessageStream
from rolling_thunder.meshcore_public_consumer import (
    MeshcoreConsumerError,
    MeshcorePublicConsumer,
)
from rolling_thunder.meshcore_public_intake_protocol import VerifiedChannel

_TOKEN = "client-" + "a" * 64
_STAMP = datetime(2026, 11, 11, 19, 0, tzinfo=UTC)


@pytest.fixture
def service(tmp_path: Path) -> tuple[MeshcorePublicConsumer, MeshcoreMessageBroker]:
    """One real Unix broker API with an isolated private SQLite database."""
    base = tmp_path / "messages"
    base.mkdir(mode=0o700)
    broker = MeshcoreMessageBroker(
        base / "db.sqlite3",
        consumers={"scout": frozenset({MessageStream.PUBLIC}),
                   "operator": frozenset({MessageStream.PRIVATE})},
    )
    consumer = BrokerConsumer(
        "scout",
        hashlib.sha256(_TOKEN.encode()).hexdigest(),
        frozenset({MessageStream.PUBLIC}),
    )
    path = tmp_path / "broker.sock"
    server = MeshcoreBrokerApiServer(str(path), broker, (consumer,))
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    credential = tmp_path / "scout.token"
    credential.write_text(_TOKEN + "\n", encoding="ascii")
    os.chmod(credential, 0o600)
    client = MeshcorePublicConsumer(path, credential)
    try:
        yield client, broker
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _public(text: bytes, slot: int = 1) -> bytes:
    return (
        bytes((0x11, 0xE0, 0, 0, slot, 0xFF, 0))
        + (1794405600).to_bytes(4, "little") + text
    )


def test_read_only_snapshot_preserves_independent_cursor(
    service: tuple[MeshcorePublicConsumer, MeshcoreMessageBroker],
) -> None:
    client, broker = service
    broker.store(
        b"\x10operator only", received_at=_STAMP, verified_channels={}
    )
    first_id = broker.store(
        _public(b"Traffic closure I-75"), received_at=_STAMP,
        verified_channels={1: VerifiedChannel(1, "#traffic")},
    )
    batch = client.preview(limit=5)
    assert len(batch) == 1
    assert batch[0].message_id == first_id
    assert batch[0].channel_name == "#traffic"
    assert batch[0].text == "Traffic closure I-75"
    assert batch[0].received_at == _STAMP
    assert batch[0].claimed_at is not None
    assert "operator only" not in repr(batch)
    assert client.preview(limit=5) == batch
    assert broker.peek("scout", MessageStream.PUBLIC)[0].message_id == first_id
    client.acknowledge_processed(first_id)
    assert client.preview() == ()
    assert broker.peek("operator", MessageStream.PRIVATE)[0].payload == b"\x10operator only"


def test_restricted_credential_fails_closed(
    service: tuple[MeshcorePublicConsumer, MeshcoreMessageBroker],
    tmp_path: Path,
) -> None:
    client, _ = service
    credential = tmp_path / "unsafe.token"
    credential.write_text(_TOKEN)
    os.chmod(credential, 0o644)
    untrusted = MeshcorePublicConsumer(client._socket_path, credential)
    with pytest.raises(MeshcoreConsumerError, match="permissions"):
        untrusted.preview()
    symlink = tmp_path / "link.token"
    symlink.symlink_to(credential)
    with pytest.raises(MeshcoreConsumerError):
        MeshcorePublicConsumer(client._socket_path, symlink).preview()


def test_no_network_access_when_socket_missing(tmp_path: Path) -> None:
    credential = tmp_path / "token"
    credential.write_text(_TOKEN)
    os.chmod(credential, stat.S_IRUSR | stat.S_IWUSR)
    consumer = MeshcorePublicConsumer(tmp_path / "not-found.sock", credential)
    with pytest.raises(MeshcoreConsumerError, match="communication"):
        consumer.preview()


def test_client_rejects_implicit_or_invalid_ack(
    service: tuple[MeshcorePublicConsumer, MeshcoreMessageBroker],
) -> None:
    client, _ = service
    for invalid in (0, -1, True, 1.0):
        with pytest.raises(ValueError):
            client.acknowledge_processed(invalid)
    for limit in (0, 101):
        with pytest.raises(ValueError):
            client.preview(limit=limit)


def test_credential_is_never_in_exception_text(tmp_path: Path) -> None:
    credential = tmp_path / "token"
    credential.write_text(_TOKEN)
    os.chmod(credential, 0o600)
    client = MeshcorePublicConsumer(tmp_path / "absent.sock", credential)
    try:
        client.preview()
    except MeshcoreConsumerError as error:
        assert _TOKEN not in str(error)
    else:
        pytest.fail("Missing socket should fail")
