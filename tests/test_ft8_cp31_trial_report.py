"""Fixture-level regression for read-only CP3.1 archived trial reporting."""
from __future__ import annotations

import runpy
import sqlite3
from pathlib import Path


def test_cp31_report_keeps_partial_exchange_distinct_from_failure(tmp_path: Path) -> None:
    database = tmp_path / "history.db"
    with sqlite3.connect(database) as db:
        db.execute(
            "CREATE TABLE ft8_performance_attempts ("
            "attempt_id TEXT, callsign TEXT, band TEXT, outcome TEXT, success INTEGER,"
            "received_report_db INTEGER, distance_km REAL, last_qso_state TEXT,"
            "terminal_reason TEXT, attempt_count INTEGER, started_at_utc TEXT)"
        )
        db.execute(
            "CREATE TABLE forge_ft8_transmit_period ("
            "qso_id TEXT, emission_index INTEGER, configured_power_watts INTEGER,"
            "power_readback_verified INTEGER, started_at_utc TEXT)"
        )
        db.execute(
            "INSERT INTO ft8_performance_attempts VALUES "
            "('a','WW3QB','20m','retry_exhausted',0,-17,700,"
            "'retry_exhausted','budget',12,'2026-10-11T01:00:00Z')"
        )
        db.executemany(
            "INSERT INTO forge_ft8_transmit_period VALUES (?,?,?,?,?)",
            [("a", 1, 20, 1, "2026-10-11T01:00:30Z"),
             ("a", 2, 25, 1, "2026-10-11T01:01:00Z")],
        )

    namespace = runpy.run_path("scripts/ft8_cp31_trial_report.py")
    report = namespace["report"](database)
    assert report["attempts"] == 1
    assert report["periods"] == 2
    assert report["by_outcome"] == {"retry_exhausted": 1}
    detail = report["attempt_details"][0]
    assert detail["received_report_db"] == -17
    assert detail["cat_power_watts"] == [20, 25]
    assert detail["emission_count"] == 2

    with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as db:
        assert db.execute("SELECT count(*) FROM forge_ft8_transmit_period").fetchone() == (2,)
