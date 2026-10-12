"""NOAA/SWPC predicted monthly SSN evidence for Forge VOACAP.

The current NOAA feed is mutable and does not publish a per-record issue time.
Capture time is therefore the earliest provable availability time; it is never
rewritten as a release time or evidence of a historical as-issued forecast.
"""

from __future__ import annotations

import argparse
import hashlib
import sqlite3
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from json import dumps, loads
from pathlib import Path
from typing import Any, Protocol, Self
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from pydantic import Field, field_validator, model_validator

from rolling_thunder.domain import DomainModel

SSN_SCHEMA_VERSION = 2
MAX_FEED_BYTES = 1_000_000
NOAA_PREDICTED_SOLAR_CYCLE_URL = (
    "https://services.swpc.noaa.gov/json/solar-cycle/predicted-solar-cycle.json"
)
NOAA_SOURCE_ID = "noaa-swpc-predicted-solar-cycle"
NOAA_SOURCE_SCHEMA = "predicted-solar-cycle-json-published-fields-v1"
NOAA_REVISION_POLICY = (
    "mutable-current-feed; capture-each-use-append-only; "
    "no-historical-as-issued-claim-without-archived-evidence"
)
_NOAA_FIELDS = {
    "time-tag", "predicted_ssn", "high25_ssn", "low25_ssn", "high_ssn",
    "low_ssn", "high75_ssn", "low75_ssn", "predicted_f10.7", "high25_f10.7",
    "low25_f10.7", "high_f10.7", "low_f10.7", "high75_f10.7", "low75_f10.7",
}


class SsnValueSemantics(StrEnum):
    """Keep forecast and observed products explicitly distinct."""

    MONTHLY_SMOOTHED_PREDICTED = "monthly_smoothed_predicted_sunspot_number"
    MONTHLY_SMOOTHED_OBSERVED = "monthly_smoothed_observed_sunspot_number"


