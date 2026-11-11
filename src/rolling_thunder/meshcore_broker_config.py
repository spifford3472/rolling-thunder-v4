"""Strict, owner-only broker opt-in configuration (no secrets in source).

The file contains SHA-256 fingerprints of high-entropy consumer bearer tokens
and approved channel keys; neither raw token nor MeshCore key is persisted here.
The operator supplies the unshared bearer token to each client out of band.
"""

from __future__ import annotations

import json
import re
import stat
from dataclasses import dataclass
from pathlib import Path

from rolling_thunder.meshcore_message_broker import MessageStream
from rolling_thunder.meshcore_public_intake_protocol import ApprovedPublicChannel

_FINGERPRINT = re.compile(r"[a-f0-9]{64}\Z")


@dataclass(frozen=True, slots=True)
class BrokerConsumer:
    """Static consumer ACL, keyed by a SHA-256 bearer token fingerprint."""

    name: str
    token_sha256: str
    streams: frozenset[MessageStream]

    def __post_init__(self) -> None:
        if (
            not self.name
            or len(self.name) > 64
            or not self.name.replace("-", "").replace("_", "").isalnum()
            or not _FINGERPRINT.fullmatch(self.token_sha256)
            or not self.streams
        ):
            raise ValueError("Invalid broker consumer ACL")


@dataclass(frozen=True, slots=True)
class BrokerRuntimeConfig:
    """Validated minimal configuration; no plaintext key or token material."""

    channels: tuple[ApprovedPublicChannel, ...]
    consumers: tuple[BrokerConsumer, ...]

    def __post_init__(self) -> None:
        if not self.channels or len(self.channels) > 8:
            raise ValueError("Broker must specify 1-8 approved channels")
        if len({channel.slot for channel in self.channels}) != len(self.channels):
            raise ValueError("Broker channel slots must be unique")
        if not all(channel.approved_for_public_intake for channel in self.channels):
            raise ValueError("Cannot ingest an unapproved channel")
        if not self.consumers or len(self.consumers) > 16:
            raise ValueError("Broker needs 1-16 authorized consumers")
        if len({item.name for item in self.consumers}) != len(self.consumers):
            raise ValueError("Duplicate broker consumer name")
        if len({item.token_sha256 for item in self.consumers}) != len(self.consumers):
            raise ValueError("Duplicate broker bearer identity")


def load_broker_config(path: Path) -> BrokerRuntimeConfig:
    """Read strict JSON only from an existing mode-0600 regular file."""
    if path.is_symlink() or not path.is_file():
        raise PermissionError("Broker configuration must be a regular file")
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise PermissionError("Broker configuration is not owner-only")
    with path.open("rb") as handle:
        raw = handle.read(8193)
    if len(raw) > 8192:
        raise ValueError("Broker configuration too large")
    decoded = json.loads(raw)
    if not isinstance(decoded, dict) or set(decoded) != {
        "schema", "approved_channels", "consumers"
    } or decoded["schema"] != "meshcore/broker-config/v1":
        raise ValueError("Invalid broker configuration schema")
    channels_raw, consumers_raw = (
        decoded["approved_channels"], decoded["consumers"]
    )
    if not isinstance(channels_raw, list) or not isinstance(consumers_raw, list):
        raise TypeError("Invalid broker configuration entries")
    channels: list[ApprovedPublicChannel] = []
    for item in channels_raw:
        if not isinstance(item, dict) or set(item) != {
            "slot", "name", "secret_sha256", "approved_for_public_intake"
        }:
            raise ValueError("Invalid channel configuration fields")
        if (
            type(item["slot"]) is not int
            or type(item["name"]) is not str
            or type(item["secret_sha256"]) is not str
            or item["approved_for_public_intake"] is not True
        ):
            raise ValueError("Invalid channel configuration types")
        channels.append(ApprovedPublicChannel(**item))
    consumers: list[BrokerConsumer] = []
    for item in consumers_raw:
        if not isinstance(item, dict) or set(item) != {
            "name", "token_sha256", "streams"
        } or not all(
            isinstance(item[k], str) for k in ("name", "token_sha256")
        ) or not isinstance(item["streams"], list):
            raise ValueError("Invalid consumer fields")
        if not all(isinstance(s, str) for s in item["streams"]):
            raise TypeError("Consumer streams must be strings")
        try:
            streams = frozenset(MessageStream(s) for s in item["streams"])
        except ValueError as error:
            raise ValueError("Unrecognized consumer message stream") from error
        consumers.append(
            BrokerConsumer(item["name"], item["token_sha256"], streams)
        )
    return BrokerRuntimeConfig(tuple(channels), tuple(consumers))
