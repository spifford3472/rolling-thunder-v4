"""Offline end-to-end contract test; binds only disposable local loopback."""
import sqlite3
from datetime import UTC, datetime, timedelta
from http.server import ThreadingHTTPServer
from threading import Thread

from rolling_thunder.forge_psk_evidence_api import PrivatePskEvidenceApi
from rolling_thunder.forge_psk_evidence_server import make_handler, validate_normalized_history
from rolling_thunder.forge_psk_evidence_snapshot import PskEvidenceSnapshotService
from rolling_thunder.ft8.psk_evidence_client import HttpPskEvidenceClient

TOKEN = "acceptance-only-private-token-more-than-32-characters"


def test_live_http_contract_on_disposable_local_db(tmp_path):
    db_path = tmp_path / "normalized.sqlite3"
    with sqlite3.connect(db_path) as db:
        db.execute("""CREATE TABLE psk_reception (
            sender_callsign TEXT, receiver_callsign TEXT,
            receiver_locator_normalized TEXT, frequency_hz INTEGER,
            flow_start_utc TEXT, snr_db INTEGER, mode TEXT)""")
        db.execute(
            "INSERT INTO psk_reception VALUES (?,?,?,?,?,?,?)",
            ("KI5VNB", "DL1TEST", "JN58", 14074000,
             (datetime.now(UTC) - timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
             -8, "FT8"),
        )
    validate_normalized_history(db_path)
    api = PrivatePskEvidenceApi(PskEvidenceSnapshotService(db_path), bearer_token=TOKEN)
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(api))
    server.daemon_threads = True
    runner = Thread(target=server.serve_forever, daemon=True)
    runner.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}"
        client = HttpPskEvidenceClient(url, bearer_token=TOKEN)
        observed = client.lookup(
            sender_callsign="KI5VNB", target_grid="JN58",
            frequency_hz=14074000, now_utc=datetime.now(UTC),
        )
        assert observed is not None
        assert observed.receiver_count == 1
        assert observed.median_snr_db == -8
        wrong_token = HttpPskEvidenceClient(url, bearer_token="X" * 40)
        assert wrong_token.lookup(
            sender_callsign="KI5VNB", target_grid="JN58",
            frequency_hz=14074000, now_utc=datetime.now(UTC),
        ) is None
        assert client.lookup(
            sender_callsign="KI5VNB", target_grid="PM95",
            frequency_hz=14074000, now_utc=datetime.now(UTC),
        ) is None
    finally:
        server.shutdown()
        server.server_close()
        runner.join(timeout=2)
