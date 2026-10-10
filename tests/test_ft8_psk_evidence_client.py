from datetime import UTC, datetime
from json import dumps

from rolling_thunder.ft8.psk_evidence_client import HttpPskEvidenceClient

NOW = datetime(2026, 10, 10, 23, tzinfo=UTC)
TOKEN = "a-private-token-longer-than-thirty-two-characters"


class FakeTransport:
    def __init__(self, value):
        self.value = value
        self.url = None

    def get(self, url, *, token, timeout_s):
        self.url = url
        assert token == TOKEN
        assert timeout_s == 1.0
        if isinstance(self.value, Exception):
            raise self.value
        return dumps(self.value).encode()


def _result():
    return {
        "schema_version": 1, "status": "observed",
        "evidence": {
            "sender_callsign": "KI5VNB", "target_grid": "JN58",
            "frequency_hz": 14074000, "directional": True,
            "usable_for_calibrated_probability": False,
            "nearby_receivers": 2,
            "median_snr_db": -12,
            "latest_reception_utc": "2026-10-10T22:56:00+00:00",
        },
    }


def test_valid_observed_reception():
    transport = FakeTransport(_result())
    client = HttpPskEvidenceClient("http://forge:8789", bearer_token=TOKEN, transport=transport)
    result = client.lookup(sender_callsign="KI5VNB", target_grid="JN58", frequency_hz=14074000, now_utc=NOW)
    assert result is not None and result.receiver_count == 2
    assert "target_grid=JN58" in transport.url


def test_fail_closed_wrong_direction_age_schema_and_outage():
    values = [_result(), _result(), _result(), _result(), OSError("down")]
    values[0]["evidence"]["directional"] = False
    values[1]["evidence"]["sender_callsign"] = "DL1ABC"
    values[2]["evidence"]["latest_reception_utc"] = "2026-10-10T21:00:00+00:00"
    values[3]["schema_version"] = 99
    for value in values:
        client = HttpPskEvidenceClient("http://forge:8789", bearer_token=TOKEN, transport=FakeTransport(value))
        assert client.lookup(sender_callsign="KI5VNB", target_grid="JN58", frequency_hz=14074000, now_utc=NOW) is None
