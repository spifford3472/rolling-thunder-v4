from datetime import UTC, datetime
from json import loads

import pytest

from rolling_thunder.forge_psk_evidence_api import PrivatePskEvidenceApi
from rolling_thunder.forge_psk_evidence_snapshot import EvidenceSnapshot

TOKEN = "long-secret-value-with-more-than-32-characters"
PATH = "/api/v1/ft8/outbound-psk-evidence?sender=KI5VNB&target_grid=JN58&frequency_hz=14074000"
NOW = datetime(2026, 10, 10, 22, tzinfo=UTC)


class Reader:
    def __init__(self):
        self.calls = []

    def get(self, *, sender_callsign, target_grid, frequency_hz):
        self.calls.append((sender_callsign, target_grid, frequency_hz))
        return EvidenceSnapshot("no_recent_evidence", None, NOW, NOW)


def test_requires_independent_auth_and_read_only():
    reader = Reader()
    app = PrivatePskEvidenceApi(reader, bearer_token=TOKEN)
    assert app.handle("GET", PATH, authorization=None).status_code == 401
    assert app.handle("POST", PATH, authorization=f"Bearer {TOKEN}").status_code == 405
    assert app.handle("GET", "/other", authorization=f"Bearer {TOKEN}").status_code == 404
    assert reader.calls == []


def test_valid_read_is_versioned_and_has_no_secrets():
    reader = Reader()
    app = PrivatePskEvidenceApi(reader, bearer_token=TOKEN)
    result = app.handle("GET", PATH, authorization=f"Bearer {TOKEN}")
    assert result.status_code == 200
    body = loads(result.body)
    assert body["schema_version"] == 1
    assert body["status"] == "no_recent_evidence"
    assert TOKEN not in result.body.decode()
    assert reader.calls == [("KI5VNB", "JN58", 14074000)]


def test_bad_parameters_are_rejected():
    app = PrivatePskEvidenceApi(Reader(), bearer_token=TOKEN)
    assert app.handle("GET", PATH + "&sender=WRONG", authorization=f"Bearer {TOKEN}").status_code == 400
    assert app.handle("GET", PATH.replace("14074000", "0"), authorization=f"Bearer {TOKEN}").status_code == 400
    with pytest.raises(ValueError):
        PrivatePskEvidenceApi(Reader(), bearer_token="short")
