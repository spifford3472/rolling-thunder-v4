"""Offline, deterministic and audited replay of one historical FT8 attempt.

The replay boundary deliberately has no network adapter.  It reads declared
SQLite snapshots through query-only connections, copies history to a new file,
and writes retrospective evidence only to that copy through an injected,
schema-validated deterministic fake provider.
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections import Counter
from collections.abc import Iterable
from contextlib import closing
from datetime import UTC, date, datetime
from enum import StrEnum
from json import dumps
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid5

from pydantic import Field, field_validator, model_validator

from rolling_thunder.domain import DomainModel
from rolling_thunder.forge_ft8_attempt_correlation import (
    DOCUMENTED_SYNTHETIC_ATTEMPTS,
    AttemptProvenance,
    VoacapAttemptHistoryRepository,
    VoacapDirection,
    VoacapModelInput,
    VoacapProviderResult,
    VoacapRelation,
    VoacapRunStatus,
    model_inputs_for_attempt,
)
from rolling_thunder.forge_ft8_attempt_coverage import (
    RetrospectiveCoverageReport,
    build_retrospective_coverage_report,
)
from rolling_thunder.ft8.attempt_ledger import (
    FT8AttemptEvent,
    FT8ReportDirection,
)

HISTORICAL_REPLAY_REPORT_SCHEMA_VERSION = 1
FAKE_PROVIDER_FIXTURE_SCHEMA_VERSION = 1
AA4NP_ATTEMPT_UUID = UUID("938620bb-b4ff-40b2-9493-081b56bb038c")
AA4NP_PAYLOAD_SHA256 = "9de70a6c8d131500cefa580465bfe1033a87f558e3c655fac511443320288cab"
_EXPECTED_HISTORY_TABLES = {
    "voacap_attempt_schema_metadata",
    "voacap_prediction_input_v1",
    "voacap_prediction_run_v1",
    "voacap_attempt_link_v1",
    "ft8_attempt_provenance_v1",
}
_EXPECTED_INBOX_TABLES = {"ft8_attempt_inbox", "ft8_attempt_inbox_metadata"}
_C3_RUN_NAMESPACE = UUID("66d1d64b-f6fb-5dfa-980d-3f4d930e9bea")


class FakeProviderDisposition(StrEnum):
    READY = "ready"
    NO_REQUESTED_CELL = "no_requested_cell"
    MALFORMED = "malformed"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"


class FakeProviderTimeout(RuntimeError):
    pass


class FakeProviderUnavailable(RuntimeError):
    pass


class FakeProviderMalformed(RuntimeError):
    pass


class FakeProviderUnsupported(RuntimeError):
    pass


class HistoricalReplaySpecification(DomainModel):
    """Exact audited event identity and independently reviewed field semantics."""

    attempt_uuid: UUID = AA4NP_ATTEMPT_UUID
    payload_sha256: str = Field(
        default=AA4NP_PAYLOAD_SHA256, pattern=r"^[0-9a-f]{64}$"
    )
    remote_callsign: str = "AA4NP"
    local_grid: str = "EM79xm"
    remote_grid: str = "EL98"
    dial_frequency_hz: int = 7_074_000
    transmit_audio_offset_hz: int = 1_906
    configured_period_powers_watts: tuple[int, ...] = (
        20,
        25,
        30,
        35,
        40,
        40,
        40,
        40,
        40,
        40,
        40,
        40,
    )
    remote_report_of_local_db: int = -15
    local_report_of_remote_db: int = 12


class FakeVoacapResponse(DomainModel):
    """One fake monthly/hourly provider result keyed without second precision."""

    year: int = Field(ge=1900, le=2200)
    month: int = Field(ge=1, le=12)
    hour_utc: int = Field(ge=0, le=23)
    band_m: int = Field(gt=0, le=200)
    mode: Literal["FT8"] = "FT8"
    power_watts: int = Field(gt=0, le=100)
    disposition: FakeProviderDisposition = FakeProviderDisposition.READY
    reliability_fraction: float | None = Field(default=None, ge=0, le=1)
    snr_db_hz: float | None = None
    muf_mhz: float | None = None
    rating: str | None = Field(default=None, min_length=1, max_length=80)

    @model_validator(mode="after")
    def validate_values(self) -> FakeVoacapResponse:
        values = (
            self.reliability_fraction,
            self.snr_db_hz,
            self.muf_mhz,
            self.rating,
        )
        if self.disposition is FakeProviderDisposition.READY and not any(
            value is not None for value in values
        ):
            raise ValueError("ready fake provider response requires a modeled value")
        if self.disposition is not FakeProviderDisposition.READY and any(
            value is not None for value in values
        ):
            raise ValueError("non-ready fake provider response cannot contain modeled values")
        return self

    @property
    def key(self) -> tuple[int, int, int, int, str, int]:
        return (
            self.year,
            self.month,
            self.hour_utc,
            self.band_m,
            self.mode,
            self.power_watts,
        )


class FakeVoacapFixture(DomainModel):
    schema_version: Literal[1] = 1
    provider_kind: Literal["deterministic_fake"] = "deterministic_fake"
    model_service_version: str = Field(min_length=1, max_length=120)
    responses: tuple[FakeVoacapResponse, ...] = Field(min_length=1, max_length=96)

    @model_validator(mode="after")
    def validate_unique_requests(self) -> FakeVoacapFixture:
        keys = tuple(response.key for response in self.responses)
        if len(set(keys)) != len(keys):
            raise ValueError("fake provider fixture contains duplicate request identity")
        return self

    @property
    def fixture_sha256(self) -> str:
        return hashlib.sha256(_canonical(self.model_dump(mode="json")).encode()).hexdigest()


class AuditedProvenance(DomainModel):
    classification: Literal["field_observed"]
    reason: str = Field(min_length=1)
    evidence_reference: str = Field(min_length=1)
    evidence_date: date


class HistoricalReplayInputResult(DomainModel):
    input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    direction: VoacapDirection
    period_sequence: int | None
    year: int
    month: int
    selected_hour_utc: int
    band_m: int | None
    mode: Literal["FT8"] = "FT8"
    power_watts: int | None
    status: VoacapRunStatus
    response_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    failure_reason: str | None = None
    training_eligible: Literal[False] = False


class HistoricalReplayReport(DomainModel):
    """Versioned report containing hashes and semantics, never raw/private payloads."""

    schema_version: Literal[1] = 1
    replay_contract: Literal["ft8-historical-retrospective-v1"] = (
        "ft8-historical-retrospective-v1"
    )
    release_identifier: str = Field(min_length=1, max_length=200)
    replayed_at_utc: datetime
    attempt_uuid: UUID
    immutable_payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_inbox_logical_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_history_logical_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    replay_history_logical_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fake_provider_fixture_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_service_version: str
    provenance: AuditedProvenance
    provider_call_limit: int = Field(ge=1)
    provider_calls: int = Field(ge=0)
    dedup_verification_provider_calls: int | None = Field(default=None, ge=0)
    dedup_verification: Literal["zero_extra_calls", "not_run_nonterminal"]
    source_lease_state_unchanged: Literal[True] = True
    source_databases_unchanged: Literal[True] = True
    appended_rows: dict[str, int]
    statuses: dict[str, int]
    inputs: tuple[HistoricalReplayInputResult, ...]
    semantic_notes: dict[str, str]
    c2_coverage: RetrospectiveCoverageReport

    @field_validator("replayed_at_utc")
    @classmethod
    def normalize_replay_time(cls, value: datetime) -> datetime:
        return _utc(value)


class DeterministicFakeVoacapProvider:
    """Strict local fixture adapter; there is intentionally no socket transport."""

    def __init__(self, fixture: FakeVoacapFixture, *, call_limit: int) -> None:
        if call_limit < 1:
            raise ValueError("fake provider call limit must be positive")
        self._fixture = fixture
        self._responses = {response.key: response for response in fixture.responses}
        self._call_limit = call_limit
        self.calls = 0

    def predict(self, model_input: VoacapModelInput) -> VoacapProviderResult:
        if model_input.model_service_version != self._fixture.model_service_version:
            raise ValueError("fake provider model version does not match immutable input")
        request = model_input.provider_request()
        if request is None:
            raise ValueError("fake provider received incomplete model input")
        if set(request) != {
            "tx_grid",
            "rx_grid",
            "year",
            "month",
            "bands_m",
            "power_watts",
            "mode",
            "timezone",
        }:
            raise ValueError("VOACAP request contract changed")
        if "hour" in request or "second" in request:
            raise ValueError("VOACAP request must not fabricate sub-month time inputs")
        bands = request["bands_m"]
        if not isinstance(bands, list) or len(bands) != 1 or request["timezone"] != "UTC":
            raise ValueError("VOACAP request band/timezone contract changed")
        key = (
            int(request["year"]),
            int(request["month"]),
            model_input.event_hour_utc.hour,
            int(bands[0]),
            str(request["mode"]),
            int(request["power_watts"]),
        )
        self.calls += 1
        if self.calls > self._call_limit:
            raise RuntimeError("fake provider call limit exceeded")
        response = self._responses.get(key)
        if response is None:
            raise FakeProviderUnsupported(
                "fake provider fixture has no year/month/hour/band/mode/watts entry"
            )
        if response.disposition is FakeProviderDisposition.TIMEOUT:
            raise FakeProviderTimeout("deterministic fake provider timeout")
        if response.disposition is FakeProviderDisposition.UNAVAILABLE:
            raise FakeProviderUnavailable("deterministic fake provider unavailable")
        if response.disposition is FakeProviderDisposition.MALFORMED:
            raise FakeProviderMalformed("deterministic fake provider malformed response")
        response_json: dict[str, Any] = {
            "fixture_schema_version": FAKE_PROVIDER_FIXTURE_SCHEMA_VERSION,
            "model_service_version": self._fixture.model_service_version,
            "analysis": {"best_band_by_hour": []},
        }
        if response.disposition is FakeProviderDisposition.READY:
            response_json["analysis"]["best_band_by_hour"].append(
                {
                    "hour_utc": response.hour_utc,
                    "band_m": response.band_m,
                    "reliability": response.reliability_fraction,
                    "snr_db": response.snr_db_hz,
                    "muf_mhz": response.muf_mhz,
                    "rating": response.rating,
                }
            )
        return VoacapProviderResult(
            service_version=self._fixture.model_service_version,
            response_json=response_json,
            reliability_fraction=response.reliability_fraction,
            snr_db_hz=response.snr_db_hz,
            muf_mhz=response.muf_mhz,
            rating=response.rating,
        )


def run_audited_historical_replay(
    source_inbox_database: Path,
    source_history_database: Path,
    replay_history_database: Path,
    fixture: FakeVoacapFixture,
    *,
    replayed_at_utc: datetime,
    release_identifier: str,
    specification: HistoricalReplaySpecification | None = None,
    provider_call_limit: int = 12,
) -> HistoricalReplayReport:
    """Replay one audited UUID into a new history copy and return its report."""
    spec = specification or HistoricalReplaySpecification()
    replayed_at = _utc(replayed_at_utc)
    source_inbox = source_inbox_database.resolve()
    source_history = source_history_database.resolve()
    replay_history = replay_history_database.resolve()
    if len({source_inbox, source_history, replay_history}) != 3:
        raise ValueError("source and replay SQLite paths must be distinct")
    if replay_history.exists():
        raise FileExistsError(f"replay history output already exists: {replay_history}")
    if not replay_history.parent.is_dir():
        raise FileNotFoundError(f"replay history parent does not exist: {replay_history.parent}")

    inbox_before = _logical_sha256(source_inbox, _EXPECTED_INBOX_TABLES)
    history_before = _logical_sha256(source_history, _EXPECTED_HISTORY_TABLES)
    event, source_state = _load_and_validate_event(source_inbox, spec)
    provenance = _load_and_validate_provenance(source_history, spec.attempt_uuid)
    before_counts = _history_counts(source_history)
    _copy_sqlite(source_history, replay_history)

    history = VoacapAttemptHistoryRepository(replay_history)
    copied_provenance = _load_and_validate_provenance(replay_history, spec.attempt_uuid)
    if copied_provenance != provenance:
        raise RuntimeError("audited provenance changed while copying history")
    provider = DeterministicFakeVoacapProvider(
        fixture, call_limit=provider_call_limit
    )
    inputs = tuple(
        item.model_copy(
            update={"model_service_version": fixture.model_service_version}
        )
        for item in model_inputs_for_attempt(event)
    )
    first_calls_before = provider.calls
    _replay_inputs(history, provider, inputs, replayed_at)
    first_pass_calls = provider.calls - first_calls_before
    terminal = all(history.has_terminal_run_for_input(item) for item in inputs)
    dedup_calls: int | None = None
    dedup_status: Literal["zero_extra_calls", "not_run_nonterminal"]
    if terminal:
        dedup_before = provider.calls
        _replay_inputs(history, provider, inputs, replayed_at)
        dedup_calls = provider.calls - dedup_before
        if dedup_calls != 0:
            raise RuntimeError("terminal replay made an extra fake provider call")
        dedup_status = "zero_extra_calls"
    else:
        dedup_status = "not_run_nonterminal"

    after_counts = _history_counts(replay_history)
    results = _input_results(history, inputs)
    if any(result.training_eligible for result in results):
        raise RuntimeError("retrospective replay became training eligible")
    copied_provenance_after = _load_and_validate_provenance(
        replay_history, spec.attempt_uuid
    )
    if copied_provenance_after != provenance:
        raise RuntimeError("audited provenance changed during replay")
    if _logical_sha256(source_inbox, _EXPECTED_INBOX_TABLES) != inbox_before:
        raise RuntimeError("source inbox changed during offline replay")
    if _logical_sha256(source_history, _EXPECTED_HISTORY_TABLES) != history_before:
        raise RuntimeError("source history changed during offline replay")
    if _load_inbox_state(source_inbox, spec.attempt_uuid) != source_state:
        raise RuntimeError("source inbox lease or processing state changed")

    replay_sha = _logical_sha256(replay_history, _EXPECTED_HISTORY_TABLES)
    coverage = build_retrospective_coverage_report(
        source_inbox,
        replay_history,
        window_start_utc=event.started_at_utc,
        window_end_utc=max(event.ended_at_utc, event.started_at_utc)
        .replace(microsecond=999999),
        generated_at_utc=replayed_at,
        release_identifier=release_identifier,
        inbox_snapshot_identifier=f"sqlite-logical-sha256:{inbox_before}",
        history_snapshot_identifier=f"sqlite-logical-sha256:{replay_sha}",
    )
    statuses = dict(sorted(Counter(result.status.value for result in results).items()))
    return HistoricalReplayReport(
        release_identifier=release_identifier,
        replayed_at_utc=replayed_at,
        attempt_uuid=spec.attempt_uuid,
        immutable_payload_sha256=spec.payload_sha256,
        source_inbox_logical_sha256=inbox_before,
        source_history_logical_sha256=history_before,
        replay_history_logical_sha256=replay_sha,
        fake_provider_fixture_sha256=fixture.fixture_sha256,
        model_service_version=fixture.model_service_version,
        provenance=provenance,
        provider_call_limit=provider_call_limit,
        provider_calls=first_pass_calls,
        dedup_verification_provider_calls=dedup_calls,
        dedup_verification=dedup_status,
        appended_rows={
            key: after_counts[key] - before_counts[key] for key in before_counts
        },
        statuses=statuses,
        inputs=results,
        semantic_notes={
            "availability": "retrospective only; never information available before station choice",
            "decoder_reports": "exchange-level FT8 decoder dB; not provider dB-Hz and not per-period",
            "power": "CAT-verified configured watts; not measured RF output or a causal threshold",
            "provider_time": "request selects year/month; stored result selects requested UTC hour and band",
            "missing": "missing and unsupported are explicit; neither is zero",
            "training": "retrospective evidence is never training eligible, including field observations",
        },
        c2_coverage=coverage,
    )


def load_fake_voacap_fixture(path: Path) -> FakeVoacapFixture:
    """Load a bounded local JSON fixture without resolving URLs or sockets."""
    if path.stat().st_size > 1_048_576:
        raise ValueError("fake provider fixture exceeds 1 MiB")
    return FakeVoacapFixture.model_validate_json(path.read_text(encoding="utf-8"))


def _replay_inputs(
    history: VoacapAttemptHistoryRepository,
    provider: DeterministicFakeVoacapProvider,
    inputs: tuple[VoacapModelInput, ...],
    at_utc: datetime,
) -> None:
    for model_input in inputs:
        if history.has_terminal_run_for_input(model_input):
            continue
        if model_input.provider_request() is None:
            history.record_run(
                model_input,
                requested_at_utc=at_utc,
                available_at_utc=at_utc,
                status=VoacapRunStatus.SKIPPED,
                relation=VoacapRelation.RETROSPECTIVE,
                failure_reason="required model input missing",
                prediction_uuid=_run_uuid(
                    model_input, VoacapRunStatus.SKIPPED, at_utc
                ),
            )
            continue
        try:
            result = provider.predict(model_input)
        except FakeProviderUnsupported as error:
            history.record_run(
                model_input,
                requested_at_utc=at_utc,
                available_at_utc=at_utc,
                status=VoacapRunStatus.SKIPPED,
                relation=VoacapRelation.RETROSPECTIVE,
                failure_reason=str(error),
                prediction_uuid=_run_uuid(
                    model_input, VoacapRunStatus.SKIPPED, at_utc
                ),
            )
        except (
            FakeProviderMalformed,
            FakeProviderTimeout,
            FakeProviderUnavailable,
        ) as error:
            history.record_run(
                model_input,
                requested_at_utc=at_utc,
                available_at_utc=at_utc,
                status=VoacapRunStatus.FAILED,
                relation=VoacapRelation.RETROSPECTIVE,
                failure_reason=str(error),
                prediction_uuid=_run_uuid(
                    model_input, VoacapRunStatus.FAILED, at_utc
                ),
            )
        else:
            status = (
                VoacapRunStatus.READY
                if any(
                    value is not None
                    for value in (
                        result.reliability_fraction,
                        result.snr_db_hz,
                        result.muf_mhz,
                        result.rating,
                    )
                )
                else VoacapRunStatus.UNAVAILABLE
            )
            history.record_run(
                model_input,
                requested_at_utc=at_utc,
                available_at_utc=at_utc,
                status=status,
                relation=VoacapRelation.RETROSPECTIVE,
                result=result,
                failure_reason=(
                    None
                    if status is VoacapRunStatus.READY
                    else "fake response has no requested UTC-hour/band modeled values"
                ),
                prediction_uuid=_run_uuid(model_input, status, at_utc),
            )


def _input_results(
    history: VoacapAttemptHistoryRepository,
    inputs: tuple[VoacapModelInput, ...],
) -> tuple[HistoricalReplayInputResult, ...]:
    diagnostics = history.diagnostics(inputs[0].attempt_uuid)
    by_hash: dict[str, list[dict[str, Any]]] = {}
    for row in diagnostics["correlations"]:
        by_hash.setdefault(str(row["input_hash"]), []).append(row)
    results: list[HistoricalReplayInputResult] = []
    for model_input in inputs:
        rows = by_hash.get(model_input.input_hash, [])
        if not rows:
            raise RuntimeError("replay did not persist an explicit input result")
        row = rows[-1]
        if bool(row["training_eligible"]):
            raise RuntimeError("retrospective replay link is training eligible")
        band_m = (
            None
            if model_input.band is None or not model_input.band.endswith("m")
            else int(model_input.band.removesuffix("m"))
        )
        results.append(
            HistoricalReplayInputResult(
                input_hash=model_input.input_hash,
                direction=model_input.direction,
                period_sequence=model_input.period_sequence,
                year=model_input.event_hour_utc.year,
                month=model_input.event_hour_utc.month,
                selected_hour_utc=model_input.event_hour_utc.hour,
                band_m=band_m,
                power_watts=model_input.tx_power_watts,
                status=VoacapRunStatus(row["status"]),
                response_sha256=row["response_sha256"],
                failure_reason=row["failure_reason"],
                training_eligible=False,
            )
        )
    return tuple(results)


def _load_and_validate_event(
    path: Path, spec: HistoricalReplaySpecification
) -> tuple[FT8AttemptEvent, tuple[object, ...]]:
    with closing(_read_only(path)) as db:
        _require_tables(db, _EXPECTED_INBOX_TABLES, "inbox")
        _check_database(db, "inbox")
        row = db.execute(
            """SELECT payload_sha256,payload_json,state,attempt_count,next_attempt_at_utc,
            lease_token,leased_until_utc,worker_id,completed_at_utc,last_error
            FROM ft8_attempt_inbox WHERE attempt_uuid=?""",
            (str(spec.attempt_uuid),),
        ).fetchone()
    if row is None:
        raise ValueError("audited attempt UUID is absent from the inbox snapshot")
    stored_sha = str(row[0])
    if stored_sha != spec.payload_sha256:
        raise ValueError("audited attempt immutable payload SHA-256 mismatch")
    event = FT8AttemptEvent.model_validate_json(row[1])
    if event.attempt_uuid != spec.attempt_uuid or event.payload_sha256 != stored_sha:
        raise ValueError("audited attempt UUID or canonical payload SHA-256 mismatch")
    _validate_event_semantics(event, spec)
    return event, tuple(row[2:])


def _validate_event_semantics(
    event: FT8AttemptEvent, spec: HistoricalReplaySpecification
) -> None:
    if event.remote_callsign.upper() != spec.remote_callsign:
        raise ValueError("audited attempt remote callsign mismatch")
    if event.local_grid != spec.local_grid or event.remote_grid != spec.remote_grid:
        raise ValueError("audited attempt grid or precision mismatch")
    if event.dial_frequency_hz != spec.dial_frequency_hz or event.band != "40m":
        raise ValueError("audited attempt dial frequency/band mismatch")
    periods = tuple(period for period in event.tx_periods if period.transmitted)
    powers = tuple(period.configured_power_watts for period in periods)
    if powers != spec.configured_period_powers_watts:
        raise ValueError("audited attempt configured period powers mismatch")
    if any(period.power_source != "cat_configured_readback" for period in periods):
        raise ValueError("audited attempt power is not verified configured CAT readback")
    if any(period.frequency_hz != spec.dial_frequency_hz for period in periods):
        raise ValueError("audited attempt period frequency is not the exact dial frequency")
    if any(
        period.transmit_audio_offset_hz != spec.transmit_audio_offset_hz
        for period in periods
    ):
        raise ValueError("audited attempt transmit audio offset mismatch")
    reports = {report.direction: report for report in event.reports}
    expected_reports = {
        FT8ReportDirection.REMOTE_REPORT_OF_LOCAL: spec.remote_report_of_local_db,
        FT8ReportDirection.LOCAL_REPORT_OF_REMOTE: spec.local_report_of_remote_db,
    }
    if set(reports) != set(expected_reports) or any(
        reports[direction].value_db != value
        or reports[direction].unit != "ft8_decoder_db"
        for direction, value in expected_reports.items()
    ):
        raise ValueError("audited attempt directional FT8 decoder reports mismatch")


def _load_and_validate_provenance(path: Path, attempt_uuid: UUID) -> AuditedProvenance:
    with closing(_read_only(path)) as db:
        _require_tables(db, _EXPECTED_HISTORY_TABLES, "history")
        _check_database(db, "history")
        _check_documented_exclusions(db)
        row = db.execute(
            """SELECT provenance,reason,evidence_reference,evidence_date
            FROM ft8_attempt_provenance_v1 WHERE attempt_uuid=?""",
            (str(attempt_uuid),),
        ).fetchone()
    if row is None:
        raise ValueError("audited field_observed provenance entry is missing")
    if row[0] != AttemptProvenance.FIELD_OBSERVED.value:
        raise ValueError("audited attempt provenance is not field_observed")
    return AuditedProvenance(
        classification="field_observed",
        reason=row[1],
        evidence_reference=row[2],
        evidence_date=row[3],
    )


def _check_documented_exclusions(db: sqlite3.Connection) -> None:
    for attempt_uuid, classification, reason, evidence, evidence_date in (
        DOCUMENTED_SYNTHETIC_ATTEMPTS
    ):
        row = db.execute(
            """SELECT provenance,reason,evidence_reference,evidence_date
            FROM ft8_attempt_provenance_v1 WHERE attempt_uuid=?""",
            (str(attempt_uuid),),
        ).fetchone()
        if row != (classification, reason, evidence, evidence_date):
            raise ValueError("documented synthetic/test exclusion changed or is missing")


def _history_counts(path: Path) -> dict[str, int]:
    tables = (
        "voacap_prediction_input_v1",
        "voacap_prediction_run_v1",
        "voacap_attempt_link_v1",
        "ft8_attempt_provenance_v1",
    )
    with closing(_read_only(path)) as db:
        return {
            table: int(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in tables
        }


def _load_inbox_state(path: Path, attempt_uuid: UUID) -> tuple[object, ...]:
    with closing(_read_only(path)) as db:
        row = db.execute(
            """SELECT state,attempt_count,next_attempt_at_utc,lease_token,
            leased_until_utc,worker_id,completed_at_utc,last_error
            FROM ft8_attempt_inbox WHERE attempt_uuid=?""",
            (str(attempt_uuid),),
        ).fetchone()
    if row is None:
        raise ValueError("audited attempt UUID disappeared from inbox snapshot")
    return tuple(row)


def _copy_sqlite(source: Path, destination: Path) -> None:
    with closing(_read_only(source)) as source_db, closing(
        sqlite3.connect(destination)
    ) as destination_db:
        source_db.backup(destination_db)


def _logical_sha256(path: Path, required_tables: set[str]) -> str:
    with closing(_read_only(path)) as db:
        _require_tables(db, required_tables, "SQLite")
        digest = hashlib.sha256()
        for line in db.iterdump():
            digest.update(line.encode())
            digest.update(b"\n")
    return digest.hexdigest()


def _read_only(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise FileNotFoundError(path)
    db = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    db.execute("PRAGMA query_only=ON")
    return db


def _require_tables(
    db: sqlite3.Connection, required: set[str], label: str
) -> None:
    tables = {
        str(row[0])
        for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    missing = required - tables
    if missing:
        raise ValueError(f"missing required {label} tables: {sorted(missing)}")


def _check_database(db: sqlite3.Connection, label: str) -> None:
    if db.execute("PRAGMA integrity_check").fetchone() != ("ok",):
        raise ValueError(f"{label} snapshot failed integrity validation")
    if db.execute("PRAGMA foreign_key_check").fetchall():
        raise ValueError(f"{label} snapshot failed foreign-key validation")


def _canonical(value: object) -> str:
    return dumps(value, sort_keys=True, separators=(",", ":"))


def _run_uuid(
    model_input: VoacapModelInput, status: VoacapRunStatus, at_utc: datetime
) -> UUID:
    identity = f"{model_input.input_hash}:{status.value}:{_utc(at_utc).isoformat()}"
    return uuid5(_C3_RUN_NAMESPACE, identity)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC)


def fixture_request_keys(
    event: FT8AttemptEvent,
) -> tuple[tuple[int, int, int, int, str, int], ...]:
    """Expose deterministic unique fake-fixture identities for offline tooling."""
    result: list[tuple[int, int, int, int, str, int]] = []
    for item in model_inputs_for_attempt(event):
        request = item.provider_request()
        if request is None:
            continue
        bands = request["bands_m"]
        result.append(
            (
                int(request["year"]),
                int(request["month"]),
                item.event_hour_utc.hour,
                int(bands[0]),
                str(request["mode"]),
                int(request["power_watts"]),
            )
        )
    return tuple(dict.fromkeys(result))


def statuses_for(results: Iterable[HistoricalReplayInputResult]) -> dict[str, int]:
    """Return stable status counts for report consumers."""
    return dict(sorted(Counter(item.status.value for item in results).items()))