class SsnFeedResponse(DomainModel):
    """Bounded transport result retaining the exact evidence returned."""

    body: bytes = Field(max_length=MAX_FEED_BYTES)
    captured_at_utc: datetime
    status_code: int = Field(default=200, ge=100, le=599)
    final_url: str
    headers: dict[str, str] = Field(default_factory=dict)

    @field_validator("captured_at_utc")
    @classmethod
    def utc_time(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def bounded_headers(self) -> Self:
        if len(self.headers) > 64:
            raise ValueError("SSN response has too many HTTP headers")
        if any(len(key) > 120 or len(value) > 2_000 for key, value in self.headers.items()):
            raise ValueError("SSN response HTTP header exceeds bound")
        return self


class SsnFeedTransport(Protocol):
    def fetch(self, source_url: str, *, timeout_s: float, max_bytes: int) -> SsnFeedResponse: ...


class UrllibSsnFeedTransport:
    """Small HTTPS-only transport; tests inject a fake instead."""

    def fetch(self, source_url: str, *, timeout_s: float, max_bytes: int) -> SsnFeedResponse:
        _require_https(source_url)
        request = Request(source_url, headers={"Accept": "application/json"}, method="GET")
        try:
            with urlopen(request, timeout=timeout_s) as response:
                body = response.read(max_bytes + 1)
                status = int(response.status)
                final_url = response.geturl()
                headers = {str(key).lower(): str(value) for key, value in response.headers.items()}
                captured = datetime.now(UTC)
        except (HTTPError, URLError, TimeoutError, OSError) as error:
            raise OSError("NOAA SSN feed unavailable") from error
        if len(body) > max_bytes:
            raise ValueError("SSN feed response exceeds configured bound")
        return SsnFeedResponse(
            body=body, captured_at_utc=captured, status_code=status,
            final_url=final_url, headers=headers,
        )


class SmoothedSsnSnapshot(DomainModel):
    """One immutable captured revision of a forecast-month SSN record."""

    schema_version: int = Field(default=SSN_SCHEMA_VERSION, frozen=True)
    value: float = Field(ge=0, le=500)
    value_semantics: SsnValueSemantics
    target_month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    source_id: str = Field(min_length=1, max_length=120)
    source_url: str = Field(min_length=1, max_length=500)
    source_version: str = Field(min_length=1, max_length=120)
    source_schema: str = Field(min_length=1, max_length=160)
    source_revision_policy: str = Field(min_length=1, max_length=300)
    source_record_id: str = Field(min_length=1, max_length=200)
    source_released_at_utc: datetime | None = None
    captured_at_utc: datetime
    raw_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    raw_payload: bytes = Field(max_length=MAX_FEED_BYTES)
    source_http_headers: dict[str, str] = Field(default_factory=dict)

    @field_validator("source_released_at_utc", "captured_at_utc")
    @classmethod
    def utc_times(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _utc(value)

    @model_validator(mode="after")
    def provenance(self) -> Self:
        _require_https(self.source_url)
        if hashlib.sha256(self.raw_payload).hexdigest() != self.raw_sha256:
            raise ValueError("SSN raw payload hash does not match retained bytes")
        if (
            self.source_released_at_utc is not None
            and self.source_released_at_utc > self.captured_at_utc
        ):
            raise ValueError("SSN source release cannot postdate capture")
        if len(self.source_http_headers) > 64:
            raise ValueError("SSN snapshot has too many retained HTTP headers")
        return self

    @property
    def canonical_sha256(self) -> str:
        return _sha(self.model_dump(mode="json"))

    def require_for_target(
        self, *, target_month: str, as_of_utc: datetime, max_capture_age: timedelta
    ) -> None:
        as_of = _utc(as_of_utc)
        if max_capture_age <= timedelta(0):
            raise ValueError("SSN capture freshness limit must be positive")
        if self.value_semantics is not SsnValueSemantics.MONTHLY_SMOOTHED_PREDICTED:
            raise ValueError("C4 requires predicted_ssn, not observed SSN")
        if self.target_month != target_month:
            raise ValueError("SSN forecast month does not match VOACAP target month")
        if self.captured_at_utc > as_of:
            raise ValueError("SSN snapshot contains future knowledge")
        if as_of - self.captured_at_utc > max_capture_age:
            raise ValueError("SSN snapshot capture is stale")
        if self.source_released_at_utc is not None and self.source_released_at_utc > as_of:
            raise ValueError("SSN release contains future knowledge")


class NoaaSwpcPredictedSsnAdapter:
    """Parse NOAA's documented predicted-solar-cycle JSON using injected I/O."""

    def __init__(
        self, *, transport: SsnFeedTransport, timeout_s: float = 10.0,
        max_bytes: int = MAX_FEED_BYTES,
        source_url: str = NOAA_PREDICTED_SOLAR_CYCLE_URL,
    ) -> None:
        _require_https(source_url)
        if timeout_s <= 0 or timeout_s > 30:
            raise ValueError("SSN timeout must be within 0-30 seconds")
        if max_bytes < 1 or max_bytes > MAX_FEED_BYTES:
            raise ValueError("SSN response bound is invalid")
        self._transport = transport
        self._source_url = source_url
        self._timeout_s = timeout_s
        self._max_bytes = max_bytes

    def fetch(
        self, *, target_month: str, as_of_utc: datetime,
        max_capture_age: timedelta = timedelta(hours=24),
    ) -> SmoothedSsnSnapshot:
        response = self._transport.fetch(
            self._source_url, timeout_s=self._timeout_s, max_bytes=self._max_bytes
        )
        if not 200 <= response.status_code < 300:
            raise ValueError(f"NOAA SSN feed returned HTTP {response.status_code}")
        if response.final_url != self._source_url:
            raise ValueError("NOAA SSN feed redirected away from the pinned source URL")
        if len(response.body) > self._max_bytes:
            raise ValueError("SSN feed response exceeds configured bound")
        try:
            payload = loads(response.body)
        except (UnicodeDecodeError, ValueError) as error:
            raise ValueError("NOAA SSN feed is not valid JSON") from error
        if not isinstance(payload, list):
            raise TypeError("NOAA SSN feed root must be an array")
        matches: list[Mapping[str, Any]] = []
        for record in payload:
            if not isinstance(record, Mapping) or set(record) != _NOAA_FIELDS:
                raise ValueError("NOAA SSN feed schema is ambiguous or unsupported")
            if record.get("time-tag") == target_month:
                matches.append(record)
        if len(matches) != 1:
            raise ValueError("NOAA SSN feed must contain exactly one target-month record")
        predicted_ssn = matches[0].get("predicted_ssn")
        if isinstance(predicted_ssn, bool) or not isinstance(predicted_ssn, (int, float)):
            raise TypeError("NOAA target record predicted_ssn must be numeric")
        raw_sha = hashlib.sha256(response.body).hexdigest()
        snapshot = SmoothedSsnSnapshot(
            value=predicted_ssn,
            value_semantics=SsnValueSemantics.MONTHLY_SMOOTHED_PREDICTED,
            target_month=target_month,
            source_id=NOAA_SOURCE_ID,
            source_url=self._source_url,
            source_version=NOAA_SOURCE_SCHEMA,
            source_schema=NOAA_SOURCE_SCHEMA,
            source_revision_policy=NOAA_REVISION_POLICY,
            source_record_id=f"{target_month}:predicted_ssn",
            source_released_at_utc=None,
            captured_at_utc=response.captured_at_utc,
            raw_sha256=raw_sha,
            raw_payload=response.body,
            source_http_headers=response.headers,
        )
        snapshot.require_for_target(
            target_month=target_month, as_of_utc=as_of_utc,
            max_capture_age=max_capture_age,
        )
        return snapshot


class SsnSnapshotRepository:
    """Append-only captured revisions, including raw bytes and HTTP metadata."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS predicted_ssn_snapshot_v2(
                  canonical_sha256 TEXT PRIMARY KEY,source_id TEXT NOT NULL,
                  source_version TEXT NOT NULL,source_schema TEXT NOT NULL,
                  source_revision_policy TEXT NOT NULL,source_record_id TEXT NOT NULL,
                  target_month TEXT NOT NULL,value_semantics TEXT NOT NULL,
                  source_released_at_utc TEXT,captured_at_utc TEXT NOT NULL,
                  raw_sha256 TEXT NOT NULL,raw_payload BLOB NOT NULL,
                  source_http_headers_json TEXT NOT NULL,payload_json TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS predicted_ssn_revision_v2
                  ON predicted_ssn_snapshot_v2(source_id,source_record_id,captured_at_utc);
                """
            )

    def add(self, snapshot: SmoothedSsnSnapshot) -> bool:
        payload = snapshot.model_dump_json(exclude={"raw_payload"})
        with sqlite3.connect(self.path) as db:
            existing = db.execute(
                "SELECT 1 FROM predicted_ssn_snapshot_v2 WHERE canonical_sha256=?",
                (snapshot.canonical_sha256,),
            ).fetchone()
            if existing is not None:
                return False
            db.execute(
                "INSERT INTO predicted_ssn_snapshot_v2 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    snapshot.canonical_sha256, snapshot.source_id, snapshot.source_version,
                    snapshot.source_schema, snapshot.source_revision_policy,
                    snapshot.source_record_id, snapshot.target_month,
                    snapshot.value_semantics.value,
                    None if snapshot.source_released_at_utc is None
                    else _time(snapshot.source_released_at_utc),
                    _time(snapshot.captured_at_utc), snapshot.raw_sha256,
                    snapshot.raw_payload, dumps(snapshot.source_http_headers, sort_keys=True),
                    payload,
                ),
            )
        return True

    def status(self) -> dict[str, object]:
        return self.read_status(self.path)

    @staticmethod
    def read_status(path: Path) -> dict[str, object]:
        """Inspect an existing store query-only without running schema creation."""
        uri = f"file:{path.resolve()}?mode=ro"
        with sqlite3.connect(uri, uri=True) as db:
            db.execute("PRAGMA query_only=ON")
            row = db.execute(
                "SELECT COUNT(*),MAX(captured_at_utc),COUNT(DISTINCT target_month) "
                "FROM predicted_ssn_snapshot_v2"
            ).fetchone()
        return {
            "schema_version": SSN_SCHEMA_VERSION,
            "revision_count": int(row[0]),
            "latest_capture_at_utc": row[1],
            "target_month_count": int(row[2]),
        }


