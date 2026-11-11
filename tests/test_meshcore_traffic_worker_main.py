"""Standalone worker CLI uses local single-instance lock and safe one-shot path."""

from __future__ import annotations

import fcntl
import hashlib
import os
import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest

from rolling_thunder.meshcore_broker_api import MeshcoreBrokerApiServer
from rolling_thunder.meshcore_broker_config import BrokerConsumer
from rolling_thunder.meshcore_message_broker import MeshcoreMessageBroker, MessageStream
from rolling_thunder.meshcore_public_intake_protocol import VerifiedChannel
from rolling_thunder.meshcore_traffic_ledger import TrafficLedgerError
from rolling_thunder.meshcore_traffic_worker_main import main


def _args(private: Path, socket: Path, token: Path) -> list[str]:
    return [
        "--socket", str(socket),
        "--credential", str(token),
        "--database", str(private / "traffic.db"),
        "--traffic-slot", "1",
        "--once",
    ]


def test_one_shot_processes_public_and_preserves_other_consumer(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    token_path = private / "client.token"
    token = "q" * 64
    token_path.write_text(token + "\n")
    os.chmod(token_path, 0o600)
    broker = MeshcoreMessageBroker(
        private / "broker.db",
        consumers={
            "rolling-thunder": frozenset({MessageStream.PUBLIC}),
            "scout": frozenset({MessageStream.PUBLIC}),
        },
    )
    broker.store(
        bytes((0x11, 0xE0, 0, 0, 1, 0xFF, 0))
        + (1794405600).to_bytes(4, "little")
        + b"Crash on I-75 northbound",
        received_at=datetime(2026, 11, 11, tzinfo=UTC),
        verified_channels={1: VerifiedChannel(1, "#traffic")},
    )
    socket = tmp_path / "broker.sock"
    server = MeshcoreBrokerApiServer(
        str(socket), broker,
        (BrokerConsumer(
            "rolling-thunder", hashlib.sha256(token.encode()).hexdigest(),
            frozenset({MessageStream.PUBLIC}),
        ),),
    )
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        assert main(_args(private, socket, token_path)) == 0
        output = capsys.readouterr().out
        assert "1 new candidates" in output
        assert token not in output
        assert broker.peek("rolling-thunder", MessageStream.PUBLIC) == ()
        assert len(broker.peek("scout", MessageStream.PUBLIC)) == 1
        assert main(_args(private, socket, token_path)) == 0
        assert "0 public records" in capsys.readouterr().out
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_local_lock_rejects_second_worker_before_read(
    tmp_path: Path,
) -> None:
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    lock = private / "traffic.db.lock"
    fd = os.open(lock, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(TrafficLedgerError, match="already running"):
            main(_args(private, tmp_path / "missing.sock", private / "missing.token"))
    finally:
        os.close(fd)
    assert not (private / "traffic.db").exists()


def test_cli_rejects_invalid_cadence_and_batch(
    tmp_path: Path,
) -> None:
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    for bad in (
        ["--poll-seconds", "0.5"],
        ["--poll-seconds", "121"],
        ["--batch-size", "0"],
    ):
        args = _args(private, tmp_path / "broker.sock", private / "token")
        args.extend(bad)
        with pytest.raises(SystemExit) as error:
            main(args)
        assert error.value.code == 2
    assert not (private / "traffic.db").exists()
