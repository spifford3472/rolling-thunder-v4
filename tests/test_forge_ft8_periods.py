from datetime import UTC, datetime
from uuid import uuid4

import pytest

from rolling_thunder.forge_ft8_periods import ForgeFT8PeriodConflict, ForgeFT8PeriodRepository
from rolling_thunder.ft8.hardware_transmit import FT8TransmitPeriodTelemetry


def test_exactly_once_and_conflicting_replay(tmp_path):
    repo = ForgeFT8PeriodRepository(tmp_path / "forge.sqlite")
    qso = uuid4()
    time = datetime(2026, 10, 10, 12, tzinfo=UTC)
    record = FT8TransmitPeriodTelemetry(qso, time, time, 20, True, 14074000, True)
    assert repo.persist(qso, 1, record)
    assert not ForgeFT8PeriodRepository(tmp_path / "forge.sqlite").persist(qso, 1, record)
    changed = FT8TransmitPeriodTelemetry(qso, time, time, 25, True, 14074000, True)
    with pytest.raises(ForgeFT8PeriodConflict):
        repo.persist(qso, 1, changed)
    assert repo.persist(qso, 2, record)


def test_forge_offset_persists_and_replay_detects_changed_offset(tmp_path):
    path = tmp_path / 'forge.sqlite'
    repo = ForgeFT8PeriodRepository(path)
    qso = uuid4()
    now = datetime(2026, 10, 10, 12, tzinfo=UTC)
    record = FT8TransmitPeriodTelemetry(qso, now, now, 20, True, 14074000, True, 1500)
    assert repo.persist(qso, 1, record)
    assert not ForgeFT8PeriodRepository(path).persist(qso, 1, record)
    with pytest.raises(ForgeFT8PeriodConflict):
        repo.persist(qso, 1, FT8TransmitPeriodTelemetry(qso, now, now, 20, True, 14074000, True, 1600))
