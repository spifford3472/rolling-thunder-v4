"""Broker opt-in flags must fail before any serial/socket side effect."""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

from rolling_thunder.meshcore_collector_main import (
    _prepare_local_socket,
    main,
)


def _args(tmp_path: Path) -> list[str]:
    return [
        "--database", str(tmp_path / "old.db"),
        "--gps-snapshot", str(tmp_path / "gps.json"),
        "--socket", str(tmp_path / "old.sock"),
    ]


def test_message_broker_not_enabled_with_partial_arguments(
    tmp_path: Path,
) -> None:
    cases = [
        ["--enable-message-broker"],
        ["--broker-database", str(tmp_path / "inbox.db")],
        [
            "--enable-message-broker",
            "--broker-database", str(tmp_path / "inbox.db"),
            "--broker-config", str(tmp_path / "config.json"),
        ],
        [
            "--enable-message-broker",
            "--broker-config", str(tmp_path / "config.json"),
            "--broker-database", str(tmp_path / "old.db"),
            "--broker-socket", str(tmp_path / "old.sock"),
        ],
    ]
    for extra in cases:
        with pytest.raises(SystemExit):
            main(_args(tmp_path) + extra)
        assert not (tmp_path / "old.sock").exists()
        assert not (tmp_path / "old.db").exists()


def test_rejects_socket_that_has_live_owner(tmp_path: Path) -> None:
    path = tmp_path / "owned.sock"
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as owner:
        owner.bind(str(path))
        owner.listen(1)
        with pytest.raises(RuntimeError, match="owner"):
            _prepare_local_socket(path)
        assert path.exists()


def test_removes_only_stale_socket_inode(tmp_path: Path) -> None:
    path = tmp_path / "stale.sock"
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as previous:
        previous.bind(str(path))
    _prepare_local_socket(path)
    assert not path.exists()


def test_non_socket_path_never_removed(tmp_path: Path) -> None:
    path = tmp_path / "data"
    path.write_text("precious", encoding="utf-8")
    with pytest.raises(RuntimeError):
        _prepare_local_socket(path)
    assert path.read_text() == "precious"
