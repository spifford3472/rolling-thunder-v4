"""Broker configuration is owner-only, strict, and contains no raw secrets."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from rolling_thunder.meshcore_broker_config import load_broker_config
from rolling_thunder.meshcore_message_broker import MessageStream

S = MessageStream
TOKEN = "owner-" + "x" * 64
KEY = b"\x01" * 16


def _config() -> dict[str, object]:
    return {
        "schema": "meshcore/broker-config/v1",
        "approved_channels": [
            {
                "slot": 3,
                "name": "#traffic",
                "secret_sha256": hashlib.sha256(KEY).hexdigest(),
                "approved_for_public_intake": True,
            }
        ],
        "consumers": [
            {
                "name": "operator",
                "token_sha256": hashlib.sha256(TOKEN.encode()).hexdigest(),
                "streams": ["private", "public", "quarantine"],
            },
            {
                "name": "scout",
                "token_sha256": hashlib.sha256(b"x" * 64).hexdigest(),
                "streams": ["public"],
            },
        ],
    }


def _write(path: Path, config: dict[str, object]) -> Path:
    path.write_text(json.dumps(config), encoding="utf-8")
    os.chmod(path, 0o600)
    return path


def test_strict_owner_config_and_content_bounded(tmp_path: Path) -> None:
    path = _write(tmp_path / "broker.json", _config())
    result = load_broker_config(path)
    assert len(result.channels) == 1
    assert result.channels[0].name == "#traffic"
    assert S.PRIVATE in result.consumers[0].streams
    assert S.PRIVATE not in result.consumers[1].streams
    assert TOKEN not in path.read_text()
    assert KEY.hex() not in path.read_text()


@pytest.mark.parametrize("change", ["duplicate", "unapproved", "bad_stream", "bad_hash",
                                     "bad_schema", "bad_type"])
def test_invalid_config_fails_closed(tmp_path: Path, change: str) -> None:
    config = _config()
    channels = config["approved_channels"]
    consumers = config["consumers"]
    assert isinstance(channels, list) and isinstance(consumers, list)
    if change == "duplicate":
        channels.append(channels[0].copy())
    elif change == "unapproved":
        channels[0]["approved_for_public_intake"] = False
    elif change == "bad_stream":
        consumers[0]["streams"] = ["radio-transmit"]
    elif change == "bad_hash":
        consumers[0]["token_sha256"] = "plaintext-token"
    elif change == "bad_schema":
        config["schema"] = "unknown"
    else:
        consumers[0]["streams"] = [False]
    with pytest.raises((ValueError, TypeError)):
        load_broker_config(_write(tmp_path / "broker.json", config))


def test_public_file_permissions_and_symlinks_rejected(tmp_path: Path) -> None:
    path = _write(tmp_path / "broker.json", _config())
    os.chmod(path, 0o644)
    with pytest.raises(PermissionError):
        load_broker_config(path)
    os.chmod(path, 0o600)
    link = tmp_path / "alias.json"
    link.symlink_to(path)
    with pytest.raises(PermissionError):
        load_broker_config(link)


def test_oversized_config_rejected(tmp_path: Path) -> None:
    path = tmp_path / "huge.json"
    path.write_bytes(b"x" * 8193)
    os.chmod(path, 0o600)
    with pytest.raises(ValueError, match="large"):
        load_broker_config(path)
