"""Local-only independent MeshCore collector API tests."""
import http.client
import json
import socket
import sqlite3
import threading
from pathlib import Path

from rolling_thunder.meshcore_collector_main import _LocalHttpServer
from rolling_thunder.meshcore_observation_repository import MeshcoreObservationRepository


class _WorkerState:
    received = 4
    stored = 3
    dropped = 1
    write_errors = 0


class _CollectorState:
    running = True
    device_connected = True
    last_error = None
    worker = _WorkerState()


class _FakeCollector:
    def status(self) -> _CollectorState:
        return _CollectorState()


def _request(socket_path: Path, method: str, path: str) -> tuple[int, dict]:
    """Make a local-only HTTP request without a TCP listener."""
    class Connection(http.client.HTTPConnection):
        def connect(self) -> None:
            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.sock.connect(str(socket_path))

    connection = Connection("localhost")
    try:
        connection.request(method, path)
        response = connection.getresponse()
        return response.status, json.loads(response.read())
    finally:
        connection.close()


def test_unix_api_health_no_mutations_no_raw_payload(tmp_path: Path) -> None:
    database = tmp_path / "meshcore.db"
    MeshcoreObservationRepository(database)
    sock = tmp_path / "collector.sock"
    server = _LocalHttpServer(str(sock), database, _FakeCollector())
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        status, health = _request(sock, "GET", "/v1/health")
        assert status == 200
        assert health["schema"] == "meshcore/v1"
        assert health["device_connected"] is True
        status, nodes = _request(sock, "GET", "/v1/nodes")
        assert status == 200 and nodes["items"] == []
        status, signals = _request(sock, "GET", "/v1/signals")
        assert status == 200 and signals["items"] == []
        status, activity = _request(sock, "GET", "/v1/activity")
        assert status == 200
        assert activity["schema"] == "meshcore/activity/v1"
        assert activity["period"] == "rolling_24h_utc"
        assert activity["observed_nodes"] == 0
        assert activity["receiver_reception_cells"] == []
        status, rejected = _request(sock, "GET", "/v1/activity?hours=100000")
        assert status == 404
        status, rejected = _request(sock, "POST", "/v1/activity")
        assert status == 405 and rejected["error"] == "read_only"
        status, rejected = _request(sock, "POST", "/v1/nodes")
        assert status == 405 and rejected["error"] == "read_only"
        status, rejected = _request(sock, "GET", "/v1/private")
        assert status == 404
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_no_contact_storage_or_network_in_api(tmp_path: Path) -> None:
    database = tmp_path / "meshcore.db"
    MeshcoreObservationRepository(database)
    with sqlite3.connect(database) as connection:
        tables = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
    assert "contacts" not in tables
