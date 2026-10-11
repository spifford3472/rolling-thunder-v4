"""C4 regional as-of joins: wholly synthetic, no provider or production DB."""
import hashlib
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from rolling_thunder.forge_ft8_c4_asof import audit_c4_choice_pairs
from rolling_thunder.forge_voacap_baseline import BaselinePlan, TargetGrid
from rolling_thunder.ft8.attempt_ledger import (
    FT8AttemptClassification,
    FT8AttemptEvent,
    FT8AttemptTxPeriod,
)
from rolling_thunder.ft8.performance import FT8AttemptOutcome

START = datetime(2026, 10, 11, 12, tzinfo=UTC)


def _fixture(tmp_path: Path, *, forecast_after_choice: bool = False) -> tuple[Path, Path, Path]:
    inbox, history, c4 = (tmp_path / s for s in ("inbox.db", "history.db", "c4.db"))
    choice = START + timedelta(minutes=30)
    event = FT8AttemptEvent(
        schema_version=2, choice_at_utc=choice, attempt_uuid=uuid4(),
        source_event_created_utc=choice + timedelta(minutes=4),
        started_at_utc=choice + timedelta(seconds=1),
        ended_at_utc=choice + timedelta(minutes=2),
        classification=FT8AttemptClassification.SUCCESS,
        source_outcome=FT8AttemptOutcome.COMPLETED,
        terminal_phase="completed", remote_callsign="TEST1",
        band="20m", local_grid="EM79xm", remote_grid="FN31", remote_grid_source="decoded_ft8",
        tx_periods=(FT8AttemptTxPeriod(sequence=1, started_at_utc=choice + timedelta(seconds=15),
                                      ended_at_utc=choice + timedelta(seconds=30),
                                      frequency_hz=14074000, transmitted=True),),
        transmit_attempt_count=1, busy_extension_attempts=0,
    )
    with sqlite3.connect(inbox) as db:
        db.execute("CREATE TABLE ft8_attempt_inbox (attempt_uuid TEXT,payload_sha256 TEXT,payload_json TEXT)")
        db.execute("INSERT INTO ft8_attempt_inbox VALUES (?,?,?)",
                   (str(event.attempt_uuid),event.payload_sha256,event.model_dump_json()))
    with sqlite3.connect(history) as db:
        db.execute("CREATE TABLE ft8_attempt_provenance_v1 (attempt_uuid TEXT,provenance TEXT)")
        db.execute("INSERT INTO ft8_attempt_provenance_v1 VALUES (?,?)",
                   (str(event.attempt_uuid),"field_observed"))
    plan = BaselinePlan(
        plan_id=uuid4(), plan_version="test-v1", created_at_utc=START - timedelta(days=1),
        origin_grid="EM79xm", origin_uncertainty="grid6 center",
        target_inventory_version="test-regions-v1",
        targets=(TargetGrid(region_id="us-northeast",grid="FN31",
                            uncertainty="grid4 only"),),
        model_version="model-1", service_version="svc-1",
        ssn_source="synthetic", ssn_source_version="1",
    )
    request = '{"bands_m":[20],"hour_utc":12}'
    response = '{"analysis":{"best_band_by_hour":[{"band_m":20,"hour_utc":12}]}}'
    reqsha = hashlib.sha256(request.encode()).hexdigest()
    respsha = hashlib.sha256(response.encode()).hexdigest()
    generated = START - timedelta(minutes=5)
    if forecast_after_choice:
        generated = START + timedelta(minutes=35)
    with sqlite3.connect(c4) as db:
        db.execute("CREATE TABLE baseline_plan_v1 (plan_id TEXT,payload_json TEXT,canonical_sha256 TEXT)")
        db.execute("INSERT INTO baseline_plan_v1 VALUES (?,?,?)",
                   (str(plan.plan_id),plan.model_dump_json(),plan.canonical_sha256))
        db.execute("CREATE TABLE baseline_provider_response_v1 (request_sha256 TEXT,response_json TEXT,service_version TEXT,model_version TEXT,response_sha256 TEXT)")
        db.execute("INSERT INTO baseline_provider_response_v1 VALUES (?,?,?,?,?)",
                   (reqsha,response,"svc-1","model-1",respsha))
        db.execute("""CREATE TABLE baseline_slot_v1
        (plan_id TEXT,target_grid TEXT,band_m INTEGER,forecast_for_utc TEXT,
         generated_at_utc TEXT,canonical_request_sha256 TEXT,
         canonical_request_json TEXT,response_sha256 TEXT,ssn_observed_at_utc TEXT,
         ssn_captured_at_utc TEXT,status TEXT,timing_class TEXT)""")
        db.execute("INSERT INTO baseline_slot_v1 VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                   (str(plan.plan_id),"FN31",20,START.isoformat(),generated.isoformat(),
                    reqsha,request,respsha,(START-timedelta(hours=2)).isoformat(),
                    (START-timedelta(hours=1)).isoformat(),"ready","pre_choice"))
    return inbox, history, c4


def test_valid_regional_prechoice_joins_but_does_not_qualify_power(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    result = audit_c4_choice_pairs(*paths)
    assert result["available"]
    assert result["regional_asof_comparisons"] == 1
    assert result["distinct_provider_request_inputs"] == 1
    assert result["calibrated_for_power"] is False
    assert result["noninferiority_vs_20w_established"] is False


def test_forecast_generated_after_choice_is_not_prospective(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, forecast_after_choice=True)
    result = audit_c4_choice_pairs(*paths)
    assert result["regional_asof_comparisons"] == 0


def test_missing_sources_fail_closed(tmp_path: Path) -> None:
    result = audit_c4_choice_pairs(tmp_path/"i",tmp_path/"h",tmp_path/"c4")
    assert not result["available"]
    assert result["regional_asof_comparisons"] == 0
