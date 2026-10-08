"""Offline contract tests for respectful PSK Reporter analytics."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from typing import Any
from urllib.parse import parse_qs, urlparse
from uuid import UUID

import pytest

from rolling_thunder.domain import Contact, ContactSource, RadioMode
from rolling_thunder.forge_propagation_history import (
    ForgePropagationHistoryRepository,
    PskReporterCollectionStatus,
)
from rolling_thunder.forge_pskreporter import (
    PSK_REPORTER_CORRELATION_POLICY,
    PSK_REPORTER_QUERY_URL,
    PskReporterAnalyticsService,
    PskReporterConfig,
    PskReporterHttpClient,
    PskReporterQueryStatus,
    parse_pskreporter_xml,
)
from rolling_thunder.http_home_platform import UrllibHttpResponse

NOW = datetime(2026, 10, 7, 2, 0, tzinfo=UTC)


class Transport:
    def __init__(self, responses: list[UrllibHttpResponse | BaseException]) -> None:
        self.responses = responses
        self.requests: list[tuple[str, str, float]] = []

    def request(self, method, url, *, headers, body, timeout_s):  # type: ignore[no-untyped-def]
        del headers, body
        self.requests.append((method, url, timeout_s))
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


class CompletionTimes:
    def __init__(self, values: dict[UUID, Any]) -> None:
        self.values = values
        self.calls: list[UUID] = []

    def ended_at_utc(self, contact_id: UUID) -> datetime | None:
        self.calls.append(contact_id)
        return self.values.get(contact_id)  # type: ignore[no-any-return]


def test_http_query_uses_official_encoded_bounded_parameters() -> None:
    transport = Transport([UrllibHttpResponse(200, b"<receptionReports/>")])
    config = PskReporterConfig(enabled=True, sender_callsign="ki5vnb", report_limit=123)
    result = PskReporterHttpClient(config, transport=transport).query(
        now=NOW,
        window_s=900,
        frequency_range_hz=(14_064_000, 14_084_000),
    )

    assert result.status is PskReporterQueryStatus.SUCCEEDED
    method, url, timeout = transport.requests[0]
    assert method == "GET"
    assert url.startswith(f"{PSK_REPORTER_QUERY_URL}?")
    parameters = parse_qs(urlparse(url).query)
    assert parameters == {
        "senderCallsign": ["KI5VNB"],
        "mode": ["FT8"],
        "flowStartSeconds": ["-900"],
        "rronly": ["1"],
        "noactive": ["1"],
        "nolocator": ["1"],
        "rptlimit": ["123"],
        "frange": ["14064000-14084000"],
    }
    assert timeout == config.timeout_s


def test_client_rate_limits_successes_and_failures_for_five_minutes() -> None:
    transport = Transport(
        [
            OSError("offline"),
            UrllibHttpResponse(200, b"<receptionReports/>"),
        ]
    )
    client = PskReporterHttpClient(PskReporterConfig(enabled=True), transport=transport)

    first = client.query(now=NOW, window_s=300, frequency_range_hz=None)
    early = client.query(now=NOW + timedelta(seconds=299), window_s=300, frequency_range_hz=None)
    due = client.query(now=NOW + timedelta(seconds=300), window_s=300, frequency_range_hz=None)

    assert first.status is PskReporterQueryStatus.QUERY_FAILED
    assert early.status is PskReporterQueryStatus.NOT_DUE
    assert due.status is PskReporterQueryStatus.SUCCEEDED
    assert len(transport.requests) == 2


def test_client_allows_only_one_concurrent_network_attempt_per_interval() -> None:
    caller_count = 16
    start = Barrier(caller_count)
    transport = Transport(
        [UrllibHttpResponse(200, b"<receptionReports/>")] * caller_count
    )
    client = PskReporterHttpClient(PskReporterConfig(enabled=True), transport=transport)

    def query() -> PskReporterQueryStatus:
        start.wait()
        return client.query(
            now=NOW, window_s=300, frequency_range_hz=None
        ).status

    with ThreadPoolExecutor(max_workers=caller_count) as executor:
        statuses = list(executor.map(lambda _: query(), range(caller_count)))

    assert statuses.count(PskReporterQueryStatus.SUCCEEDED) == 1
    assert statuses.count(PskReporterQueryStatus.NOT_DUE) == caller_count - 1
    assert len(transport.requests) == 1


def test_xml_parser_retains_optional_fields_and_skips_bad_records() -> None:
    xml = _xml(
        _report(
            "W1GOOD",
            "FN31pr",
            NOW - timedelta(minutes=8),
            snr=-7,
            sequence=42,
        ),
        '<receptionReport receiverCallsign="BAD" frequency="nope"/>',
        _report("W2MIN", None, NOW - timedelta(minutes=7), mode=None),
    )

    reports, skipped = parse_pskreporter_xml(xml)

    assert skipped == 1
    assert len(reports) == 2
    assert reports[0].receiver_callsign == "W1GOOD"
    assert reports[0].receiver_locator == "FN31pr"
    assert reports[0].snr_db == -7
    assert reports[0].mode == "FT8"
    assert reports[0].sequence_number == 42
    assert reports[1].receiver_locator is None
    assert reports[1].snr_db is None


@pytest.mark.parametrize("body", [b"<broken", b"<wrongRoot/>"])
def test_malformed_provider_document_is_query_failure_not_zero(body: bytes) -> None:
    transport = Transport([UrllibHttpResponse(200, body)])
    result = PskReporterHttpClient(PskReporterConfig(enabled=True), transport=transport).query(
        now=NOW, window_s=300, frequency_range_hz=None
    )

    assert result.status is PskReporterQueryStatus.QUERY_FAILED
    assert result.reports == ()
    assert result.error


def test_provider_report_count_above_requested_limit_is_query_failure() -> None:
    body = _xml(
        _report("W1ONE", "FN31pr", NOW - timedelta(minutes=2)),
        _report("W2TWO", "EM79xp", NOW - timedelta(minutes=1)),
    )
    transport = Transport([UrllibHttpResponse(200, body.encode())])
    result = PskReporterHttpClient(
        PskReporterConfig(enabled=True, report_limit=1), transport=transport
    ).query(now=NOW, window_s=300, frequency_range_hz=None)

    assert result.status is PskReporterQueryStatus.QUERY_FAILED
    assert result.reports == ()
    assert result.error == "PSK Reporter response exceeded the requested report limit"


def test_conservative_fallback_batches_due_qsos_and_distinguishes_zero_from_failure(
    tmp_path: Path,
) -> None:
    repository = ForgePropagationHistoryRepository(tmp_path / "psk.sqlite3")
    transport = Transport([UrllibHttpResponse(200, b"<receptionReports/>")])
    config = PskReporterConfig(enabled=True)
    service = PskReporterAnalyticsService(
        repository,
        config,
        client=PskReporterHttpClient(config, transport=transport),
    )
    not_due = _contact(1, NOW - timedelta(seconds=599))
    due_one = _contact(2, NOW - timedelta(seconds=600))
    due_two = _contact(3, NOW - timedelta(minutes=11), frequency_hz=7_074_000)

    outcomes = service.collect_recent([not_due, due_one, due_two], now=NOW)

    assert [outcome.status for outcome in outcomes] == [
        PskReporterCollectionStatus.NOT_DUE,
        PskReporterCollectionStatus.QUERIED_ZERO_REPORTS,
        PskReporterCollectionStatus.QUERIED_ZERO_REPORTS,
    ]
    assert len(transport.requests) == 1
    assert outcomes[1].summary_json is not None
    assert outcomes[1].summary_json["report_count"] == 0
    assert outcomes[1].summary_json["eligibility"] == {
        "reference_source": "conservative_start_fallback",
        "reference_at_utc": "2026-10-07T01:55:00Z",
        "eligible_at_utc": "2026-10-07T02:00:00Z",
    }
    assert outcomes[1].query_id is not None
    assert outcomes[1].query_id == outcomes[2].query_id
    with sqlite3.connect(tmp_path / "psk.sqlite3") as connection:
        assert connection.execute(
            "SELECT count(*), count(raw_xml) FROM pskreporter_query"
        ).fetchone() == (1, 1)
        per_qso_payloads = connection.execute(
            "SELECT raw_response_json FROM qso_pskreporter_summary "
            "WHERE query_id IS NOT NULL"
        ).fetchall()
    assert len(per_qso_payloads) == 2
    assert all("<receptionReports" not in row[0] for row in per_qso_payloads)
    assert repository.read_pskreporter(due_one.contact_id) == outcomes[1]

    # Successful terminal windows are restart-safe and do not retrieve again.
    repeated = service.collect_recent([due_one, due_two], now=NOW + timedelta(minutes=5))
    assert repeated == outcomes[1:]
    assert len(transport.requests) == 1


def test_completion_end_plus_300_is_exact_eligibility_boundary(tmp_path: Path) -> None:
    repository = ForgePropagationHistoryRepository(tmp_path / "end-boundary.sqlite3")
    transport = Transport([UrllibHttpResponse(200, b"<receptionReports/>")])
    contact = _contact(20, NOW - timedelta(minutes=20))
    completion = CompletionTimes({contact.contact_id: NOW - timedelta(seconds=300)})
    config = PskReporterConfig(enabled=True)
    service = PskReporterAnalyticsService(
        repository,
        config,
        client=PskReporterHttpClient(config, transport=transport),
        completion_time_provider=completion,
    )

    outcome = service.collect_recent([contact], now=NOW)[0]

    assert outcome.status is PskReporterCollectionStatus.QUERIED_ZERO_REPORTS
    assert len(transport.requests) == 1
    assert outcome.summary_json is not None
    assert outcome.summary_json["eligibility"] == {
        "reference_source": "ft8_terminal_end",
        "reference_at_utc": "2026-10-07T01:55:00Z",
        "eligible_at_utc": "2026-10-07T02:00:00Z",
    }


def test_completion_end_plus_300_is_not_due_one_second_early(tmp_path: Path) -> None:
    repository = ForgePropagationHistoryRepository(tmp_path / "end-not-due.sqlite3")
    transport = Transport([])
    contact = _contact(21, NOW - timedelta(minutes=20))
    completion = CompletionTimes({contact.contact_id: NOW - timedelta(seconds=299)})
    config = PskReporterConfig(enabled=True)
    service = PskReporterAnalyticsService(
        repository,
        config,
        client=PskReporterHttpClient(config, transport=transport),
        completion_time_provider=completion,
    )

    outcome = service.collect_recent([contact], now=NOW)[0]

    assert outcome.status is PskReporterCollectionStatus.NOT_DUE
    assert transport.requests == []
    assert outcome.summary_json is not None
    assert outcome.summary_json["eligibility"]["eligible_at_utc"] == (
        "2026-10-07T02:00:01Z"
    )


@pytest.mark.parametrize(
    "completion",
    [
        datetime(2026, 10, 7, 1, 50, tzinfo=UTC).replace(tzinfo=None),
        datetime(2026, 10, 7, 1, 30, tzinfo=UTC),
        "2026-10-07T01:55:00Z",
    ],
)
def test_malformed_completion_time_fails_closed_without_query(
    tmp_path: Path, completion: object
) -> None:
    repository = ForgePropagationHistoryRepository(tmp_path / "invalid-end.sqlite3")
    transport = Transport([])
    contact = _contact(22, NOW - timedelta(minutes=20))
    provider = CompletionTimes({contact.contact_id: completion})
    config = PskReporterConfig(enabled=True)
    service = PskReporterAnalyticsService(
        repository,
        config,
        client=PskReporterHttpClient(config, transport=transport),
        completion_time_provider=provider,
    )

    outcome = service.collect_recent([contact], now=NOW)[0]

    assert outcome.status is PskReporterCollectionStatus.NOT_DUE
    assert transport.requests == []
    assert outcome.summary_json is not None
    assert outcome.summary_json["reason"] == "invalid_ft8_completion_time"
    assert outcome.summary_json["eligibility"]["eligible_at_utc"] is None


def test_terminal_summary_is_restart_safe_before_completion_lookup(tmp_path: Path) -> None:
    database = tmp_path / "restart.sqlite3"
    contact = _contact(23, NOW - timedelta(minutes=20))
    config = PskReporterConfig(enabled=True)
    first_transport = Transport([UrllibHttpResponse(200, b"<receptionReports/>")])
    first_provider = CompletionTimes({contact.contact_id: NOW - timedelta(minutes=5)})
    first = PskReporterAnalyticsService(
        ForgePropagationHistoryRepository(database),
        config,
        client=PskReporterHttpClient(config, transport=first_transport),
        completion_time_provider=first_provider,
    ).collect_recent([contact], now=NOW)[0]
    restarted_transport = Transport([])
    restarted_provider = CompletionTimes(
        {
            contact.contact_id: datetime(2026, 10, 7, 1, 30, tzinfo=UTC).replace(
                tzinfo=None
            )
        }
    )

    repeated = PskReporterAnalyticsService(
        ForgePropagationHistoryRepository(database),
        config,
        client=PskReporterHttpClient(config, transport=restarted_transport),
        completion_time_provider=restarted_provider,
    ).collect_recent([contact], now=NOW + timedelta(minutes=10))[0]

    assert repeated == first
    assert restarted_provider.calls == []
    assert restarted_transport.requests == []


def test_provider_failure_is_persisted_as_failure_and_remains_retryable(
    tmp_path: Path,
) -> None:
    repository = ForgePropagationHistoryRepository(tmp_path / "failure.sqlite3")
    transport = Transport([OSError("provider unavailable")])
    config = PskReporterConfig(enabled=True)
    service = PskReporterAnalyticsService(
        repository,
        config,
        client=PskReporterHttpClient(config, transport=transport),
    )
    contact = _contact(4, NOW - timedelta(minutes=10))

    outcome = service.collect_recent([contact], now=NOW)[0]

    assert outcome.status is PskReporterCollectionStatus.QUERY_FAILED
    assert outcome.last_error == "provider unavailable"
    assert outcome.queried_at_utc == NOW
    assert outcome.summary_json is not None
    assert outcome.summary_json["query_parameters"]["senderCallsign"] == "KI5VNB"


def test_correlation_filters_unrelated_reports_and_summarizes_receivers(
    tmp_path: Path,
) -> None:
    contact = _contact(5, NOW - timedelta(minutes=10))
    qso_time = contact.started_at
    body = _xml(
        _report("NEAR", "EM79xp", qso_time + timedelta(seconds=15), snr=-2),
        _report("FAR", "JN18eu", qso_time + timedelta(seconds=30), snr=-12),
        _report("NOGRID", None, qso_time + timedelta(seconds=45), snr=4),
        _report("BADGRID", "NOT-A-GRID", qso_time + timedelta(seconds=50), snr=-5),
        _report("WRONGTIME", "FN31pr", qso_time + timedelta(minutes=20), snr=20),
        _report("WRONGBAND", "FN31pr", qso_time + timedelta(seconds=20), frequency=7_074_000),
        _report("WRONGMODE", "FN31pr", qso_time + timedelta(seconds=20), mode="JS8"),
        _report("WRONGSENDER", "FN31pr", qso_time + timedelta(seconds=20), sender="K1OTHER"),
    )
    repository = ForgePropagationHistoryRepository(tmp_path / "summary.sqlite3")
    transport = Transport([UrllibHttpResponse(200, body.encode())])
    config = PskReporterConfig(enabled=True)
    service = PskReporterAnalyticsService(
        repository,
        config,
        client=PskReporterHttpClient(config, transport=transport),
    )

    outcome = service.collect_recent([contact], now=NOW)[0]

    assert outcome.status is PskReporterCollectionStatus.QUERIED_WITH_REPORTS
    assert outcome.summary_json is not None
    summary = outcome.summary_json
    assert summary["correlation_policy"]["name"] == PSK_REPORTER_CORRELATION_POLICY
    assert summary["report_count"] == 4
    assert summary["strongest_report"]["receiver_callsign"] == "NOGRID"
    assert summary["furthest_report"]["receiver_callsign"] == "FAR"
    assert summary["continent_summaries"][0]["continent"] is None
    assert all(receiver["continent"] is None for receiver in summary["receivers"])
    bad_grid = next(
        receiver for receiver in summary["receivers"] if receiver["receiver_callsign"] == "BADGRID"
    )
    assert bad_grid["receiver_locator"] == "NOT-A-GRID"
    assert bad_grid["receiver_latitude"] is None
    assert bad_grid["distance_km"] is None
    assert outcome.raw_response_json is not None
    assert len(outcome.raw_response_json["matched_reports"]) == 4
    assert "raw_xml" not in outcome.raw_response_json
    assert outcome.query_id is not None
    archived = repository.read_pskreporter_query(outcome.query_id)
    assert archived is not None
    assert archived.raw_xml == body


def test_response_size_cap_failure_does_not_affect_other_propagation_state(
    tmp_path: Path,
) -> None:
    repository = ForgePropagationHistoryRepository(tmp_path / "isolated.sqlite3")
    transport = Transport([UrllibHttpResponse(200, b"<receptionReports/>" + b" " * 2000)])
    config = PskReporterConfig(enabled=True, maximum_response_bytes=1024)
    service = PskReporterAnalyticsService(
        repository,
        config,
        client=PskReporterHttpClient(config, transport=transport),
    )
    contact = _contact(6, NOW - timedelta(minutes=10))

    outcome = service.collect_recent([contact], now=NOW)[0]

    assert outcome.status is PskReporterCollectionStatus.QUERY_FAILED
    assert "maximum size" in (outcome.last_error or "")
    assert repository.get_qso(contact.contact_id) is None
    assert repository.latest_collection_time("solar_observation") is None


def _contact(index: int, started_at: datetime, *, frequency_hz: int = 14_074_000) -> Contact:
    return Contact(
        contact_id=UUID(f"00000000-0000-4000-8000-{index:012d}"),
        callsign=f"K{index}TEST",
        frequency_hz=frequency_hz,
        mode=RadioMode.FT8,
        started_at=started_at,
        rst_sent="-10",
        rst_received="-12",
        grid="FN31pr",
        my_grid="EM79xp",
        source=ContactSource.FT8,
    )


def _report(
    receiver: str,
    locator: str | None,
    occurred_at: datetime,
    *,
    snr: int | None = None,
    sequence: int | None = None,
    frequency: int = 14_074_000,
    mode: str | None = "FT8",
    sender: str = "KI5VNB",
) -> str:
    attributes = {
        "receiverCallsign": receiver,
        "senderCallsign": sender,
        "frequency": str(frequency),
        "flowStartSeconds": str(int(occurred_at.timestamp())),
    }
    if locator is not None:
        attributes["receiverLocator"] = locator
    if snr is not None:
        attributes["sNR"] = str(snr)
    if sequence is not None:
        attributes["sequenceNumber"] = str(sequence)
    if mode is not None:
        attributes["mode"] = mode
    serialized = " ".join(f'{name}="{value}"' for name, value in attributes.items())
    return f"<receptionReport {serialized}/>"


def _xml(*reports: str) -> str:
    return "<receptionReports>" + "".join(reports) + "</receptionReports>"
