"""Optional standalone loopback/private PSK evidence HTTP server.

Never starts from the existing PSK worker; requires explicit configuration,
independent token injection, and an existing normalized history database.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar

from rolling_thunder.forge_psk_evidence_api import PrivatePskEvidenceApi
from rolling_thunder.forge_psk_evidence_snapshot import PskEvidenceSnapshotService


def validate_normalized_history(path: Path) -> None:
    """Fail closed rather than silently interpreting a different PSK schema."""
    if not path.is_file():
        raise ValueError("normalized PSK history file does not exist")
    try:
        with sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True, timeout=0.2) as db:
            columns = {
                row[1] for row in db.execute("PRAGMA table_info(psk_reception)")
            }
    except sqlite3.Error as exc:
        raise ValueError("normalized PSK history unreadable") from exc
    required = {
        "sender_callsign", "receiver_callsign",
        "receiver_locator_normalized", "frequency_hz",
        "flow_start_utc", "snr_db", "mode",
    }
    if not required <= columns:
        raise ValueError("normalized PSK history schema incomplete")


def make_handler(api: PrivatePskEvidenceApi) -> type[BaseHTTPRequestHandler]:
    """HTTP adapter with GET-only requests and no logging of bearer tokens."""

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "RT-PSK-Evidence/1"
        api_app: ClassVar[PrivatePskEvidenceApi] = api

        def do_GET(self) -> None:
            reply = self.api_app.handle(
                "GET", self.path, authorization=self.headers.get("Authorization"),
            )
            self.send_response(reply.status_code)
            for key, value in reply.headers:
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(reply.body)))
            self.end_headers()
            self.wfile.write(reply.body)

        def do_POST(self) -> None:
            self.send_error(405, "Method not allowed")

        def log_message(self, _format: str, *args: object) -> None:
            """Do not log query strings, credentials, or path parameters."""

    return Handler


def main() -> int:
    parser = argparse.ArgumentParser(description="Explicit opt-in private PSK evidence listener")
    parser.add_argument("--normalized-db", type=Path, required=True)
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8791)
    parser.add_argument("--token-env", default="ROLLING_THUNDER_PSK_EVIDENCE_TOKEN")
    args = parser.parse_args()
    if args.bind != "127.0.0.1":
        parser.error("only loopback binding is supported until private network review")
    if not 1 <= args.port <= 65535:
        parser.error("port invalid")
    validate_normalized_history(args.normalized_db)
    token = os.environ.get(args.token_env, "")
    api = PrivatePskEvidenceApi(
        PskEvidenceSnapshotService(args.normalized_db), bearer_token=token,
    )
    with ThreadingHTTPServer((args.bind, args.port), make_handler(api)) as server:
        server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
