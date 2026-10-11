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


def test_example_policy_is_valid_and_off() -> None:
    from rolling_thunder.forge_ft8_power_advisor_config import (
        PowerAdvisorMode,
        load_ft8_power_advisor_policy,
    )

    path = Path(__file__).resolve().parents[1] / "config" / "ft8-power-advisor.example.yaml"
    assert load_ft8_power_advisor_policy(path).mode is PowerAdvisorMode.OFF


def test_proposed_systemd_unit_remains_non_networked_and_non_actuating() -> None:
    unit = (
        Path(__file__).resolve().parents[1]
        / "deploy/systemd/rolling-thunder-forge-ft8-readiness.service"
    ).read_text()
    assert "DynamicUser=yes" in unit
    assert "IPAddressDeny=any" in unit
    assert "ProtectSystem=strict" in unit
    assert "RestrictAddressFamilies=AF_UNIX" in unit
    assert "rolling-thunder-forge-ft8-readiness" in unit
    assert "rolling-thunder-forge-deploy" not in unit
    assert "ExecStart=" in unit
    assert not any(unsafe in unit for unsafe in ("CAT", "PTT", "ft8-hardware", "voacap-service"))


def test_atomic_status_snapshot_and_transition_audit(tmp_path: Path, capsys: object) -> None:
    import json

    from rolling_thunder.forge_ft8_readiness_main import persist_status

    path = tmp_path / "private-state" / "status.json"
    sample = {
        "observed_at_utc": "2026-10-11T20:00:00Z",
        "readiness": "OFF",
        "reason_codes": ["configuration_off"],
        "policy_mode": "off",
        "shadow_only": True,
        "apply_allowed": False,
        "may_transmit": False,
    }
    assert persist_status(path, sample)
    assert json.loads(path.read_text()) == sample
    assert path.stat().st_mode & 0o777 == 0o600
    assert not persist_status(path, sample)
    changed = dict(sample, readiness="INSUFFICIENT_EVIDENCE/COLLECTING")
    assert persist_status(path, changed)
    assert json.loads(path.read_text())["readiness"] == changed["readiness"]


def test_systemd_requires_reviewed_three_source_paths() -> None:
    root = Path(__file__).resolve().parents[1]
    unit = (root / "deploy/systemd/rolling-thunder-forge-ft8-readiness.service").read_text()
    example = (root / "deploy/systemd/forge-ft8-readiness.paths.env.example").read_text()
    assert "EnvironmentFile=/etc/rolling-thunder-forge-ft8-readiness/paths.env" in unit
    for variable in ("C3_INBOX_DB_PATH", "C3_HISTORY_DB_PATH", "C4_DB_PATH"):
        assert "${" + variable + "}" in unit
        assert variable + "=/REVIEW_REQUIRED/" in example
    assert "IPAddressDeny=any" in unit
