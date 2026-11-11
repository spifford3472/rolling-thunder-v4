"""Offline persistence, privacy, backpressure and replay tests for broker."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import stat
from datetime import UTC, datetime
from pathlib import Path

import pytest

from rolling_thunder.meshcore_message_broker import (
    BrokerCapacityError,
    MeshcoreMessageBroker,
    MessageStream,
)
from rolling_thunder.meshcore_public_intake_protocol import (
    ApprovedPublicChannel,
    VerifiedChannel,
    verify_channel_info,
)


NOW = datetime(2026, 11, 11, 18, 0, tzinfo=UTC)
S = MessageStream
CONSUMERS = {
    "scout": frozenset({S.PUBLIC}),
    "rolling-thunder": frozenset({S.PUBLIC}),
    "operator": frozenset({S.PRIVATE, S.QUARANTINE, S.PUBLIC}),
}
SECRET = bytes(range(16))
APPROVAL = ApprovedPublicChannel(
    3, "#traffic", hashlib.sha256(SECRET).hexdigest(), True
)
REPLY = bytes((0x12, 3)) + b"#traffic".ljust(32, b"\x00") + SECRET
CHANNEL = verify_channel_info(REPLY, APPROVAL)
assert CHANNEL is not None
TIMESTAMP = 1794405600


@pytest.fixture
def path(tmp_path: Path) -> Path:
    base = tmp_path / "broker"
    base.mkdir(mode=0o700)
    return base / "messages.db"


def _public_frame(*, slot: int = 3, text: bytes = b"Accident I-71") -> bytes:
    return (
        bytes((0x11, 0xE0, 0, 0, slot, 0xFF, 0))
        + TIMESTAMP.to_bytes(4, "little") + text
    )


def _broker(path: Path, **kwargs: object) -> MeshcoreMessageBroker:
    return MeshcoreMessageBroker(path, consumers=CONSUMERS, **kwargs)


def test_private_and_public_are_separate_with_independent_cursors(path: Path) -> None:
    broker = _broker(path)
    private = bytes((0x10,)) + b"private message with secret"
    first = broker.store(private, received_at=NOW, verified_channels={3: CHANNEL})
    second = broker.store(
        _public_frame(), received_at=NOW, verified_channels={3: CHANNEL}
    )
    assert first != second
    assert broker.status() == {"public": 1, "private": 1, "quarantine": 0}

    public = broker.peek("scout", S.PUBLIC)
    assert [msg.message_id for msg in public] == [second]
    assert public[0].payload == "Accident I-71"
    assert public[0].channel_name == "#traffic"
    assert "private message" not in repr(public)
    assert broker.peek("operator", S.PRIVATE)[0].payload == private

    broker.acknowledge("scout", S.PUBLIC, second)
    assert broker.peek("scout", S.PUBLIC) == ()
    assert len(broker.peek("rolling-thunder", S.PUBLIC)) == 1
    assert len(broker.peek("operator", S.PRIVATE)) == 1


def test_private_denied_to_public_clients(path: Path) -> None:
    broker = _broker(path)
    broker.store(b"\x07secret", received_at=NOW, verified_channels={})
    for stream in (S.PRIVATE, S.QUARANTINE):
        with pytest.raises(PermissionError):
            broker.peek("scout", stream)
        with pytest.raises(PermissionError):
            broker.acknowledge("scout", stream, 1)
    with pytest.raises(PermissionError):
        broker.peek("unknown", S.PUBLIC)


def test_unverified_or_bad_channels_are_quarantined(path: Path) -> None:
    broker = _broker(path)
    broker.store(_public_frame(), received_at=NOW, verified_channels={})
    broker.store(
        _public_frame(slot=2), received_at=NOW, verified_channels={3: CHANNEL}
    )
    broker.store(b"\x1Bbinary", received_at=NOW, verified_channels={})
    broker.store(b"\xFFunknown", received_at=NOW, verified_channels={})
    assert broker.status() == {"public": 0, "private": 0, "quarantine": 4}
    assert not broker.peek("scout", S.PUBLIC)
    assert len(broker.peek("operator", S.QUARANTINE)) == 4


def test_restart_preserves_payload_and_cursor(path: Path) -> None:
    broker = _broker(path)
    broker.store(b"\x07private", received_at=NOW, verified_channels={})
    message_id = broker.store(
        _public_frame(), received_at=NOW, verified_channels={3: CHANNEL}
    )
    broker.acknowledge("rolling-thunder", S.PUBLIC, message_id)
    restarted = _broker(path)
    assert restarted.peek("rolling-thunder", S.PUBLIC) == ()
    assert len(restarted.peek("scout", S.PUBLIC)) == 1
    assert restarted.peek("operator", S.PRIVATE)[0].payload == b"\x07private"


def test_repeated_ack_is_idempotent_and_cannot_skip_stream(path: Path) -> None:
    broker = _broker(path)
    private_id = broker.store(b"\x10private", received_at=NOW, verified_channels={})
    public_id = broker.store(
        _public_frame(), received_at=NOW, verified_channels={3: CHANNEL}
    )
    with pytest.raises(ValueError):
        broker.acknowledge("scout", S.PUBLIC, private_id)
    with pytest.raises(ValueError):
        broker.acknowledge("scout", S.PUBLIC, 999)
    broker.acknowledge("scout", S.PUBLIC, public_id)
    broker.acknowledge("scout", S.PUBLIC, public_id)
    assert broker.peek("scout", S.PUBLIC) == ()


def test_backpressure_stops_before_another_dequeue(path: Path) -> None:
    broker = _broker(path, capacity=2)
    assert broker.can_accept()
    broker.store(b"\x07one", received_at=NOW, verified_channels={})
    broker.store(b"\x10two", received_at=NOW, verified_channels={})
    assert not broker.can_accept()
    with pytest.raises(BrokerCapacityError):
        broker.store(b"\x07three", received_at=NOW, verified_channels={})
    assert broker.status()["private"] == 2


def test_no_private_payload_in_public_database_rows(path: Path) -> None:
    broker = _broker(path)
    broker.store(b"\x07top-secret", received_at=NOW, verified_channels={})
    broker.store(
        _public_frame(), received_at=NOW, verified_channels={3: CHANNEL}
    )
    with sqlite3.connect(path) as connection:
        public = connection.execute(
            "SELECT payload FROM broker_messages WHERE stream='public'"
        ).fetchall()
        assert public == [(b"Accident I-71",)]


def test_file_and_directory_owner_permissions(path: Path) -> None:
    _broker(path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


@pytest.mark.parametrize("bad", [b"", b"\x12" + b"x" * 49, b"\x0A", b"X" * 177])
def test_refuse_secret_control_and_unbounded_frames(path: Path, bad: bytes) -> None:
    broker = _broker(path)
    with pytest.raises(ValueError):
        broker.store(bad, received_at=NOW, verified_channels={})
    assert sum(broker.status().values()) == 0


def test_file_symlink_and_permissive_directory_refused(tmp_path: Path) -> None:
    base = tmp_path / "broker"
    base.mkdir(mode=0o700)
    target = base / "legitimate.db"
    _broker(target)
    symlink = base / "alias.db"
    symlink.symlink_to(target)
    with pytest.raises(PermissionError):
        _broker(symlink)
    os.chmod(base, 0o755)
    with pytest.raises(PermissionError):
        _broker(target)


def test_no_reuse_of_observation_db_and_fail_closed_future_schema(path: Path) -> None:
    _broker(path)
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE broker_schema SET version=99 WHERE id=1")
    with pytest.raises(ValueError, match="schema"):
        _broker(path)


def test_sqlite_failure_does_not_advance_any_cursor(path: Path) -> None:
    broker = _broker(path)
    broker.store(b"\x07private", received_at=NOW, verified_channels={})
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE broker_messages")
    with pytest.raises(sqlite3.Error):
        broker.can_accept()


def test_invalid_consumer_and_limits_refused(path: Path) -> None:
    with pytest.raises(ValueError):
        MeshcoreMessageBroker(path, consumers={"": frozenset({S.PUBLIC})})
    broker = _broker(path)
    with pytest.raises(ValueError):
        broker.peek("scout", S.PUBLIC, limit=0)
