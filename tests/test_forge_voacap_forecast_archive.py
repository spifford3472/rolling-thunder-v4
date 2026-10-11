from datetime import UTC, datetime, timedelta

import pytest

from rolling_thunder.forge_voacap_forecast_archive import (
    ArchivedForecast,
    ForecastArchive,
    ForecastConflict,
)
from rolling_thunder.voacap_forecast_trends import ForecastPoint


def event(*, issued_offset_hours: int = -2, snr: float = -8.0) -> ArchivedForecast:
    valid = datetime(2026, 10, 11, 2, tzinfo=UTC)
    return ArchivedForecast(
        provider="local-test",
        point=ForecastPoint(
            issued_at_utc=valid + timedelta(hours=issued_offset_hours),
            valid_at_utc=valid, model_version="v1", path_identity="EM79-DM75",
            equipment_identity="mobile", band="40m",
            reliability=0.65, predicted_snr_db=snr,
        ),
        station_grid6="EM79xm", target_grid="DM75", target_uncertainty="4-char grid",
        model_inputs_hash="example-hash", collected_at_utc=valid - timedelta(hours=1),
    )


def test_archive_is_durable_and_idempotent(tmp_path) -> None:
    dbfile = tmp_path / "forecasts.db"
    repo = ForecastArchive(dbfile)
    assert repo.append(event())
    assert not ForecastArchive(dbfile).append(event())
    assert ForecastArchive(dbfile).count() == 1


def test_conflicting_replay_fails_closed(tmp_path) -> None:
    archive = ForecastArchive(tmp_path / "a.db")
    assert archive.append(event())
    with pytest.raises(ForecastConflict):
        archive.append(event(snr=-12))
    assert archive.count() == 1


def test_hindcast_is_recorded_not_disguised_as_forecast(tmp_path) -> None:
    import sqlite3

    db = tmp_path / "archive.db"
    archive = ForecastArchive(db)
    archive.append(event(issued_offset_hours=1))
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
        flags = conn.execute("SELECT is_forward_forecast FROM voacap_forecast_event").fetchall()
    assert flags == [(0,)]


def test_revision_at_new_issue_time_is_retained(tmp_path) -> None:
    archive = ForecastArchive(tmp_path / "history.db")
    archive.append(event())
    archive.append(event(issued_offset_hours=-3))
    assert archive.count() == 2
