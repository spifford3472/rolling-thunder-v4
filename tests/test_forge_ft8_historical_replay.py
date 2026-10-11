"""Phase C3 offline audited replay and versioned report coverage."""

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from rolling_thunder.forge_ft8_attempt_correlation import (
    AttemptInboxRepository,
    VoacapAttemptHistoryRepository,
    model_inputs_for_attempt,
)
from rolling_thunder.forge_ft8_historical_replay import (
    AA4NP_ATTEMPT_UUID,
    AA4NP_PAYLOAD_SHA256,
    AuditedProvenance,
    FakeProviderDisposition,
    FakeVoacapFixture,
    FakeVoacapResponse,
    HistoricalReplaySpecification,
    fixture_request_keys,
    run_audited_historical_replay,
)
from rolling_thunder.forge_ft8_historical_replay_main import main
from rolling_thunder.ft8.attempt_ledger import (
    FT8AttemptClassification,
    FT8AttemptEvent,
    FT8AttemptReport,
    FT8AttemptTxPeriod,
    FT8ReportDirection,
)
from rolling_thunder.ft8.performance import FT8AttemptOutcome

REPLAYED_AT = datetime(2027, 1, 2, 12, tzinfo=UTC)
STARTED_AT = datetime(2026, 12, 31, 23, 59, 15, tzinfo=UTC)
POWERS = (20, 25, 30, 35) + (40,) * 8


def test_production_audit_identity_is_frozen() -> None:
    assert str(AA4NP_ATTEMPT_UUID) == "938620bb-b4ff-40b2-9493-081b56bb038c"
    assert AA4NP_PAYLOAD_SHA256 == (
        "9de70a6c8d131500cefa580465bfe1033a87f558e3c655fac511443320288cab"
    )
    assert HistoricalReplaySpecification().payload_sha256 == AA4NP_PAYLOAD_SHA256


def test_replay_is_bounded_deterministic_deduplicated_and_source_read_only(
    tmp_path: Path,
) -> None:
    inbox_path, history_path, event, spec = _databases(tmp_path)
    _set_processing_lease(inbox_path)
    inbox_before = _dump(inbox_path)
    history_before = _dump(history_path)
    fixture = _fixture(event, version="fake-model-2026.12")
    output = tmp_path / "replay-history.sqlite"

    report = run_audited_historical_replay(
        inbox_path,
        history_path,
        output,
        fixture,
        replayed_at_utc=REPLAYED_AT,
        release_identifier="c3-test-release",
        specification=spec,
    )

    assert report.attempt_uuid == AA4NP_ATTEMPT_UUID
    assert report.immutable_payload_sha256 == event.payload_sha256
    assert report.provenance == AuditedProvenance(
        classification="field_observed",
        reason="operator-audited production FT8 exchange",
        evidence_reference="protected acceptance record C3",
        evidence_date="2026-10-11",
    )
    assert report.provider_calls == 12
    assert report.provider_call_limit == 12
    assert report.dedup_verification == "zero_extra_calls"
    assert report.dedup_verification_provider_calls == 0
    assert report.statuses == {"ready": 12, "skipped": 1}
    assert report.appended_rows == {
        "voacap_prediction_input_v1": 13,
        "voacap_prediction_run_v1": 13,
        "voacap_attempt_link_v1": 13,
        "ft8_attempt_provenance_v1": 0,
    }
    assert len(report.inputs) == 13
    assert len({item.input_hash for item in report.inputs}) == 13
    assert all(not item.training_eligible for item in report.inputs)
    assert all(
        item.response_sha256 is not None
        for item in report.inputs
        if item.status.value == "ready"
    )
    reverse = report.inputs[-1]
    assert reverse.direction.value == "remote_to_local"
    assert reverse.power_watts is None
    assert reverse.status.value == "skipped"
    assert report.c2_coverage.denominators == {
        "events": 1,
        "transmitted_periods": 12,
        "modeled_inputs": 13,
    }
    assert report.c2_coverage.event_partitions["provenance"] == {
        "field_observed": 1
    }
    assert report.c2_coverage.run_partitions["training_eligible"] == {
        "ineligible": 13
    }
    assert report.source_lease_state_unchanged
    assert report.source_databases_unchanged
    assert _dump(inbox_path) == inbox_before
    assert _dump(history_path) == history_before


