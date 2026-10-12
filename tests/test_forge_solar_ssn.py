from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from rolling_thunder.forge_solar_ssn import (
    HamQslRawSunspotsAudit,
    SsnFeedResponse,
    SsnSnapshotRepository,
    SsnValueSemantics,
    VersionedSmoothedSsnJsonAdapter,
)

NOW = datetime(2026, 10, 12, 12, tzinfo=UTC)


class FakeTransport:
    def __init__(self, body: bytes, captured: datetime = NOW) -> None:
        self.body = body
        self.captured = captured
        self.calls: list[tuple[str, float, int]] = []

    def fetch(self, source_url: str, *, timeout_s: float, max_bytes: int) -> SsnFeedResponse:
        self.calls.append((source_url, timeout_s, max_bytes))
        return SsnFeedResponse(body=self.body, captured_at_utc=self.captured)


def _body(**changes: object) -> bytes:
    payload: dict[str, object] = {
        "contract": "smoothed-ssn-v1",
        "value": 121.4,
        "value_semantics": "monthly_smoothed_observed_sunspot_number",
        "source_record_id": "2026-03-final",
        "observed_at_utc": "2026-03-01T00:00:00Z",
        "released_at_utc": "2026-10-12T10:00:00Z",
    }
    payload.update(changes)
    return json.dumps(payload, sort_keys=True).encode()


def _adapter(transport: FakeTransport) -> VersionedSmoothedSsnJsonAdapter:
    return VersionedSmoothedSsnJsonAdapter(
        transport=transport,
        source_id="reviewed-authoritative-source",
        source_url="https://source.invalid/normalized-v1",
        source_version="dataset-release-2026-10-12",
    )


def test_bounded_normalized_feed_retains_semantics_and_provenance() -> None:
    transport = FakeTransport(_body())
    snapshot = _adapter(transport).fetch(
        as_of_utc=NOW,
        max_capture_age=timedelta(hours=24),
        max_observation_age=timedelta(days=400),
    )
    assert snapshot.value == 121.4
    assert snapshot.value_semantics is SsnValueSemantics.MONTHLY_SMOOTHED_OBSERVED
    assert snapshot.raw_sha256 == hashlib.sha256(transport.body).hexdigest()
    assert transport.calls == [("https://source.invalid/normalized-v1", 10.0, 1_000_000)]


@pytest.mark.parametrize(
    "body",
    [
        b"not-json",
        _body(contract="unknown"),
        _body(value_semantics="daily_raw_sunspot_count"),
        _body(extra="ambiguous"),
        _body(value=-1),
    ],
)
def test_malformed_ambiguous_and_raw_counts_fail_closed(body: bytes) -> None:
    with pytest.raises((ValueError, ValidationError)):
        _adapter(FakeTransport(body)).fetch(
            as_of_utc=NOW,
            max_capture_age=timedelta(hours=24),
            max_observation_age=timedelta(days=400),
        )


def test_future_and_stale_snapshots_fail_closed() -> None:
    with pytest.raises(ValueError, match="future knowledge"):
        _adapter(FakeTransport(
            _body(released_at_utc="2026-10-13T00:00:00Z"),
            datetime(2026, 10, 13, 1, tzinfo=UTC),
        )).fetch(
            as_of_utc=NOW,
            max_capture_age=timedelta(hours=24),
            max_observation_age=timedelta(days=400),
        )
    with pytest.raises(ValueError, match="stale"):
        _adapter(FakeTransport(
            _body(released_at_utc="2026-10-10T09:00:00Z"),
            NOW - timedelta(days=2),
        )).fetch(
            as_of_utc=NOW,
            max_capture_age=timedelta(hours=24),
            max_observation_age=timedelta(days=400),
        )
    with pytest.raises(ValueError, match="observation period is stale"):
        _adapter(FakeTransport(_body(
            observed_at_utc="2020-01-01T00:00:00Z",
            released_at_utc="2026-10-12T10:00:00Z",
        ))).fetch(
            as_of_utc=NOW,
            max_capture_age=timedelta(hours=24),
            max_observation_age=timedelta(days=400),
        )


def test_snapshot_store_is_immutable(tmp_path: Path) -> None:
    snapshot = _adapter(FakeTransport(_body())).fetch(
        as_of_utc=NOW,
        max_capture_age=timedelta(hours=24),
        max_observation_age=timedelta(days=400),
    )
    repository = SsnSnapshotRepository(tmp_path / "ssn.sqlite")
    assert repository.add(snapshot) is True
    assert repository.add(snapshot) is False
    changed = snapshot.model_copy(update={"value": 122.0})
    with pytest.raises(ValueError, match="changed immutable"):
        repository.add(changed)


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
    assert audit.latest() == {
        "collected_at_utc": "2026-10-12T11:00:00Z",
        "source_url": "https://hamqsl.invalid",
        "source_updated": "12 Oct 2026",
        "raw_sunspots": "90",
        "eligibility": "ineligible_raw_observed_count_not_monthly_smoothed_ssn",
    }
    with pytest.raises(ValueError, match="not monthly smoothed"):
        audit.as_smoothed_snapshot()
    assert history.read_bytes() == before