class HamQslRawSunspotsAudit:
    """Read-only evidence that cannot be promoted to predicted monthly SSN."""

    def __init__(self, history_path: Path) -> None:
        self._history_path = history_path

    def latest(self) -> dict[str, str] | None:
        uri = f"file:{self._history_path.resolve()}?mode=ro"
        with sqlite3.connect(uri, uri=True) as db:
            db.execute("PRAGMA query_only=ON")
            row = db.execute(
                "SELECT collected_at_utc,source_url,source_updated,payload_json "
                "FROM solar_observation ORDER BY collected_at_utc DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        payload = loads(row[3])
        return {
            "collected_at_utc": str(row[0]), "source_url": str(row[1]),
            "source_updated": str(row[2]), "raw_sunspots": str(payload.get("sunspots", "")),
            "eligibility": "ineligible_raw_observed_count_not_predicted_monthly_ssn",
        }

    def as_smoothed_snapshot(self) -> SmoothedSsnSnapshot:
        raise ValueError("HamQSL raw sunspots are not NOAA predicted monthly SSN")


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect/capture NOAA predicted monthly SSN")
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--target-month")
    args = parser.parse_args()
    if args.status:
        if not args.database.is_file():
            parser.error("--status requires an existing database")
        print(dumps(SsnSnapshotRepository.read_status(args.database), sort_keys=True))
        return
    if args.target_month is None:
        parser.error("capture requires --target-month")
    adapter = NoaaSwpcPredictedSsnAdapter(transport=UrllibSsnFeedTransport())
    snapshot = adapter.fetch(target_month=args.target_month, as_of_utc=datetime.now(UTC))
    added = SsnSnapshotRepository(args.database).add(snapshot)
    print(dumps({
        "state": "captured" if added else "exact_replay",
        "target_month": snapshot.target_month,
        "value_semantics": snapshot.value_semantics.value,
        "captured_at_utc": _time(snapshot.captured_at_utc),
        "source_released_at_utc": None,
        "raw_sha256": snapshot.raw_sha256,
        "source_http_headers": snapshot.source_http_headers,
    }, sort_keys=True))


def _require_https(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("SSN source URL must be absolute credential-free HTTPS")


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC)


def _time(value: datetime) -> str:
    return _utc(value).isoformat().replace("+00:00", "Z")


def _sha(value: Any) -> str:
    return hashlib.sha256(
        dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


if __name__ == "__main__":
    main()
