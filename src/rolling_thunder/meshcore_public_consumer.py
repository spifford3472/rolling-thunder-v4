"""Bounded capability-authenticated MeshCore broker consumer.

This transport is read-only by default and never opens serial, SQLite,
CAT/PTT, or a network TCP connection. Acknowledgement requires an explicit
method call after application-specific durable processing.
"""

from __future__ import annotations

import http.client
import json
import os
import socket
import stat
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

_MAX_RESPONSE_BYTES = 65536
_MAX_TOKEN_CHARS = 160


class MeshcoreConsumerError(RuntimeError):
    """Sanitized consumer transport/protocol failure (never bearer or payload)."""


@dataclass(frozen=True, slots=True)
class PublicBrokerMessage:
    """Public data only; remote sender identity is not authenticated."""

    message_id: int
    channel_name: str
    channel_slot: int
    text: str
    received_at: datetime
    claimed_at: datetime | None


class _UnixConnection(http.client.HTTPConnection):
    """One HTTP exchange over an owner-only local Unix-domain socket."""

    def __init__(self, socket_path: Path, timeout_s: float) -> None:
        super().__init__("localhost", timeout=timeout_s)
        self.socket_path = socket_path

    def connect(self) -> None:
        conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        conn.settimeout(self.timeout)
        try:
            conn.connect(str(self.socket_path))
        except BaseException:
            conn.close()
            raise
        self.sock = conn


def _read_token(path: Path) -> str:
    """Open the credential with no symlink traversal and strict file modes."""
    if path.is_symlink() or not path.is_file():
        raise MeshcoreConsumerError("Consumer credential unavailable")
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise MeshcoreConsumerError("Consumer credential permissions unsafe")
    if path.stat().st_uid != os.geteuid():
        raise MeshcoreConsumerError("Consumer credential owner mismatch")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        raw = os.read(fd, 256)
    finally:
        os.close(fd)
    if len(raw) > _MAX_TOKEN_CHARS + 1:
        raise MeshcoreConsumerError("Consumer credential invalid")
    try:
        token = raw.decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise MeshcoreConsumerError("Consumer credential invalid") from exc
    if not 32 <= len(token) <= _MAX_TOKEN_CHARS or any(
        ch.isspace() for ch in token
    ):
        raise MeshcoreConsumerError("Consumer credential invalid")
    return token


class MeshcorePublicConsumer:
    """Side-effect-free public-channel snapshots with explicit opt-in ACK."""

    def __init__(
        self,
        socket_path: Path,
        credential_path: Path,
        *,
        timeout_s: float = 1.5,
    ) -> None:
        if not 0.1 <= timeout_s <= 5:
            raise ValueError("Invalid broker timeout")
        self._socket_path = socket_path
        self._credential_path = credential_path
        self._timeout_s = timeout_s

    def _request(
        self, method: str, route: str, body: dict[str, object] | None = None
    ) -> dict[str, Any]:
        token = _read_token(self._credential_path)
        connection = _UnixConnection(self._socket_path, self._timeout_s)
        payload = json.dumps(body, separators=(",", ":")) if body else None
        headers = {"Authorization": "Bearer " + token}
        if body is not None:
            headers["Content-Type"] = "application/json"
        try:
            connection.request(method, route, body=payload, headers=headers)
            response = connection.getresponse()
            length = response.getheader("Content-Length")
            if length is None or not length.isdecimal() or int(length) > _MAX_RESPONSE_BYTES:
                raise MeshcoreConsumerError("Broker response size invalid")
            raw = response.read(_MAX_RESPONSE_BYTES + 1)
            if len(raw) != int(length):
                raise MeshcoreConsumerError("Broker response length mismatch")
            if response.status != 200:
                raise MeshcoreConsumerError("Broker unavailable or access denied")
            data = json.loads(raw)
        except (OSError, TimeoutError, http.client.HTTPException, ValueError) as exc:
            raise MeshcoreConsumerError("Broker communication failed") from exc
        finally:
            connection.close()
        if not isinstance(data, dict):
            raise MeshcoreConsumerError("Broker response format invalid")
        return data

    def preview(self, *, limit: int = 25) -> tuple[PublicBrokerMessage, ...]:
        """Return only public verified channel text, never advance cursors."""
        if not 1 <= limit <= 100:
            raise ValueError("Invalid message batch size")
        document = self._request("GET", f"/v1/messages/public?limit={limit}")
        if document.get("schema") != "meshcore/broker/v1" or document.get("stream") != "public":
            raise MeshcoreConsumerError("Broker response version mismatch")
        items = document.get("items")
        if not isinstance(items, list) or len(items) > limit:
            raise MeshcoreConsumerError("Broker response batch invalid")
        output: list[PublicBrokerMessage] = []
        previous = 0
        for item in items:
            if not isinstance(item, dict):
                raise MeshcoreConsumerError("Broker item invalid")
            identifier = item.get("id")
            name = item.get("channel_name")
            slot = item.get("channel_slot")
            body = item.get("payload")
            if (
                type(identifier) is not int or identifier <= previous
                or type(slot) is not int or not 0 <= slot < 8
                or not isinstance(name, str) or not name
                or not isinstance(body, str) or not body.strip()
                or len(body) > 512
                or item.get("payload_encoding") != "utf-8"
            ):
                raise MeshcoreConsumerError("Broker message invalid")
            try:
                received = datetime.fromisoformat(item["received_at_utc"])
                claimed_raw = item.get("sender_claimed_at_utc")
                claimed = datetime.fromisoformat(claimed_raw) if claimed_raw else None
            except (KeyError, TypeError, ValueError) as exc:
                raise MeshcoreConsumerError("Broker timestamp invalid") from exc
            if received.utcoffset() is None or (
                claimed is not None and claimed.utcoffset() is None
            ):
                raise MeshcoreConsumerError("Broker timestamp lacks timezone")
            output.append(
                PublicBrokerMessage(identifier, name, slot, body, received, claimed)
            )
            previous = identifier
        return tuple(output)

    def acknowledge_processed(self, message_id: int) -> None:
        """Advance only this authenticated public consumer after explicit processing.

        An external caller, not this client, must guarantee that the message
        was durably processed and is eligible for acknowledgement.
        """
        if type(message_id) is not int or message_id < 1:
            raise ValueError("Invalid public message identifier")
        response = self._request(
            "POST", "/v1/ack", {"stream": "public", "message_id": message_id}
        )
        if response.get("schema") != "meshcore/broker/v1" or (
            response.get("acknowledged") is not True
        ):
            raise MeshcoreConsumerError("Broker acknowledgement unverified")
