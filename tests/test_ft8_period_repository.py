"""Restart-safe per-transmission telemetry."""
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from rolling_thunder.ft8.hardware_transmit import FT8TransmitPeriodTelemetry
from rolling_thunder.ft8.period_repository import FT8TransmitPeriodRepository


def test_periods_survive_reopen_with_distinct_order(tmp_path):
    path = tmp_path / 'pi.sqlite'
    repo = FT8TransmitPeriodRepository(path)
    qso = uuid4()
    now = datetime(2026, 10, 10, 12, tzinfo=UTC)
    for index in range(3):
        start = now + timedelta(seconds=15 * index)
        repo.append(FT8TransmitPeriodTelemetry(qso,start,start + timedelta(seconds=12),20,True,14074000,True))
    records = FT8TransmitPeriodRepository(path).for_qso(qso)
    assert len(records) == 3
    assert records[0].started_at_utc < records[1].started_at_utc
    assert all(record.configured_power_watts == 20 for record in records)


def test_unknown_power_never_converted_to_verified_value(tmp_path):
    repo = FT8TransmitPeriodRepository(tmp_path / 'pi.sqlite')
    qso = uuid4()
    now = datetime(2026, 10, 10, 12, tzinfo=UTC)
    repo.append(FT8TransmitPeriodTelemetry(qso,now,now,None,False,7074000,True))
    assert repo.for_qso(qso)[0].configured_power_watts is None
    with pytest.raises(ValueError,match='provenance'):
        repo.append(FT8TransmitPeriodTelemetry(qso,now,now,20,False,7074000,True))


def test_pre_key_intent_survives_restart_and_remains_uncertain(tmp_path):
    db = tmp_path / 'pi.sqlite'
    qso = uuid4()
    intent = uuid4()
    FT8TransmitPeriodRepository(db).begin_intent(intent, qso, 14074000, 20)
    reopened = FT8TransmitPeriodRepository(db)
    assert reopened.uncertain_intents() == (intent,)
    assert reopened.for_qso(qso) == ()
    reopened.finish_intent(intent)
    assert FT8TransmitPeriodRepository(db).uncertain_intents() == ()


def test_complete_intent_atomically_persists_matching_emission(tmp_path):
    db = tmp_path / 'pi.sqlite'
    repo = FT8TransmitPeriodRepository(db)
    qso, intent = uuid4(), uuid4()
    now = datetime(2026, 10, 10, 12, tzinfo=UTC)
    record = FT8TransmitPeriodTelemetry(qso, now, now + timedelta(seconds=12), 20, True, 14074000, True)
    repo.begin_intent(intent, qso, 14074000, 20)
    with pytest.raises(ValueError, match='immutable intent'):
        repo.complete_intent(intent, FT8TransmitPeriodTelemetry(qso, now, now, 30, True, 14074000, True))
    assert FT8TransmitPeriodRepository(db).uncertain_intents() == (intent,)
    assert repo.for_qso(qso) == ()
    repo.complete_intent(intent, record)
    assert FT8TransmitPeriodRepository(db).uncertain_intents() == ()
    assert repo.for_qso(qso) == (record,)
    with pytest.raises(ValueError, match='already completed'):
        repo.complete_intent(intent, record)
    assert len(repo.for_qso(qso)) == 1
