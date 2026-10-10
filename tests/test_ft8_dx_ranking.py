from datetime import UTC, datetime, timedelta

import pytest

from rolling_thunder.ft8.dx_ranking import (
    CQCandidate,
    ReachabilityEvidence,
    rank_cqs,
    score_cq,
)

NOW = datetime(2026, 10, 10, 20, 0, tzinfo=UTC)


def cq(call="TEST", grid="FN20", snr=-5, evidence=None):
    return CQCandidate(call, grid, snr, evidence)


def test_dx_prefers_distant_with_equal_unknown_reachability():
    ranked = rank_cqs((cq("NEAR", "EM79"), cq("FAR", "JN58")), local_grid="EM79xm", now_utc=NOW)
    assert [item.callsign for item in ranked] == ["FAR", "NEAR"]


def test_strong_reachability_can_outweigh_distance():
    distant = cq("FAR", "JN58", -5, ReachabilityEvidence(0.0, NOW, 6))
    nearer = cq("NEAR", "FN20", -5, ReachabilityEvidence(1.0, NOW, 6))
    ranked = rank_cqs((distant, nearer), local_grid="EM79xm", now_utc=NOW)
    assert ranked[0].callsign == "NEAR"


def test_missing_data_is_low_confidence_not_zero_score():
    result = score_cq(cq(grid=None, snr=None), local_grid=None, now_utc=NOW)
    assert result.score > 0
    assert result.confidence == "low"
    assert result.distance_km is None


def test_stale_future_or_zero_receiver_evidence_cannot_change_score():
    base = score_cq(cq(), local_grid="EM79", now_utc=NOW).score
    for moment, count in ((NOW - timedelta(hours=1), 9), (NOW + timedelta(seconds=5), 9), (NOW, 0)):
        result = score_cq(cq(evidence=ReachabilityEvidence(1, moment, count)), local_grid="EM79", now_utc=NOW)
        assert result.score == base


def test_repeatable_and_stable_ties():
    items = (cq("B"), cq("A"))
    assert [x.callsign for x in rank_cqs(items, local_grid="EM79", now_utc=NOW)] == ["B", "A"]


def test_bad_evidence_rejected():
    with pytest.raises(ValueError):
        ReachabilityEvidence(1.5, NOW, 1)
    with pytest.raises(ValueError):
        ReachabilityEvidence(0.5, NOW, -1)
    with pytest.raises(ValueError):
        score_cq(cq(), local_grid="EM79", now_utc=NOW.replace(tzinfo=None))


def test_invalid_grid_does_not_crash():
    assert score_cq(cq(grid="INVALID"), local_grid="EM79", now_utc=NOW).distance_km is None