def test_exact_frequency_hour_rollover_power_and_decoder_report_semantics(
    tmp_path: Path,
) -> None:
    _inbox, _history, event, _spec = _databases(tmp_path)

    inputs = model_inputs_for_attempt(event)

    assert len(inputs) == 13
    assert [item.tx_power_watts for item in inputs[:-1]] == list(POWERS)
    assert all(item.frequency_hz == 7_074_000 for item in inputs)
    assert all(item.band == "40m" for item in inputs)
    assert {item.tx_grid_precision for item in inputs[:-1]} == {6}
    assert {item.rx_grid_precision for item in inputs[:-1]} == {4}
    assert inputs[0].event_hour_utc == datetime(2026, 12, 31, 23, tzinfo=UTC)
    assert inputs[-2].event_hour_utc == datetime(2027, 1, 1, 0, tzinfo=UTC)
    requests = [item.provider_request() for item in inputs[:-1]]
    assert all(request is not None for request in requests)
    assert all("hour" not in request and "second" not in request for request in requests)  # type: ignore[union-attr]
    assert {request["bands_m"][0] for request in requests if request is not None} == {40}
    reports = {report.direction: report for report in event.reports}
    assert reports[FT8ReportDirection.REMOTE_REPORT_OF_LOCAL].value_db == -15
    assert reports[FT8ReportDirection.LOCAL_REPORT_OF_REMOTE].value_db == 12
    assert {report.unit for report in event.reports} == {"ft8_decoder_db"}
    assert all(period.frequency_hz == 7_074_000 for period in event.tx_periods)
    assert all(period.transmit_audio_offset_hz == 1_906 for period in event.tx_periods)


def test_replay_rejects_payload_hash_mismatch_before_copy(tmp_path: Path) -> None:
    inbox, history, _event, spec = _databases(tmp_path)
    wrong = spec.model_copy(update={"payload_sha256": "0" * 64})
    output = tmp_path / "must-not-exist.sqlite"

    with pytest.raises(ValueError, match="immutable payload SHA-256 mismatch"):
        run_audited_historical_replay(
            inbox,
            history,
            output,
            _fixture(_event, version="fake-v1"),
            replayed_at_utc=REPLAYED_AT,
            release_identifier="test",
            specification=wrong,
        )

    assert not output.exists()


@pytest.mark.parametrize("classification", [None, "synthetic_test"])
def test_replay_requires_existing_field_observed_provenance(
    tmp_path: Path, classification: str | None
) -> None:
    inbox, history, event, spec = _databases(tmp_path)
    with sqlite3.connect(history) as db:
        db.execute(
            "DELETE FROM ft8_attempt_provenance_v1 WHERE attempt_uuid=?",
            (str(AA4NP_ATTEMPT_UUID),),
        )
        if classification is not None:
            db.execute(
                """INSERT INTO ft8_attempt_provenance_v1
                (attempt_uuid,provenance,reason,evidence_reference,evidence_date)
                VALUES (?,?,?,?,?)""",
                (
                    str(AA4NP_ATTEMPT_UUID),
                    classification,
                    "not field evidence",
                    "test fixture",
                    "2026-10-11",
                ),
            )

    with pytest.raises(ValueError, match="provenance"):
        run_audited_historical_replay(
            inbox,
            history,
            tmp_path / "replay.sqlite",
            _fixture(event, version="fake-v1"),
            replayed_at_utc=REPLAYED_AT,
            release_identifier="test",
            specification=spec,
        )


def test_changed_synthetic_exclusion_fails_closed(tmp_path: Path) -> None:
    inbox, history, event, spec = _databases(tmp_path)
    with sqlite3.connect(history) as db:
        db.execute(
            """UPDATE ft8_attempt_provenance_v1 SET reason='changed'
            WHERE attempt_uuid='9ad2f0c2-ed0e-4ba7-8b03-732d8aa8c339'"""
        )

    with pytest.raises(ValueError, match="synthetic/test exclusion changed"):
        run_audited_historical_replay(
            inbox,
            history,
            tmp_path / "replay.sqlite",
            _fixture(event, version="fake-v1"),
            replayed_at_utc=REPLAYED_AT,
            release_identifier="test",
            specification=spec,
        )


def test_version_fork_appends_without_mutating_prior_results(tmp_path: Path) -> None:
    inbox, history, event, spec = _databases(tmp_path)
    version_one = tmp_path / "version-one.sqlite"
    first = run_audited_historical_replay(
        inbox,
        history,
        version_one,
        _fixture(event, version="fake-v1"),
        replayed_at_utc=REPLAYED_AT,
        release_identifier="release-one",
        specification=spec,
    )
    first_rows = _model_rows(version_one, "fake-v1")
    version_two = tmp_path / "version-two.sqlite"

    second = run_audited_historical_replay(
        inbox,
        version_one,
        version_two,
        _fixture(event, version="fake-v2"),
        replayed_at_utc=REPLAYED_AT + timedelta(hours=1),
        release_identifier="release-two",
        specification=spec,
    )

    assert first.provider_calls == 12
    assert second.provider_calls == 12
    assert second.appended_rows["voacap_prediction_input_v1"] == 13
    assert _model_rows(version_two, "fake-v1") == first_rows
    assert len(_model_rows(version_two, "fake-v2")) == 13
    assert len({item.input_hash for item in first.inputs} & {item.input_hash for item in second.inputs}) == 0


