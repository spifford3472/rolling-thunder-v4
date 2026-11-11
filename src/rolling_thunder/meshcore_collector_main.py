"""Independent, receive-only MeshCore daemon with Unix-socket read API.

Only this process owns the Heltec serial port and durable observation database.
No MeshCore command encoder or outbound RF action is exposed.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import socketserver
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any

from rolling_thunder.meshcore_gps_bridge import read_meshcore_gps_snapshot
from rolling_thunder.meshcore_observation_repository import MeshcoreObservationRepository
from rolling_thunder.meshcore_passive import node_role_from_type_code
from rolling_thunder.meshcore_passive_worker import MeshcorePassiveWorker
from rolling_thunder.meshcore_serial_service import MeshcorePassiveSerialService

_LOGGER = logging.getLogger(__name__)
_DEFAULT_DEVICE = (
    "/dev/serial/by-path/"
    "platform-fd500000.pcie-pci-0000:01:00.0-usb-0:1.1.1:1.0"
)


class _LocalHttpServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    """Local-only read-only endpoint; process shutdown is independent."""
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self, socket_path: str, db: Path, collector: MeshcorePassiveSerialService
    ) -> None:
        self.database_path = db
        self.collector = collector
        super().__init__(socket_path, _Handler)


class _Handler(BaseHTTPRequestHandler):
    """Small versioned JSON API for Rolling Thunder and SCOUT."""

    server: _LocalHttpServer

    def do_GET(self) -> None:
        """Serve only bounded, read-only, versioned endpoints."""
        if self.path not in ("/v1/health", "/v1/nodes", "/v1/signals"):
            self._reply(404, {"error": "not_found"})
            return
        if self.path == "/v1/health":
            status = self.server.collector.status()
            self._reply(200, {
                "schema": "meshcore/v1",
                "running": status.running,
                "device_connected": status.device_connected,
                "last_error": status.last_error,
                "received": status.worker.received,
                "stored": status.worker.stored,
                "dropped": status.worker.dropped,
                "write_errors": status.worker.write_errors,
            })
            return
        try:
            with sqlite3.connect(
                f"file:{self.server.database_path}?mode=ro", uri=True
            ) as connection:
                if self.path == "/v1/nodes":
                    rows = connection.execute(
                        """
                        SELECT public_key_hex, advertised_name, node_type_code,
                               first_seen_utc, last_seen_utc, observation_count
                        FROM meshcore_observed_nodes
                        ORDER BY last_seen_utc DESC LIMIT 100
                        """
                    ).fetchall()
                    keys: tuple[str, ...] = ("public_key_hex", "name", "type_code",
                            "first_seen_utc", "last_seen_utc", "count")
                else:
                    rows = connection.execute(
                        """
                        SELECT received_at_utc, rssi_dbm, snr_db, gps_status
                        FROM meshcore_signal_samples
                        ORDER BY sample_id DESC LIMIT 100
                        """
                    ).fetchall()
                    keys = ("received_at_utc", "rssi_dbm", "snr_db", "gps_status")
            items = [dict(zip(keys, row)) for row in rows]
            if self.path == "/v1/nodes":
                for item in items:
                    item["role"] = node_role_from_type_code(item["type_code"])
            self._reply(200, {"schema": "meshcore/v1", "items": items})
        except sqlite3.Error:
            _LOGGER.exception("MeshCore read-only query failed")
            self._reply(503, {"error": "storage_unavailable"})

    def do_POST(self) -> None:
        """The local query API intentionally exposes no mutation."""
        self._reply(405, {"error": "read_only"})

    def log_message(self, format: str, *args: Any) -> None:
        """Avoid logging URLs or user-supplied payloads."""
        return

    def _reply(self, status: int, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main(argv: list[str] | None = None) -> int:
    """Run collector until SIGTERM; serial failures never kill the HTTP API."""
    parser = argparse.ArgumentParser(description="Local-only passive MeshCore collector")
    parser.add_argument("--device", type=Path, default=Path(_DEFAULT_DEVICE))
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--gps-snapshot", type=Path, required=True)
    parser.add_argument("--socket", type=Path, required=True)
    options = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    options.socket.parent.mkdir(parents=True, exist_ok=True)
    if options.socket.exists():
        raise RuntimeError("Existing MeshCore API socket; refuse double owner")
    repository = MeshcoreObservationRepository(options.database)
    writer = MeshcorePassiveWorker(
        repository, lambda: read_meshcore_gps_snapshot(options.gps_snapshot)
    )
    collector = MeshcorePassiveSerialService(writer, options.device)
    stop = threading.Event()

    def request_stop(_signal: int, _frame: object) -> None:
        """Signal-only handler; shutdown is run outside signal context."""
        stop.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    collector.start()
    try:
        server = _LocalHttpServer(str(options.socket), options.database, collector)
        os.chmod(options.socket, 0o600)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        try:
            stop.wait()
        finally:
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=3)
    finally:
        collector.stop()
        options.socket.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
