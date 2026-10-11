"""The C5.1 timer never upgrades raw inventory to scientific eligibility."""
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from rolling_thunder.forge_ft8_readiness_main import evaluate_once, inspect_c4


def test_missing_c4_and_off_config_fail_safe(tmp_path: Path) -> None:
    config = tmp_path / "policy.yaml"
    config.write_text("schema_version: 1\nmode: 'off'\npinned_model_version: x\n")
    result = evaluate_once(config, tmp_path / "missing.sqlite", now=datetime(2026, 10, 11, tzinfo=UTC))
    assert result["readiness"] == "OFF"
    assert result["shadow_only"] is True
    assert result["apply_allowed"] is False
    assert result["may_transmit"] is False
    assert result["suggested_start_watts"] is None
    assert result["current_operational_baseline_watts"] == 20


def test_armed_with_many_rows_still_not_eligible(tmp_path: Path) -> None:
    config = tmp_path / "policy.yaml"
    config.write_text("schema_version: 1\nmode: armed_when_ready\npinned_model_version: x\n")
    dbfile = tmp_path / "baseline.sqlite"
    with sqlite3.connect(dbfile) as db:
        db.execute("CREATE TABLE baseline_slot_v1(status TEXT, canonical_request_sha256 TEXT)")
        db.executemany("INSERT INTO baseline_slot_v1 VALUES (?,?)", [("generated", "same")] * 20001)
    before = dbfile.read_bytes()
    result = evaluate_once(config, dbfile)
    assert result["readiness"] == "INSUFFICIENT_EVIDENCE/COLLECTING"
    assert result["c4_inventory"]["stored_slots"] == 20001
    assert result["c4_inventory"]["independent_requests"] == 1
    assert result["suggested_start_watts"] is None
    assert dbfile.read_bytes() == before


def test_invalid_config_is_degraded_without_commands(tmp_path: Path) -> None:
    result = evaluate_once(tmp_path / "missing.yaml", tmp_path / "missing.sqlite")
    assert result["readiness"] == "DEGRADED/SUSPENDED"
    assert result["may_transmit"] is False
    assert inspect_c4(tmp_path / "missing.sqlite")["available"] is False
