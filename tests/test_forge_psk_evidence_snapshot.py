from datetime import UTC, datetime, timedelta

import pytest

from rolling_thunder.forge_psk_evidence_snapshot import PskEvidenceSnapshotService
from rolling_thunder.forge_psk_path_evidence import PskOutboundPathEvidence

NOW = datetime(2026, 10, 10, 22, tzinfo=UTC)


def test_cache_freshness_and_safe_payload(tmp_path):
    current = [NOW]
    seen = []

    def reader(path, *, sender_callsign, target_grid, frequency_hz, now_utc):
        seen.append((sender_callsign, target_grid, frequency_hz, now_utc))
        return PskOutboundPathEvidence(
            sender_callsign, target_grid, frequency_hz, now_utc, 4, 2, -12,
        )

    service = PskEvidenceSnapshotService(
        tmp_path / "missing.db", clock=lambda: current[0], reader=reader,
    )
    first = service.get(sender_callsign="ki5vnb", target_grid="jn58", frequency_hz=14074000)
    assert first.status == "observed"
    assert first.public_data()["evidence"]["nearby_receivers"] == 2
    assert len(seen) == 1
    current[0] += timedelta(seconds=119)
    assert service.get(sender_callsign="KI5VNB", target_grid="JN58", frequency_hz=14074000) is first
    current[0] += timedelta(seconds=1)
    assert service.get(sender_callsign="KI5VNB", target_grid="JN58", frequency_hz=14074000) is not first
    assert len(seen) == 2


def test_missing_history_is_neutral_and_no_file_created(tmp_path):
    history = tmp_path / "absent.db"
    service = PskEvidenceSnapshotService(history, clock=lambda: NOW)
    result = service.get(sender_callsign="KI5VNB", target_grid="PM95", frequency_hz=14074000)
    assert result.status == "no_recent_evidence"
    assert not result.evidence.has_relevant_evidence
    assert not history.exists()
    with pytest.raises(ValueError):
        service.get(sender_callsign="", target_grid="PM95", frequency_hz=14074000)
