"""Capability-protected local Unix API for independent MeshCore inbox cursors.

Runs on a *separate* mode-0600 Unix socket; the existing observation API
remains read-only. Each consumer has a distinct high-entropy bearer secret
whose SHA-256 fingerprint alone is present in protected configuration.
No network/TCP listener, shell, radio, CAT or MeshCore RF command exists here.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import socketserver
import sqlite3
from http.server import BaseHTTPRequestHandler
from typing import Any
from urllib.parse import parse_qs, urlsplit

from rolling_thunder.meshcore_broker_config import BrokerConsumer
from rolling_thunder.meshcore_message_broker import (
    MeshcoreMessageBroker,
    MessageStream,
)

_MAX_TOKEN_LENGTH = 160
_MAX_REQUEST_BYTES = 1024


class MeshcoreBrokerApiServer(
    socketserver.ThreadingMixIn, socketserver.UnixStreamServer
):
    """One local-only service, with exact registered consumer identity."""

    daemon_threads = True
    allow_reuse_address = False

    def __init__(
        self,
        socket_path: str,
        inbox: MeshcoreMessageBroker,
        consumers: tuple[BrokerConsumer, ...],
    ) -> None:
        self.inbox = inbox
        self.consumers = consumers
        super().__init__(socket_path, _BrokerHandler)


class _BrokerHandler(BaseHTTPRequestHandler):
    """Read per-consumer streams and accept their independent acknowledgments."""

    server: MeshcoreBrokerApiServer

    def _consumer(self) -> BrokerConsumer | None:
        """Authenticate before parsing any private message request data."""
        value = self.headers.get("Authorization", "")
        if not value.startswith("Bearer "):
            return None
        token = value[7:]
        if not 32 <= len(token) <= _MAX_TOKEN_LENGTH or not token.isascii():
            return None
        digest = hashlib.sha256(token.encode("ascii")).hexdigest()
        for candidate in self.server.consumers:
            if hmac.compare_digest(digest, candidate.token_sha256):
                return candidate
        return None

    def _reply(self, code: int, data: dict[str, Any]) -> None:
        """No-store responses protect personal and quarantine payloads."""
        payload = json.dumps(data, allow_nan=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        """Fetch a bounded batch without advancing any other consumer."""
        consumer = self._consumer()
        if consumer is None:
            self._reply(401, {"error": "unauthorized"})
            return
        parsed = urlsplit(self.path)
        if parsed.path == "/v1/status" and not parsed.query:
            try:
                counts = self.server.inbox.status()
                self._reply(200, {
                    "schema": "meshcore/broker/v1",
                    "counts": {
                        stream.value: counts[stream.value]
                        for stream in consumer.streams
                    },
                })
            except sqlite3.Error:
                self._reply(503, {"error": "inbox_unavailable"})
            return
        prefix = "/v1/messages/"
        if not parsed.path.startswith(prefix):
            self._reply(404, {"error": "not_found"})
            return
        try:
            stream = MessageStream(parsed.path[len(prefix):])
            params = parse_qs(parsed.query, strict_parsing=True)
            if set(params) - {"limit"} or any(len(v) != 1 for v in params.values()):
                raise ValueError
            limit = int(params.get("limit", ["25"])[0])
            if stream not in consumer.streams:
                self._reply(403, {"error": "forbidden"})
                return
            batch = self.server.inbox.peek(consumer.name, stream, limit=limit)
            items = []
            for message in batch:
                value = message.payload
                items.append({
                    "id": message.message_id,
                    "received_at_utc": message.received_at.isoformat(),
                    "channel_slot": message.channel_slot,
                    "channel_name": message.channel_name,
                    "sender_claimed_at_utc": (
                        message.sender_claimed_at.isoformat()
                        if message.sender_claimed_at is not None else None
                    ),
                    "payload_encoding": "utf-8" if isinstance(value, str) else "base64",
                    "payload": (
                        value if isinstance(value, str)
                        else base64.b64encode(value).decode("ascii")
                    ),
                })
        except (ValueError, TypeError):
            self._reply(400, {"error": "invalid_request"})
            return
        except sqlite3.Error:
            self._reply(503, {"error": "inbox_unavailable"})
            return
        self._reply(200, {
            "schema": "meshcore/broker/v1",
            "stream": stream.value,
            "items": items,
        })

    def do_POST(self) -> None:
        """Acknowledge only the authenticated consumer's own stream cursor."""
        consumer = self._consumer()
        if consumer is None:
            self._reply(401, {"error": "unauthorized"})
            return
        if self.path != "/v1/ack":
            self._reply(404, {"error": "not_found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 1 <= length <= _MAX_REQUEST_BYTES:
                raise ValueError
            request = json.loads(self.rfile.read(length))
            if not isinstance(request, dict) or set(request) != {
                "stream", "message_id"
            }:
                raise ValueError
            stream = MessageStream(request["stream"])
            message_id = request["message_id"]
            if type(message_id) is not int:
                raise ValueError
            if stream not in consumer.streams:
                self._reply(403, {"error": "forbidden"})
                return
            self.server.inbox.acknowledge(consumer.name, stream, message_id)
        except (ValueError, KeyError, TypeError, json.JSONDecodeError):
            self._reply(400, {"error": "invalid_request"})
            return
        except sqlite3.Error:
            self._reply(503, {"error": "inbox_unavailable"})
            return
        self._reply(200, {"schema": "meshcore/broker/v1", "acknowledged": True})

    def do_PUT(self) -> None:
        """No message insertion or bulk API mutation is authorized."""
        self._reply(405, {"error": "method_not_allowed"})

    def do_DELETE(self) -> None:
        """Never delete durable personal or public messages over HTTP."""
        self._reply(405, {"error": "method_not_allowed"})

    def log_message(self, format: str, *args: Any) -> None:
        """Avoid logging private URLs, tokens, message bodies or identifiers."""
        return