def test_same_snapshot_fixture_and_audit_time_produce_identical_reports(
    tmp_path: Path,
) -> None:
    inbox, history, event, spec = _databases(tmp_path)
    fixture = _fixture(event, version="fake-deterministic")

    first = run_audited_historical_replay(
        inbox,
        history,
        tmp_path / "deterministic-one.sqlite",
        fixture,
        replayed_at_utc=REPLAYED_AT,
        release_identifier="same-release",
        specification=spec,
    )
    second = run_audited_historical_replay(
        inbox,
        history,
        tmp_path / "deterministic-two.sqlite",
        fixture,
        replayed_at_utc=REPLAYED_AT,
        release_identifier="same-release",
        specification=spec,
    )

    assert first == second
    assert first.replay_history_logical_sha256 == second.replay_history_logical_sha256


@pytest.mark.parametrize(
    ("disposition", "expected_status", "dedup"),
    [
        (FakeProviderDisposition.NO_REQUESTED_CELL, "unavailable", "zero_extra_calls"),
        (FakeProviderDisposition.MALFORMED, "failed", "not_run_nonterminal"),
        (FakeProviderDisposition.TIMEOUT, "failed", "not_run_nonterminal"),
        (FakeProviderDisposition.UNAVAILABLE, "failed", "not_run_nonterminal"),
    ],
)
def test_fake_provider_failures_are_explicit_and_bounded(
    tmp_path: Path,
    disposition: FakeProviderDisposition,
    expected_status: str,
    dedup: str,
) -> None:
    inbox, history, event, spec = _databases(tmp_path)
    fixture = _fixture(event, version=f"fake-{disposition.value}", disposition=disposition)

    report = run_audited_historical_replay(
        inbox,
        history,
        tmp_path / f"{disposition.value}.sqlite",
        fixture,
        replayed_at_utc=REPLAYED_AT,
        release_identifier="failure-fixture",
        specification=spec,
    )

    assert report.provider_calls == 12
    assert report.provider_calls <= report.provider_call_limit
    assert report.statuses[expected_status] == 12
    assert report.statuses["skipped"] == 1
    assert report.dedup_verification == dedup
    assert all(not item.training_eligible for item in report.inputs)


def test_missing_fake_request_is_explicitly_unsupported(tmp_path: Path) -> None:
    inbox, history, event, spec = _databases(tmp_path)
    complete = _fixture(event, version="fake-incomplete")
    incomplete = complete.model_copy(update={"responses": complete.responses[:-1]})

    report = run_audited_historical_replay(
        inbox,
        history,
        tmp_path / "incomplete.sqlite",
        incomplete,
        replayed_at_utc=REPLAYED_AT,
        release_identifier="incomplete-fixture",
        specification=spec,
    )

    unsupported = [
        item
        for item in report.inputs
        if item.failure_reason
        == "fake provider fixture has no year/month/hour/band/mode/watts entry"
    ]
    assert unsupported
    assert all(item.status.value == "skipped" for item in unsupported)
    assert report.provider_calls == 12
    assert report.dedup_verification_provider_calls == 0


def test_malformed_fake_fixture_is_rejected() -> None:
    with pytest.raises(ValidationError, match="modeled value"):
        FakeVoacapFixture.model_validate(
            {
                "model_service_version": "fake-v1",
                "responses": [
                    {
                        "year": 2026,
                        "month": 10,
                        "hour_utc": 1,
                        "band_m": 40,
                        "power_watts": 20,
                        "disposition": "ready",
                    }
                ],
            }
        )


def test_fake_only_cli_rejects_non_audited_fixture_before_outputs(tmp_path: Path) -> None:
    inbox, history, event, _spec = _databases(tmp_path)
    fixture_path = tmp_path / "fake-provider.json"
    fixture_path.write_text(
        _fixture(event, version="fake-cli").model_dump_json(), encoding="utf-8"
    )
    output = tmp_path / "cli-replay.sqlite"
    report = tmp_path / "cli-report.json"

    # The production SHA is intentionally different from this constructed event,
    # so the fixed-audit CLI must fail before creating either output.
    assert (
        main(
            [
                "--source-inbox",
                str(inbox),
                "--source-history",
                str(history),
                "--replay-history-output",
                str(output),
                "--report-output",
                str(report),
                "--fake-provider-fixture",
                str(fixture_path),
                "--release-identifier",
                "cli-test",
                "--replayed-at-utc",
                REPLAYED_AT.isoformat(),
                "--copied-fixture-acknowledgement",
                "copied-fixture-only",
            ]
        )
        == 3
    )
    assert not output.exists()
    assert not report.exists()


