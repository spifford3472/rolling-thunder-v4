"""Authenticated local Unix API tests; no network or real MeshCore device."""

from __future__ import annotations

import hashlib
import http.client
import json
import socket
import threading
from datetime import UTC, datetime
from pathlib import Path

from rolling_thunder.meshcore_broker_api import MeshcoreBrokerApiServer
from rolling_thunder.meshcore_broker_config import BrokerConsumer
from rolling_thunder.meshcore_message_broker import (
    MeshcoreMessageBroker,
    MessageStream,
)
from rolling_thunder.meshcore_public_intake_protocol import VerifiedChannel

TOKEN_PUBLIC = "scout-" + "a" * 64
TOKEN_PRIVATE = "owner-" + "b" * 64
S = MessageStream
NOW = datetime(2026, 11, 11, 19, 0, tzinfo=UTC)


class SocketConnection(http.client.HTTPConnection):
    """Connect only to a test-only Unix socket."""

    def __init__(self, path: Path) -> None:
        super().__init__("localhost", timeout=2)
        self.path = path

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(2)
        self.sock.connect(str(self.path))


def _request(
    path: Path, method: str, route: str, *,
    token: str | None = None, body: dict[str, object] | None = None
) -> tuple[int, dict[str, object]]:
    con = SocketConnection(path)
    headers = {}
    if token is not None:
        headers["Authorization"] = "Bearer " + token
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    try:
        con.request(method, route, body=data, headers=headers)
        response = con.getresponse()
        assert response.getheader("Cache-Control") == "no-store"
        decoded = json.loads(response.read())
        assert isinstance(decoded, dict)
        return response.status, decoded
    finally:
        con.close()


def test_public_and_private_capabilities_and_acks(tmp_path: Path) -> None:
    base = tmp_path / "inbox"
    base.mkdir(mode=0o700)
    clients = (
        BrokerConsumer(
            "scout", hashlib.sha256(TOKEN_PUBLIC.encode()).hexdigest(),
            frozenset({S.PUBLIC}),
        ),
        BrokerConsumer(
            "owner", hashlib.sha256(TOKEN_PRIVATE.encode()).hexdigest(),
            frozenset({S.PUBLIC, S.PRIVATE, S.QUARANTINE}),
        ),
    )
    broker = MeshcoreMessageBroker(
        base / "broker.db", consumers={item.name: item.streams for item in clients}
    )
    broker.store(b"\x10hello-secret", received_at=NOW, verified_channels={})
    frame = (
        bytes((0x11, 0xE0, 0, 0, 3, 0xFF, 0))
        + (1794405600).to_bytes(4, "little") + b"Traffic closure"
    )
    broker.store(frame, received_at=NOW, verified_channels={
        3: VerifiedChannel(3, "#traffic")
    })
    path = tmp_path / "api.sock"
    server = MeshcoreBrokerApiServer(str(path), broker, clients)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        status, result = _request(path, "GET", "/v1/messages/public")
        assert status == 401
        status, result = _request(
            path, "GET", "/v1/messages/private", token=TOKEN_PUBLIC
        )
        assert status == 403
        status, result = _request(
            path, "GET", "/v1/messages/public", token=TOKEN_PUBLIC
        )
        assert status == 200
        items = result["items"]
        assert isinstance(items, list) and len(items) == 1
        public_id = items[0]["id"]
        assert items[0]["payload"] == "Traffic closure"
        assert "hello-secret" not in json.dumps(result)

        status, result = _request(
            path, "GET", "/v1/messages/private", token=TOKEN_PRIVATE
        )
        assert status == 200
        private_items = result["items"]
        assert isinstance(private_items, list) and len(private_items) == 1
        assert private_items[0]["payload_encoding"] == "base64"
        status, result = _request(
            path, "POST", "/v1/ack", token=TOKEN_PUBLIC,
            body={"stream": "public", "message_id": public_id},
        )
        assert status == 200
        status, result = _request(
            path, "GET", "/v1/messages/public", token=TOKEN_PUBLIC
        )
        assert result["items"] == []
        # Operator still sees the same public message: separate cursor.
        status, result = _request(
            path, "GET", "/v1/messages/public", token=TOKEN_PRIVATE
        )
        assert isinstance(result["items"], list) and len(result["items"]) == 1
        status, result = _request(
            path, "POST", "/v1/ack", token=TOKEN_PUBLIC,
            body={"stream": "private", "message_id": 1},
        )
        assert status == 403
        status, result = _request(
            path, "GET", "/v1/status", token=TOKEN_PUBLIC
        )
        counts = result["counts"]
        assert isinstance(counts, dict)
        assert set(counts) == {"public"}
        assert counts["public"] == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_invalid_tokens_routes_and_methods(tmp_path: Path) -> None:
    base = tmp_path / "private"
    base.mkdir(mode=0o700)
    token = "t" * 64
    consumer = BrokerConsumer(
        "scout", hashlib.sha256(token.encode()).hexdigest(),
        frozenset({S.PUBLIC}),
    )
    inbox = MeshcoreMessageBroker(
        base / "db", consumers={"scout": frozenset({S.PUBLIC})}
    )
    path = tmp_path / "api.sock"
    server = MeshcoreBrokerApiServer(str(path), inbox, (consumer,))
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        for route in ("/v1/messages/public?limit=999", "/v1/messages/public?x=1"):
            assert _request(path, "GET", route, token=token)[0] == 400
        assert _request(path, "GET", "/v1/messages/unknown", token=token)[0] == 400
        assert _request(path, "GET", "/v1/secrets", token=token)[0] == 404
        assert _request(path, "PUT", "/v1/messages/public", token=token)[0] == 405
        assert _request(path, "DELETE", "/v1/messages/public", token=token)[0] == 405
        assert _request(path, "GET", "/v1/status", token="invalid" * 10)[0] == 401
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
