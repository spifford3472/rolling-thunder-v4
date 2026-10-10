"""Bounded, respectful PSK Reporter retrieval and FT8 QSO analytics."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from math import asin, ceil, cos, radians, sin, sqrt
from threading import Lock
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import UUID, uuid4
from xml.etree import ElementTree

from pydantic import Field, field_validator

from rolling_thunder.domain import Contact, ContactSource, DomainModel, Frequency, RadioMode
from rolling_thunder.forge_propagation_history import (
    ForgePropagationHistoryRepository,
    PskReporterCollectionStatus,
    PskReporterProviderQuery,
    PskReporterSummary,
)
from rolling_thunder.http_home_platform import (
    HttpTransport,
    UrllibHttpResponse,
)
from rolling_thunder.maidenhead import maidenhead_grid_center
from rolling_thunder.radio_band import RadioBandResolutionError, resolve_radio_band

PSK_REPORTER_QUERY_URL = "https://retrieve.pskreporter.info/query"
PSK_REPORTER_USER_AGENT = "RollingThunder/4.4 (+https://github.com/spifford3472/rolling-thunder-v4)"
PSK_REPORTER_CORRELATION_POLICY = "rolling_thunder_ft8_time_frequency_v1"
_MAX_PROVIDER_WINDOW_S = 86_400
_FREQUENCY_TOLERANCE_HZ = 10_000
_PRE_QSO_TOLERANCE_S = 60
_EARTH_RADIUS_KM = 6_371.0088


class PskReporterConfig(DomainModel):
    """Safe provider and correlation policy controls."""

    enabled: bool = False
    sender_callsign: str = Field(default="KI5VNB", min_length=3, max_length=32)
    appcontact: str | None = Field(default=None, max_length=254)
    mode: str = Field(default="FT8", pattern=r"^FT8$")
    minimum_query_interval_s: int = Field(default=600, ge=300)
    report_latency_s: int = Field(default=300, ge=300, le=3600)
    recent_window_s: int = Field(default=1800, ge=300, le=_MAX_PROVIDER_WINDOW_S)
    correlation_window_s: int = Field(default=300, ge=60, le=1800)
    report_limit: int = Field(default=5000, ge=1, le=25_000)
    timeout_s: float = Field(default=10.0, gt=0, le=60)
    maximum_response_bytes: int = Field(default=2_097_152, ge=1024, le=16_777_216)
    maximum_qsos_per_query: int = Field(default=50, ge=1, le=100)

    @field_validator("sender_callsign")
    @classmethod
    def normalize_sender_callsign(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("sender_callsign must not be blank")
        return normalized

    @property
    def minimum_query_interval(self) -> timedelta:
        return timedelta(seconds=self.minimum_query_interval_s)


class PskReporterReception(DomainModel):
    """Useful raw facts retained from one valid receptionReport element."""

    receiver_callsign: str = Field(min_length=1, max_length=64)
    receiver_locator: str | None = Field(default=None, max_length=32)
    sender_callsign: str = Field(min_length=1, max_length=64)
    frequency_hz: int = Field(gt=0, le=300_000_000_000)
    flow_start_utc: datetime
    snr_db: int | None = Field(default=None, ge=-100, le=100)
    mode: str | None = Field(default=None, max_length=32)
    sequence_number: int | None = Field(default=None, ge=0)

    @field_validator("flow_start_utc")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("flow_start_utc must be timezone-aware")
        return value.astimezone(UTC)


class PskReporterQueryStatus(StrEnum):
    NOT_DUE = "not_due"
    QUERY_FAILED = "query_failed"
    SUCCEEDED = "succeeded"


class PskReporterQueryResult(DomainModel):
    """One explicit provider query outcome; failure is never an empty result."""

    status: PskReporterQueryStatus
    query_id: UUID | None = None
    queried_at_utc: datetime | None = None
    query_parameters: dict[str, str | int]
    reports: tuple[PskReporterReception, ...] = ()
    raw_xml: str | None = None
    skipped_record_count: int = Field(default=0, ge=0)
    error: str | None = Field(default=None, max_length=1000)


class PskReporterCompletionTimeProvider(Protocol):
    """Look up the terminal FT8 end time by the contact/attempt UUID."""

    def ended_at_utc(self, contact_id: UUID) -> datetime | None:
        """Return the terminal attempt end, or None while it is unavailable."""


class _UnavailableCompletionTimeProvider:
    def ended_at_utc(self, contact_id: UUID) -> None:
        del contact_id


@dataclass(frozen=True)
class _Eligibility:
    reference_source: str
    reference_at_utc: datetime
    eligible_at_utc: datetime

    def as_json(self) -> dict[str, str]:
        return {
            "reference_source": self.reference_source,
            "reference_at_utc": _iso(self.reference_at_utc),
            "eligible_at_utc": _iso(self.eligible_at_utc),
        }


class PskReporterHttpClient:
    """Official XML retrieval adapter with an instance-local etiquette gate."""

    def __init__(
        self,
        config: PskReporterConfig,
        *,
        transport: HttpTransport | None = None,
    ) -> None:
        self._config = config
        self._transport = transport or _BoundedUrllibTransport(config.maximum_response_bytes)
        self._last_network_retrieval_at: datetime | None = None
        self._retrieval_gate = Lock()

    def query(
        self,
        *,
        now: datetime,
        window_s: int,
        frequency_range_hz: tuple[int, int] | None,
    ) -> PskReporterQueryResult:
        now_utc = _utc(now)
        parameters = build_pskreporter_query_parameters(
            self._config,
            window_s=window_s,
            frequency_range_hz=frequency_range_hz,
        )

        with self._retrieval_gate:
            if (
                self._last_network_retrieval_at is not None
                and now_utc - self._last_network_retrieval_at < self._config.minimum_query_interval
            ):
                return PskReporterQueryResult(
                    status=PskReporterQueryStatus.NOT_DUE,
                    query_parameters=parameters,
                )

            # Reserve the interval before I/O so concurrent and failed attempts count.
            self._last_network_retrieval_at = now_utc
        query_id = uuid4()
        url = f"{PSK_REPORTER_QUERY_URL}?{urlencode(parameters)}"
        try:
            response = self._transport.request(
                "GET",
                url,
                headers={
                    "Accept": "application/xml, text/xml",
                    "User-Agent": PSK_REPORTER_USER_AGENT,
                },
                body=None,
                timeout_s=self._config.timeout_s,
            )
            if not 200 <= response.status_code < 300:
                raise OSError(f"PSK Reporter returned HTTP {response.status_code}")
            if len(response.body) > self._config.maximum_response_bytes:
                raise OSError("PSK Reporter response exceeded maximum size")
            raw_xml = response.body.decode("utf-8")
            reports, skipped = parse_pskreporter_xml(
                raw_xml, maximum_reports=self._config.report_limit
            )
        except (
            TimeoutError,
            URLError,
            OSError,
            UnicodeDecodeError,
            ElementTree.ParseError,
        ) as error:
            return PskReporterQueryResult(
                status=PskReporterQueryStatus.QUERY_FAILED,
                query_id=query_id,
                queried_at_utc=now_utc,
                query_parameters=parameters,
                error=_bounded_error(error),
            )
        return PskReporterQueryResult(
            status=PskReporterQueryStatus.SUCCEEDED,
            query_id=query_id,
            queried_at_utc=now_utc,
            query_parameters=parameters,
            reports=reports,
            raw_xml=raw_xml,
            skipped_record_count=skipped,
        )


class _BoundedUrllibTransport:
    """Read at most the configured cap plus one byte from the provider socket."""

    def __init__(self, maximum_response_bytes: int) -> None:
        self._read_limit = maximum_response_bytes + 1

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout_s: float,
    ) -> UrllibHttpResponse:
        request = Request(url=url, data=body, headers=dict(headers), method=method)
        try:
            with urlopen(request, timeout=timeout_s) as response:
                return UrllibHttpResponse(response.status, response.read(self._read_limit))
        except HTTPError as error:
            return UrllibHttpResponse(error.code, error.read(self._read_limit))


class PskReporterAnalyticsService:
    """Batch due FT8 QSOs, correlate conservatively, and persist independent outcomes."""

    def __init__(
        self,
        repository: ForgePropagationHistoryRepository,
        config: PskReporterConfig,
        *,
        client: PskReporterHttpClient | None = None,
        completion_time_provider: PskReporterCompletionTimeProvider | None = None,
    ) -> None:
        self._repository = repository
        self._config = config
        self._client = client or PskReporterHttpClient(config)
        self._completion_time_provider = (
            completion_time_provider or _UnavailableCompletionTimeProvider()
        )

    def collect_recent(
        self, contacts: Sequence[Contact], *, now: datetime
    ) -> tuple[PskReporterSummary, ...]:
        now_utc = _utc(now)
        outcomes: dict[UUID, PskReporterSummary] = {}
        due: list[Contact] = []
        eligibility_by_contact: dict[UUID, _Eligibility] = {}
        terminal = {
            PskReporterCollectionStatus.QUERIED_ZERO_REPORTS,
            PskReporterCollectionStatus.QUERIED_WITH_REPORTS,
        }
        for contact in contacts:
            existing = self._repository.read_pskreporter(contact.contact_id)
            if existing is not None and existing.status in terminal:
                outcomes[contact.contact_id] = existing
                continue
            if not self._config.enabled or not _is_ft8_qso(contact):
                outcome = PskReporterSummary(
                    contact_id=contact.contact_id,
                    status=PskReporterCollectionStatus.NOT_QUERIED,
                    summary_json={"reason": "disabled_or_not_ft8"},
                )
                self._repository.save_pskreporter(outcome)
                outcomes[contact.contact_id] = outcome
                continue
            eligibility, invalid_completion = self._eligibility_for(contact)
            if invalid_completion is not None:
                outcome = PskReporterSummary(
                    contact_id=contact.contact_id,
                    status=PskReporterCollectionStatus.NOT_DUE,
                    summary_json={
                        "reason": "invalid_ft8_completion_time",
                        "eligibility": invalid_completion,
                    },
                )
                self._repository.save_pskreporter(outcome)
                outcomes[contact.contact_id] = outcome
                continue
            assert eligibility is not None
            eligibility_by_contact[contact.contact_id] = eligibility
            if now_utc < eligibility.eligible_at_utc:
                outcome = PskReporterSummary(
                    contact_id=contact.contact_id,
                    status=PskReporterCollectionStatus.NOT_DUE,
                    summary_json={"eligibility": eligibility.as_json()},
                )
                self._repository.save_pskreporter(outcome)
                outcomes[contact.contact_id] = outcome
                continue
            if len(due) < self._config.maximum_qsos_per_query:
                due.append(contact)
            else:
                outcome = PskReporterSummary(
                    contact_id=contact.contact_id,
                    status=PskReporterCollectionStatus.NOT_DUE,
                    summary_json={
                        "reason": "bounded_batch_pending",
                        "eligibility": eligibility.as_json(),
                    },
                )
                self._repository.save_pskreporter(outcome)
                outcomes[contact.contact_id] = outcome

        if due:
            maximum_age = max((now_utc - contact.started_at).total_seconds() for contact in due)
            required_window = ceil(maximum_age) + self._config.correlation_window_s
            if required_window > _MAX_PROVIDER_WINDOW_S:
                for contact in due:
                    outcome = _failure_summary(
                        contact,
                        now_utc,
                        "QSO is outside PSK Reporter's 24-hour retrieval window",
                        eligibility=eligibility_by_contact[contact.contact_id],
                    )
                    self._repository.save_pskreporter(outcome)
                    outcomes[contact.contact_id] = outcome
            else:
                query = self._client.query(
                    now=now_utc,
                    window_s=max(self._config.recent_window_s, required_window),
                    frequency_range_hz=_frequency_range(due),
                )
                batch = self._summaries_for_query(due, query, eligibility_by_contact)
                if query.query_id is not None and query.queried_at_utc is not None:
                    self._repository.save_pskreporter_batch(_provider_query_archive(query), batch)
                else:
                    for outcome in batch:
                        self._repository.save_pskreporter(outcome)
                for outcome in batch:
                    outcomes[outcome.contact_id] = outcome

        return tuple(outcomes[contact.contact_id] for contact in contacts)

    def _summaries_for_query(
        self,
        contacts: Sequence[Contact],
        query: PskReporterQueryResult,
        eligibility_by_contact: Mapping[UUID, _Eligibility],
    ) -> tuple[PskReporterSummary, ...]:
        if query.status is PskReporterQueryStatus.NOT_DUE:
            return tuple(
                PskReporterSummary(
                    contact_id=contact.contact_id,
                    status=PskReporterCollectionStatus.NOT_DUE,
                    summary_json={
                        "query_parameters": query.query_parameters,
                        "eligibility": eligibility_by_contact[contact.contact_id].as_json(),
                    },
                )
                for contact in contacts
            )
        if query.status is PskReporterQueryStatus.QUERY_FAILED:
            return tuple(
                _failure_summary(
                    contact,
                    query.queried_at_utc,
                    query.error or "PSK Reporter query failed",
                    query.query_parameters,
                    query_id=query.query_id,
                    eligibility=eligibility_by_contact[contact.contact_id],
                )
                for contact in contacts
            )

        reports_by_contact = _correlate_reports(contacts, query.reports, self._config)
        return tuple(
            _successful_summary(
                contact,
                reports_by_contact[contact.contact_id],
                query,
                self._config,
                eligibility_by_contact[contact.contact_id],
            )
            for contact in contacts
        )

    def _eligibility_for(
        self, contact: Contact
    ) -> tuple[_Eligibility | None, dict[str, str | None] | None]:
        try:
            completion = self._completion_time_provider.ended_at_utc(contact.contact_id)
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            return None, _invalid_eligibility_audit(None, _bounded_error(error))
        if completion is None:
            reference = contact.started_at + timedelta(seconds=self._config.correlation_window_s)
            return (
                _Eligibility(
                    reference_source="conservative_start_fallback",
                    reference_at_utc=reference,
                    eligible_at_utc=reference + timedelta(seconds=self._config.report_latency_s),
                ),
                None,
            )
        if not isinstance(completion, datetime):
            return None, _invalid_eligibility_audit(completion, "not a datetime")
        if completion.tzinfo is None or completion.utcoffset() is None:
            return None, _invalid_eligibility_audit(completion, "timestamp is timezone-naive")
        completion_utc = completion.astimezone(UTC)
        if completion_utc < contact.started_at:
            return None, _invalid_eligibility_audit(
                completion_utc, "timestamp precedes Contact.started_at"
            )
        return (
            _Eligibility(
                reference_source="ft8_terminal_end",
                reference_at_utc=completion_utc,
                eligible_at_utc=completion_utc + timedelta(seconds=self._config.report_latency_s),
            ),
            None,
        )


def parse_pskreporter_xml(
    xml: str, *, maximum_reports: int | None = None
) -> tuple[tuple[PskReporterReception, ...], int]:
    """Parse a valid provider document, skipping only malformed report records."""
    if maximum_reports is not None and maximum_reports < 1:
        raise ValueError("maximum_reports must be positive")
    root = ElementTree.fromstring(xml)
    if _local_name(root.tag) != "receptionReports":
        raise ElementTree.ParseError("PSK Reporter root must be receptionReports")
    reports: list[PskReporterReception] = []
    skipped = 0
    record_count = 0
    for element in root.iter():
        if _local_name(element.tag) != "receptionReport":
            continue
        record_count += 1
        if maximum_reports is not None and record_count > maximum_reports:
            raise ElementTree.ParseError(
                "PSK Reporter response exceeded the requested report limit"
            )
        try:
            attributes = element.attrib
            report = PskReporterReception(
                receiver_callsign=_required(attributes, "receiverCallsign").upper(),
                receiver_locator=_optional(attributes, "receiverLocator"),
                sender_callsign=_required(attributes, "senderCallsign").upper(),
                frequency_hz=int(_required(attributes, "frequency")),
                flow_start_utc=datetime.fromtimestamp(
                    int(_required(attributes, "flowStartSeconds")), UTC
                ),
                snr_db=_optional_int(attributes, "sNR"),
                mode=_optional(attributes, "mode"),
                sequence_number=_optional_int(attributes, "sequenceNumber"),
            )
        except (OSError, OverflowError, TypeError, ValueError):
            skipped += 1
            continue
        reports.append(report)
    return tuple(reports), skipped


def build_pskreporter_query_parameters(
    config: PskReporterConfig,
    *,
    window_s: int,
    frequency_range_hz: tuple[int, int] | None,
) -> dict[str, str | int]:
    """Build the exact bounded provider parameters used for reservation and I/O."""
    bounded_window = min(max(int(window_s), 1), _MAX_PROVIDER_WINDOW_S)
    parameters: dict[str, str | int] = {
        "senderCallsign": config.sender_callsign,
        "mode": config.mode,
        "flowStartSeconds": -bounded_window,
        "rronly": 1,
        "noactive": 1,
        "nolocator": 1,
        "rptlimit": config.report_limit,
    }
    if config.appcontact:
        parameters["appcontact"] = config.appcontact
    if frequency_range_hz is not None:
        lower, upper = frequency_range_hz
        parameters["frange"] = f"{lower}-{upper}"
    return parameters


def _correlate_reports(
    contacts: Sequence[Contact],
    reports: Sequence[PskReporterReception],
    config: PskReporterConfig,
) -> dict[UUID, list[PskReporterReception]]:
    correlated: dict[UUID, list[PskReporterReception]] = {
        contact.contact_id: [] for contact in contacts
    }
    for report in reports:
        if report.sender_callsign != config.sender_callsign:
            continue
        if report.mode is not None and report.mode.upper() != config.mode:
            continue
        matches = [
            contact
            for contact in contacts
            if _report_matches_contact(report, contact, config.correlation_window_s)
        ]
        if not matches:
            continue
        selected = min(
            matches,
            key=lambda contact: (
                abs((report.flow_start_utc - contact.started_at).total_seconds()),
                abs(report.frequency_hz - contact.frequency_hz),
                str(contact.contact_id),
            ),
        )
        correlated[selected.contact_id].append(report)
    return correlated


def _report_matches_contact(
    report: PskReporterReception, contact: Contact, correlation_window_s: int
) -> bool:
    if not _is_ft8_qso(contact):
        return False
    delta_s = (report.flow_start_utc - contact.started_at).total_seconds()
    if not -_PRE_QSO_TOLERANCE_S <= delta_s <= correlation_window_s:
        return False
    if abs(report.frequency_hz - contact.frequency_hz) > _FREQUENCY_TOLERANCE_HZ:
        return False
    try:
        return resolve_radio_band(Frequency(hz=report.frequency_hz)) == resolve_radio_band(
            Frequency(hz=contact.frequency_hz)
        )
    except RadioBandResolutionError:
        return False


def _successful_summary(
    contact: Contact,
    reports: Sequence[PskReporterReception],
    query: PskReporterQueryResult,
    config: PskReporterConfig,
    eligibility: _Eligibility,
) -> PskReporterSummary:
    local_coordinates = _contact_local_coordinates(contact)
    receiver_summaries = [_receiver_summary(report, local_coordinates) for report in reports]
    with_snr = [item for item in receiver_summaries if item["snr_db"] is not None]
    with_distance = [item for item in receiver_summaries if item["distance_km"] is not None]
    strongest = max(with_snr, key=lambda item: int(item["snr_db"])) if with_snr else None
    weakest = min(with_snr, key=lambda item: int(item["snr_db"])) if with_snr else None
    furthest = (
        max(with_distance, key=lambda item: float(item["distance_km"])) if with_distance else None
    )
    summary_json: dict[str, Any] = {
        "correlation_policy": {
            "name": PSK_REPORTER_CORRELATION_POLICY,
            "pre_qso_tolerance_s": _PRE_QSO_TOLERANCE_S,
            "post_qso_window_s": config.correlation_window_s,
            "frequency_tolerance_hz": _FREQUENCY_TOLERANCE_HZ,
        },
        "query_parameters": query.query_parameters,
        "report_count": len(receiver_summaries),
        "unique_receiver_grids": sorted(
            {
                str(item["receiver_locator"])
                for item in receiver_summaries
                if item["receiver_locator"] is not None
            }
        ),
        "strongest_report": strongest,
        "weakest_report": weakest,
        "furthest_report": furthest,
        "continent_summaries": (
            [] if not receiver_summaries else [_group_summary(receiver_summaries, furthest)]
        ),
        "receivers": receiver_summaries,
        "skipped_provider_record_count": query.skipped_record_count,
        "provider_query_id": None if query.query_id is None else str(query.query_id),
        "eligibility": eligibility.as_json(),
    }
    raw_response_json: dict[str, Any] = {
        "provider_query_id": None if query.query_id is None else str(query.query_id),
        "matched_reports": [report.model_dump(mode="json") for report in reports],
    }
    return PskReporterSummary(
        contact_id=contact.contact_id,
        query_id=query.query_id,
        status=(
            PskReporterCollectionStatus.QUERIED_WITH_REPORTS
            if reports
            else PskReporterCollectionStatus.QUERIED_ZERO_REPORTS
        ),
        queried_at_utc=query.queried_at_utc,
        raw_response_json=raw_response_json,
        summary_json=summary_json,
    )


def _receiver_summary(
    report: PskReporterReception,
    local_coordinates: tuple[float, float] | None,
) -> dict[str, Any]:
    receiver_coordinates: tuple[float, float] | None = None
    if report.receiver_locator is not None:
        try:
            receiver_coordinates = maidenhead_grid_center(report.receiver_locator)
        except ValueError:
            pass
    distance = None
    if local_coordinates is not None and receiver_coordinates is not None:
        distance = _distance_km(local_coordinates, receiver_coordinates)
    return {
        "receiver_callsign": report.receiver_callsign,
        "receiver_locator": report.receiver_locator,
        "receiver_latitude": None if receiver_coordinates is None else receiver_coordinates[0],
        "receiver_longitude": None if receiver_coordinates is None else receiver_coordinates[1],
        "continent": None,
        "distance_km": distance,
        "frequency_hz": report.frequency_hz,
        "flow_start_utc": _iso(report.flow_start_utc),
        "snr_db": report.snr_db,
        "mode": report.mode,
        "sequence_number": report.sequence_number,
    }


def _group_summary(
    receivers: Sequence[dict[str, Any]], furthest: dict[str, Any] | None
) -> dict[str, Any]:
    return {
        "continent": None,
        "report_count": len(receivers),
        "furthest_distance_km": None if furthest is None else furthest["distance_km"],
        "furthest_receiver": furthest,
    }


def _failure_summary(
    contact: Contact,
    queried_at: datetime | None,
    error: str,
    query_parameters: Mapping[str, str | int] | None = None,
    *,
    query_id: UUID | None = None,
    eligibility: _Eligibility | None = None,
) -> PskReporterSummary:
    summary_json: dict[str, Any] = {}
    if query_parameters is not None:
        summary_json["query_parameters"] = dict(query_parameters)
    if query_id is not None:
        summary_json["provider_query_id"] = str(query_id)
    if eligibility is not None:
        summary_json["eligibility"] = eligibility.as_json()
    return PskReporterSummary(
        contact_id=contact.contact_id,
        query_id=query_id,
        status=PskReporterCollectionStatus.QUERY_FAILED,
        queried_at_utc=queried_at,
        summary_json=summary_json or None,
        last_error=error[:1000],
    )


def _provider_query_archive(query: PskReporterQueryResult) -> PskReporterProviderQuery:
    if query.query_id is None or query.queried_at_utc is None:
        raise ValueError("network query result requires query identity and timestamp")
    return PskReporterProviderQuery(
        query_id=query.query_id,
        queried_at_utc=query.queried_at_utc,
        endpoint=PSK_REPORTER_QUERY_URL,
        status=query.status.value,
        query_parameters=query.query_parameters,
        raw_xml=query.raw_xml,
        skipped_record_count=query.skipped_record_count,
        error=query.error,
    )


def _invalid_eligibility_audit(value: object, error: str) -> dict[str, str | None]:
    if isinstance(value, datetime):
        reference = value.isoformat()
    elif value is None:
        reference = None
    else:
        reference = repr(value)[:200]
    return {
        "reference_source": "ft8_terminal_end",
        "reference_at_utc": reference,
        "eligible_at_utc": None,
        "validation_error": error[:1000],
    }


def _frequency_range(contacts: Sequence[Contact]) -> tuple[int, int] | None:
    frequencies = [contact.frequency_hz for contact in contacts if contact.frequency_hz > 0]
    if not frequencies:
        return None
    return max(1, min(frequencies) - _FREQUENCY_TOLERANCE_HZ), max(
        frequencies
    ) + _FREQUENCY_TOLERANCE_HZ


def _contact_local_coordinates(contact: Contact) -> tuple[float, float] | None:
    if contact.my_latitude is not None and contact.my_longitude is not None:
        return contact.my_latitude, contact.my_longitude
    if contact.my_grid6 is not None:
        try:
            return maidenhead_grid_center(contact.my_grid6)
        except ValueError:
            return None
    return None


def _is_ft8_qso(contact: Contact) -> bool:
    return contact.mode is RadioMode.FT8 and contact.source is ContactSource.FT8


def _required(attributes: Mapping[str, str], name: str) -> str:
    value = attributes.get(name)
    if value is None or not value.strip():
        raise ValueError(f"missing {name}")
    return value.strip()


def _optional(attributes: Mapping[str, str], name: str) -> str | None:
    value = attributes.get(name)
    if value is None or not value.strip():
        return None
    return value.strip()


def _optional_int(attributes: Mapping[str, str], name: str) -> int | None:
    value = _optional(attributes, name)
    return None if value is None else int(value)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _bounded_error(error: BaseException) -> str:
    return (str(error) or error.__class__.__name__)[:1000]


def _distance_km(start: tuple[float, float], end: tuple[float, float]) -> float:
    latitude_delta = radians(end[0] - start[0])
    longitude_delta = radians(end[1] - start[1])
    start_latitude = radians(start[0])
    end_latitude = radians(end[0])
    haversine = sin(latitude_delta / 2.0) ** 2 + (
        cos(start_latitude) * cos(end_latitude) * sin(longitude_delta / 2.0) ** 2
    )
    return 2.0 * _EARTH_RADIUS_KM * asin(min(1.0, sqrt(haversine)))