def _databases(
    tmp_path: Path,
) -> tuple[Path, Path, FT8AttemptEvent, HistoricalReplaySpecification]:
    event = _event()
    spec = HistoricalReplaySpecification(payload_sha256=event.payload_sha256)
    inbox_path = tmp_path / "copied-inbox.sqlite"
    history_path = tmp_path / "copied-history.sqlite"
    AttemptInboxRepository(inbox_path).enqueue(event, received_at_utc=REPLAYED_AT)
    VoacapAttemptHistoryRepository(history_path)
    with sqlite3.connect(history_path) as db:
        db.execute(
            """INSERT INTO ft8_attempt_provenance_v1
            (attempt_uuid,provenance,reason,evidence_reference,evidence_date)
            VALUES (?,'field_observed',?,?,?)""",
            (
                str(AA4NP_ATTEMPT_UUID),
                "operator-audited production FT8 exchange",
                "protected acceptance record C3",
                "2026-10-11",
            ),
        )
    return inbox_path, history_path, event, spec


def _event() -> FT8AttemptEvent:
    periods = tuple(
        FT8AttemptTxPeriod(
            sequence=index,
            started_at_utc=STARTED_AT + timedelta(seconds=15 * (index - 1)),
            ended_at_utc=STARTED_AT + timedelta(seconds=15 * (index - 1) + 12),
            configured_power_watts=power,
            power_source="cat_configured_readback",
            frequency_hz=7_074_000,
            transmitted=True,
            transmit_audio_offset_hz=1_906,
        )
        for index, power in enumerate(POWERS, start=1)
    )
    return FT8AttemptEvent(
        attempt_uuid=AA4NP_ATTEMPT_UUID,
        source_event_created_utc=STARTED_AT + timedelta(minutes=4),
        started_at_utc=STARTED_AT,
        ended_at_utc=periods[-1].ended_at_utc,
        classification=FT8AttemptClassification.SUCCESS,
        source_outcome=FT8AttemptOutcome.COMPLETED,
        terminal_phase="completed",
        terminal_reason="historical field exchange",
        remote_callsign="AA4NP",
        band="40m",
        dial_frequency_hz=7_074_000,
        local_grid="EM79xm",
        local_latitude=39.25,
        local_longitude=-84.55,
        remote_grid="EL98",
        remote_grid_source="decoded_ft8",
        reports=(
            FT8AttemptReport(
                direction=FT8ReportDirection.REMOTE_REPORT_OF_LOCAL,
                value_db=-15,
            ),
            FT8AttemptReport(
                direction=FT8ReportDirection.LOCAL_REPORT_OF_REMOTE,
                value_db=12,
            ),
        ),
        tx_periods=periods,
        initial_configured_power_watts=20,
        final_configured_power_watts=40,
        maximum_configured_power_watts=40,
        transmit_attempt_count=12,
        busy_extension_attempts=0,
    )


def _fixture(
    event: FT8AttemptEvent,
    *,
    version: str,
    disposition: FakeProviderDisposition = FakeProviderDisposition.READY,
) -> FakeVoacapFixture:
    return FakeVoacapFixture(
        model_service_version=version,
        responses=tuple(
            FakeVoacapResponse(
                year=year,
                month=month,
                hour_utc=hour,
                band_m=band,
                mode="FT8",
                power_watts=power,
                disposition=disposition,
                reliability_fraction=(
                    (power + hour) / 100
                    if disposition is FakeProviderDisposition.READY
                    else None
                ),
                snr_db_hz=(
                    float(power - 10)
                    if disposition is FakeProviderDisposition.READY
                    else None
                ),
            )
            for year, month, hour, band, _mode, power in fixture_request_keys(event)
        ),
    )


def _set_processing_lease(path: Path) -> None:
    with sqlite3.connect(path) as db:
        db.execute(
            """UPDATE ft8_attempt_inbox SET state='processing',attempt_count=2,
            lease_token=?,leased_until_utc=?,worker_id=? WHERE attempt_uuid=?""",
            (
                str(UUID("aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee")),
                "2027-01-02T13:00:00Z",
                "production-worker-copy",
                str(AA4NP_ATTEMPT_UUID),
            ),
        )


def _dump(path: Path) -> tuple[str, ...]:
    with sqlite3.connect(path) as db:
        return tuple(db.iterdump())


def _model_rows(path: Path, version: str) -> tuple[tuple[object, ...], ...]:
    with sqlite3.connect(path) as db:
        return tuple(
            db.execute(
                """SELECT i.input_hash,i.input_json,r.status,r.response_sha256
                FROM voacap_prediction_input_v1 i
                JOIN voacap_prediction_run_v1 r ON r.input_hash=i.input_hash
                WHERE r.service_version=? OR
                (r.service_version IS NULL AND i.input_json LIKE ?)
                ORDER BY i.input_hash,r.prediction_uuid""",
                (version, f'%"model_service_version":"{version}"%'),
            ).fetchall()
        )
