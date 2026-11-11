"""Offline analysis store: immutable, bounded and separate from broker ACK."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from rolling_thunder.meshcore_geographic_relevance import Relevance
from rolling_thunder.meshcore_traffic_analysis_repository import (
    TrafficAssessmentError,
    TrafficAssessmentRepository,
)
from rolling_thunder.meshcore_traffic_georeferences import (
    ReferenceQuality,
    TrafficGeoreference,
)
from rolling_thunder.meshcore_traffic_relevance import (
    AssessmentConfidence,
    TrafficRelevanceDecision,
)

NOW = datetime(2026, 11, 11, tzinfo=UTC)
REF = TrafficGeoreference(
    ("I-75",),
    ("44",),
    (),
    ("N",),
    False,
    ReferenceQuality.SPECIFIC_UNVERIFIED,
    "source_unverified",
)


def _decision() -> TrafficRelevanceDecision:
    return TrafficRelevanceDecision(
        Relevance.POSSIBLY_AHEAD,
        AssessmentConfidence.LOW,
        "geometric_heading_only_route_not_confirmed",
        NOW,
        REF,
        distance_m=1200.0,
        verified_geocode_source="offline:node/12",
    )


def test_append_once_and_query_only_projection(tmp_path) -> None:
    path = tmp_path / "audit" / "analysis.db"
    store = TrafficAssessmentRepository(path, create=True)
    assert store.counts() == {}
    assert store.record(42, _decision(), evaluated_at=NOW)
    assert not store.record(42, _decision(), evaluated_at=NOW)
    copied = TrafficAssessmentRepository(path)
    entries = copied.recent()
    assert len(entries) == 1
    assert entries[0].message_id == 42
    assert entries[0].relevance == "possibly_ahead"
    assert copied.counts() == {"possibly_ahead": 1}
    tables = [
        row[0]
        for row in sqlite3.connect(path).execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    ]
    assert tables == ["assessment_schema", "assessments"]
    assert not any("broker" in table or "private" in table for table in tables)


def test_conflicting_replay_fails_without_replacing_prior(tmp_path) -> None:
    store = TrafficAssessmentRepository(tmp_path / "store.db", create=True)
    store.record(2, _decision(), evaluated_at=NOW)
    with pytest.raises(TrafficAssessmentError, match="Conflicting"):
        store.record(2, replace(_decision(), reason="different"), evaluated_at=NOW)
    assert store.recent()[0].reason == _decision().reason


def test_invalid_message_ids_bounds_and_metadata_rejected(tmp_path) -> None:
    store = TrafficAssessmentRepository(tmp_path / "store.db", create=True)
    for message_id in (0, -1, True):
        with pytest.raises(TrafficAssessmentError):
            store.record(message_id, _decision(), evaluated_at=NOW)
    with pytest.raises(TrafficAssessmentError):
        store.record(1, _decision(), evaluated_at=NOW.replace(tzinfo=None))
    for limit in (0, 101, True):
        with pytest.raises(TrafficAssessmentError):
            store.recent(limit=limit)


def test_missing_file_read_does_not_create_database(tmp_path) -> None:
    path = tmp_path / "missing.db"
    with pytest.raises(TrafficAssessmentError):
        TrafficAssessmentRepository(path)
    assert not path.exists()


def test_unsafe_file_permissions_are_rejected(tmp_path) -> None:
    path = tmp_path / "store.db"
    store = TrafficAssessmentRepository(path, create=True)
    path.chmod(0o644)
    with pytest.raises(TrafficAssessmentError):
        store.recent()


def test_all_queries_bounded_and_descending(tmp_path) -> None:
    store = TrafficAssessmentRepository(tmp_path / "store.db", create=True)
    for message_id in range(1, 8):
        assert store.record(message_id, _decision(), evaluated_at=NOW)
    assert [row.message_id for row in store.recent(limit=3)] == [7, 6, 5]


def test_rejects_private_text_or_secrets_in_audit_reason(tmp_path) -> None:
    store = TrafficAssessmentRepository(tmp_path / "store.db", create=True)
    with pytest.raises(TrafficAssessmentError, match="Unsafe"):
        store.record(
            1,
            replace(_decision(), reason="Private message: call me at home"),
            evaluated_at=NOW,
        )
    assert store.counts() == {}


def test_repeated_vehicle_assessments_append_without_rewriting(tmp_path) -> None:
    """An event may move from ahead to behind as the vehicle travels."""

    from datetime import timedelta

    store = TrafficAssessmentRepository(tmp_path / "store.db", create=True)
    assert store.record(77, _decision(), evaluated_at=NOW)
    later = replace(
        _decision(),
        relevance=Relevance.BEHIND,
        reason="reported_site_behind_vehicle_heading",
        distance_m=250,
    )
    assert store.record(77, later, evaluated_at=NOW + timedelta(minutes=2))
    rows = store.recent()
    assert len(rows) == 2
    assert rows[0].relevance == "behind"
    assert rows[1].relevance == "possibly_ahead"
    assert store.counts() == {"behind": 1, "possibly_ahead": 1}
