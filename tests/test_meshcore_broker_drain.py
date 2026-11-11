"""No-hardware proof that the broker serial state machine never sends RF."""

from __future__ import annotations

import hashlib
from pathlib import Path

from rolling_thunder.meshcore_broker_drain import MeshcoreBrokerDrain
from rolling_thunder.meshcore_message_broker import (
    MeshcoreMessageBroker,
    MessageStream,
)
from rolling_thunder.meshcore_public_intake_protocol import ApprovedPublicChannel

S = MessageStream
SECRET = bytes(range(16))
POLICY = ApprovedPublicChannel(
    3, "#traffic", hashlib.sha256(SECRET).hexdigest(), True
)
INFO = bytes([0x12, 3]) + b"#traffic".ljust(32, b"\x00") + SECRET
STAMP = 1794405600
PUBLIC = (
    bytes([0x11, 0xE0, 0, 0, 3, 0xFF, 0])
    + STAMP.to_bytes(4, "little") + b"Crash I-71"
)
PRIVATE = b"\x10private payload for owner"


class FakeWriter:
    """Capture every permitted outbound serial command, never radio packets."""

    def __init__(self) -> None:
        self.commands: list[bytes] = []

    def write(self, payload: bytes) -> int:
        self.commands.append(payload)
        assert payload in (b"<\x02\x00\x1f\x03", b"<\x01\x00\x0a")
        return len(payload)


def _setup(tmp_path: Path, *, capacity: int = 100) -> tuple[
    MeshcoreMessageBroker, MeshcoreBrokerDrain, FakeWriter
]:
    base = tmp_path / "inbox"
    base.mkdir(mode=0o700)
    inbox = MeshcoreMessageBroker(
        base / "messages.db", capacity=capacity,
        consumers={
            "scout": frozenset({S.PUBLIC}),
            "operator": frozenset({S.PRIVATE, S.QUARANTINE}),
        },
    )
    drain = MeshcoreBrokerDrain(inbox, (POLICY,))
    writer = FakeWriter()
    drain.connected()
    return inbox, drain, writer


def _attest(drain: MeshcoreBrokerDrain, writer: FakeWriter) -> None:
    drain.tick(writer)
    assert writer.commands == [b"<\x02\x00\x1f\x03"]
    assert drain.receive(INFO)
    assert drain.status().ready


def test_private_committed_before_second_dequeue(tmp_path: Path) -> None:
    inbox, drain, writer = _setup(tmp_path)
    _attest(drain, writer)
    drain.tick(writer)
    assert writer.commands[-1] == b"<\x01\x00\x0a"
    assert drain.receive(PRIVATE)
    assert inbox.peek("operator", S.PRIVATE)[0].payload == PRIVATE
    assert drain.status().saved == 1
    drain.tick(writer)
    assert writer.commands.count(b"<\x01\x00\x0a") == 2
    assert drain.receive(PUBLIC)
    assert inbox.peek("scout", S.PUBLIC)[0].payload == "Crash I-71"
    drain.tick(writer)
    assert drain.receive(b"\x0a")
    count = len(writer.commands)
    drain.tick(writer)
    assert len(writer.commands) == count
    assert inbox.status() == {"public": 1, "private": 1, "quarantine": 0}


def test_wrong_channel_secret_fails_closed_without_dequeue(tmp_path: Path) -> None:
    _, drain, writer = _setup(tmp_path)
    drain.tick(writer)
    invalid = INFO[:-16] + bytes(16)
    assert drain.receive(invalid)
    assert drain.status().fault == "channel_identity_mismatch"
    drain.tick(writer)
    assert writer.commands == [b"<\x02\x00\x1f\x03"]


def test_capacity_stop_never_sends_next_dequeue(tmp_path: Path) -> None:
    inbox, drain, writer = _setup(tmp_path, capacity=1)
    _attest(drain, writer)
    drain.tick(writer)
    assert drain.receive(PRIVATE)
    assert inbox.status()["private"] == 1
    drain.tick(writer)
    assert drain.status().fault == "inbox_capacity_exhausted"
    assert writer.commands.count(b"<\x01\x00\x0a") == 1


def test_timeout_does_not_retry_pop_command(tmp_path: Path) -> None:
    _, drain, writer = _setup(tmp_path)
    _attest(drain, writer)
    drain.tick(writer)
    drain._deadline = -1
    drain.tick(writer)
    assert drain.status().fault == "serial_response_timeout"
    drain.tick(writer)
    assert writer.commands.count(b"<\x01\x00\x0a") == 1


def test_reconnect_revalidates_before_draining(tmp_path: Path) -> None:
    _, drain, writer = _setup(tmp_path)
    _attest(drain, writer)
    drain.disconnected()
    drain.connected()
    drain.tick(writer)
    assert writer.commands[-1] == b"<\x02\x00\x1f\x03"
    assert writer.commands.count(b"<\x01\x00\x0a") == 0


def test_no_more_messages_and_push_resume(tmp_path: Path) -> None:
    _, drain, writer = _setup(tmp_path)
    _attest(drain, writer)
    drain.tick(writer)
    assert drain.receive(b"\x0a")
    assert drain.receive(b"\x83")
    drain.tick(writer)
    assert writer.commands.count(b"<\x01\x00\x0a") == 2


def test_unsupported_async_frames_go_to_passive_observer(tmp_path: Path) -> None:
    _, drain, writer = _setup(tmp_path)
    _attest(drain, writer)
    drain.tick(writer)
    assert not drain.receive(b"\x80" + b"x" * 32)
    assert not drain.receive(b"\x88\x00\xf0more")
    assert drain.status().waiting_for_response


def test_store_failure_halts_without_logging_secret(tmp_path: Path) -> None:
    inbox, drain, writer = _setup(tmp_path)
    _attest(drain, writer)
    drain.tick(writer)
    def fail(*args: object, **kwargs: object) -> int:
        raise OSError("storage unplugged")
    inbox.store = fail  # type: ignore[method-assign]
    assert drain.receive(PRIVATE)
    assert drain.status().fault == "inbox_commit_failed"
    assert drain.status().saved == 0
    drain.tick(writer)
    assert writer.commands.count(b"<\x01\x00\x0a") == 1
