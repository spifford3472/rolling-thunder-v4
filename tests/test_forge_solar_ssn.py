from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from rolling_thunder.forge_solar_ssn import (
    NOAA_PREDICTED_SOLAR_CYCLE_URL,
    HamQslRawSunspotsAudit,
    NoaaSwpcPredictedSsnAdapter,
    SsnFeedResponse,
    SsnSnapshotRepository,
    SsnValueSemantics,
)

NOW = datetime(2026, 10, 12, 12, tzinfo=UTC)


class FakeTransport:
    def __init__(
        self,
        body: bytes,
        captured: datetime = NOW,
        *,
        status: int = 200,
        final_url: str = NOAA_PREDICTED_SOLAR_CYCLE_URL,
    ) -> None:
        self.response = SsnFeedResponse(
            body=body,
            captured_at_utc=captured,
            status_code=status,
            final_url=final_url,
            headers={"last-modified": "Mon, 12 Oct 2026 11:30:00 GMT", "etag": '"abc"'},
        )
        self.calls: list[tuple[str, float, int]] = []

    def fetch(self, source_url: str, *, timeout_s: float, max_bytes: int) -> SsnFeedResponse:
        self.calls.append((source_url, timeout_s, max_bytes))
        return self.response


def _record(month: str = "2026-10", **changes: object) -> dict[str, object]:
    record: dict[str, object] = {
        "time-tag": month,
        "predicted_ssn": 121.4,
        "high25_ssn": 130.0,
        "low25_ssn": 110.0,
        "high_ssn": 150.0,
        "low_ssn": 90.0,
        "high75_ssn": 140.0,
        "low75_ssn": 100.0,
        "predicted_f10.7": 160.0,
        "high25_f10.7": 170.0,
        "low25_f10.7": 150.0,
        "high_f10.7": 180.0,
        "low_f10.7": 140.0,
        "high75_f10.7": 175.0,
        "low75_f10.7": 145.0,
    }
    record.update(changes)
    return record


def _body(*records: dict[str, object]) -> bytes:
    values = records or (_record("2026-09", predicted_ssn=125.0), _record())
    return json.dumps(values, separators=(",", ":")).encode()


def _fetch(transport: FakeTransport, month: str = "2026-10"):
    return NoaaSwpcPredictedSsnAdapter(transport=transport).fetch(
        target_month=month,
        as_of_utc=NOW,
        max_capture_age=timedelta(hours=24),
    )


def test_live_capture_clock_defaults_to_response_capture_and_explicit_as_of_still_checks() -> None:
    capture = NOW + timedelta(seconds=5)
    transport = FakeTransport(_body(), captured=capture)
    snapshot = NoaaSwpcPredictedSsnAdapter(transport=transport).fetch(
        target_month="2026-10"
    )
    assert snapshot.captured_at_utc == capture
    with pytest.raises(ValueError, match="future knowledge"):
        NoaaSwpcPredictedSsnAdapter(transport=transport).fetch(
            target_month="2026-10", as_of_utc=NOW
        )


def test_noaa_wire_fixture_selects_predicted_month_and_retains_provenance() -> None:
    transport = FakeTransport(_body())
    snapshot = _fetch(transport)
    assert snapshot.value == 121.4
    assert snapshot.target_month == "2026-10"
    assert snapshot.value_semantics is SsnValueSemantics.MONTHLY_SMOOTHED_PREDICTED
    assert snapshot.source_released_at_utc is None
    assert snapshot.raw_payload == transport.response.body
    assert snapshot.raw_sha256 == hashlib.sha256(transport.response.body).hexdigest()
    assert snapshot.source_http_headers["etag"] == '"abc"'
    assert "no-historical-as-issued-claim" in snapshot.source_revision_policy
    assert transport.calls == [(NOAA_PREDICTED_SOLAR_CYCLE_URL, 10.0, 1_000_000)]


@pytest.mark.parametrize(
    "body",
    [
        b"not-json",
        json.dumps({"time-tag": "2026-10", "smoothed_ssn": 100}).encode(),
        _body(_record(extra="schema-drift")),
        _body(_record(predicted_ssn=True)),
        _body(_record("2026-10"), _record("2026-10")),
        _body(_record("2026-09")),
    ],
)
def test_malformed_observed_semantic_drift_and_month_mismatch_fail_closed(body: bytes) -> None:
    with pytest.raises((TypeError, ValueError, ValidationError)):
        _fetch(FakeTransport(body))


def test_http_redirect_status_future_and_stale_capture_fail_closed() -> None:
    with pytest.raises(ValueError, match="HTTP 500"):
        _fetch(FakeTransport(_body(), status=500))
    with pytest.raises(ValueError, match="redirected"):
        _fetch(FakeTransport(_body(), final_url="https://example.invalid/feed"))
    with pytest.raises(ValueError, match="future knowledge"):
        _fetch(FakeTransport(_body(), captured=NOW + timedelta(seconds=1)))
    with pytest.raises(ValueError, match="stale"):
        _fetch(FakeTransport(_body(), captured=NOW - timedelta(days=2)))
    with pytest.raises(ValueError, match="HTTPS"):
        NoaaSwpcPredictedSsnAdapter(
            transport=FakeTransport(_body()), source_url="http://services.swpc.noaa.gov/data"
        )


def test_snapshot_store_appends_revisions_and_retains_raw_bytes(tmp_path: Path) -> None:
    first = _fetch(FakeTransport(_body()))
    changed_body = _body(_record("2026-10", predicted_ssn=122.0))
    second = NoaaSwpcPredictedSsnAdapter(transport=FakeTransport(
        changed_body, captured=NOW + timedelta(minutes=1)
    )).fetch(
        target_month="2026-10",
        as_of_utc=NOW + timedelta(minutes=1),
        max_capture_age=timedelta(hours=24),
    )
    repository = SsnSnapshotRepository(tmp_path / "ssn.sqlite")
    assert repository.add(first) is True
    assert repository.add(first) is False
    assert repository.add(second) is True
    assert repository.status()["revision_count"] == 2
    with sqlite3.connect(repository.path) as db:
        rows = db.execute(
            "SELECT raw_payload FROM predicted_ssn_snapshot_v2 ORDER BY captured_at_utc"
        ).fetchall()
    assert rows == [(first.raw_payload,), (second.raw_payload,)]


def test_hamqsl_raw_sunspots_are_read_only_and_never_promoted(tmp_path: Path) -> None:
    history = tmp_path / "history.sqlite"
    with sqlite3.connect(history) as db:
        db.execute(
            """CREATE TABLE solar_observation(collected_at_utc TEXT PRIMARY KEY,
            source_url TEXT,source_updated TEXT,payload_json TEXT,raw_xml TEXT)"""
        )
        db.execute(
            "INSERT INTO solar_observation VALUES (?,?,?,?,?)",
            ("2026-10-12T11:00:00Z", "https://hamqsl.invalid", "12 Oct 2026",
             json.dumps({"sunspots": "90"}), "<solar/>")
        )
    before = history.read_bytes()
    audit = HamQslRawSunspotsAudit(history)
    assert audit.latest()["eligibility"] == (
        "ineligible_raw_observed_count_not_predicted_monthly_ssn"
    )
    with pytest.raises(ValueError, match="not NOAA predicted"):
        audit.as_smoothed_snapshot()
    assert history.read_bytes() == before
