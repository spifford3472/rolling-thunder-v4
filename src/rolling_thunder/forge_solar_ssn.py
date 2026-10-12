"""Auditable monthly smoothed sunspot-number ingestion for Forge VOACAP.

The adapter contract is deliberately provider-neutral.  An authoritative feed
adapter may supply the normalized wire contract after that provider's published
schema has been reviewed.  HamQSL's instantaneous ``sunspots`` field is exposed
only through an explicitly incompatible read-only audit view.
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from json import dumps, loads
from pathlib import Path
from typing import Any, Protocol

from pydantic import Field, field_validator, model_validator

from rolling_thunder.domain import DomainModel

SSN_SCHEMA_VERSION = 1
MAX_FEED_BYTES = 1_000_000


class SsnValueSemantics(StrEnum):
    """Values accepted by C4; raw daily spot counts are intentionally absent."""

    MONTHLY_SMOOTHED_OBSERVED = "monthly_smoothed_observed_sunspot_number"


class SsnFeedResponse(DomainModel):
    """Bounded transport result; adapters retain the exact bytes by SHA only."""

    body: bytes = Field(max_length=MAX_FEED_BYTES)
    captured_at_utc: datetime

    @field_validator("captured_at_utc")
    @classmethod
    def utc_time(cls, value: datetime) -> datetime:
        return _utc(value)


class SsnFeedTransport(Protocol):
    def fetch(self, source_url: str, *, timeout_s: float, max_bytes: int) -> SsnFeedResponse: ...


class SmoothedSsnSnapshot(DomainModel):
    """Immutable source record suitable for a VOACAP environment snapshot."""

    schema_version: int = Field(default=SSN_SCHEMA_VERSION, frozen=True)
    value: float = Field(ge=0, le=500)
    value_semantics: SsnValueSemantics
    source_id: str = Field(min_length=1, max_length=120)
    source_url: str = Field(min_length=1, max_length=500)
    source_version: str = Field(min_length=1, max_length=120)
    source_record_id: str = Field(min_length=1, max_length=200)
    observed_at_utc: datetime
    released_at_utc: datetime
    captured_at_utc: datetime
    raw_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("observed_at_utc", "released_at_utc", "captured_at_utc")
    @classmethod
    def utc_times(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def temporal_provenance(self) -> SmoothedSsnSnapshot:
        if self.observed_at_utc > self.released_at_utc:
            raise ValueError("SSN observation cannot postdate its source release")
        if self.released_at_utc > self.captured_at_utc:
            raise ValueError("SSN source release cannot postdate capture")
        return self

    @property
    def canonical_sha256(self) -> str:
        return _sha(self.model_dump(mode="json"))

    def require_fresh(
        self,
        *,
        as_of_utc: datetime,
        max_capture_age: timedelta,
        max_observation_age: timedelta,
    ) -> None:
        as_of = _utc(as_of_utc)
        if max_capture_age <= timedelta(0) or max_observation_age <= timedelta(0):
            raise ValueError("SSN freshness limits must be positive")
        if self.captured_at_utc > as_of or self.released_at_utc > as_of:
            raise ValueError("SSN snapshot contains future knowledge")
        if as_of - self.captured_at_utc > max_capture_age:
            raise ValueError("SSN snapshot capture is stale")
        if as_of - self.observed_at_utc > max_observation_age:
            raise ValueError("SSN observation period is stale")


class VersionedSmoothedSsnJsonAdapter:
    """Parse the internal normalized feed contract using an injected transport.

    This is not a claim about NOAA or SILSO's public wire format.  A reviewed
    provider adapter must normalize its response to this exact schema and pin
    the provider identity/version in configuration.
    """

    def __init__(
        self,
        *,
        transport: SsnFeedTransport,
        source_id: str,
        source_url: str,
        source_version: str,
        timeout_s: float = 10.0,
        max_bytes: int = MAX_FEED_BYTES,
    ) -> None:
        if not source_id.strip() or not source_version.strip():
            raise ValueError("SSN source identity and version are required")
        if timeout_s <= 0 or timeout_s > 30:
            raise ValueError("SSN timeout must be within 0-30 seconds")
        if max_bytes < 1 or max_bytes > MAX_FEED_BYTES:
            raise ValueError("SSN response bound is invalid")
        self._transport = transport
        self._source_id = source_id
        self._source_url = source_url
        self._source_version = source_version
        self._timeout_s = timeout_s
        self._max_bytes = max_bytes

    def fetch(
        self,
        *,
        as_of_utc: datetime,
        max_capture_age: timedelta,
        max_observation_age: timedelta,
    ) -> SmoothedSsnSnapshot:
        response = self._transport.fetch(
            self._source_url, timeout_s=self._timeout_s, max_bytes=self._max_bytes
        )
        if len(response.body) > self._max_bytes:
            raise ValueError("SSN feed response exceeds configured bound")
        try:
            payload = loads(response.body)
        except (UnicodeDecodeError, ValueError) as error:
            raise ValueError("SSN feed is not valid JSON") from error
        if not isinstance(payload, Mapping):
            raise TypeError("SSN feed root must be an object")
        expected = {
            "contract",
            "value",
            "value_semantics",
            "source_record_id",
            "observed_at_utc",
            "released_at_utc",
        }
        if set(payload) != expected or payload.get("contract") != "smoothed-ssn-v1":
            raise ValueError("SSN feed contract is ambiguous or unsupported")
        snapshot = SmoothedSsnSnapshot(
            value=payload["value"],
            value_semantics=payload["value_semantics"],
            source_id=self._source_id,
            source_url=self._source_url,
            source_version=self._source_version,
            source_record_id=payload["source_record_id"],
            observed_at_utc=payload["observed_at_utc"],
            released_at_utc=payload["released_at_utc"],
            captured_at_utc=response.captured_at_utc,
            raw_sha256=hashlib.sha256(response.body).hexdigest(),
        )
        snapshot.require_fresh(
            as_of_utc=as_of_utc,
            max_capture_age=max_capture_age,
            max_observation_age=max_observation_age,
        )
        return snapshot


class SsnSnapshotRepository:
    """Append-only snapshot store separate from raw propagation observations."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS smoothed_ssn_snapshot_v1(
                  canonical_sha256 TEXT PRIMARY KEY,
                  source_id TEXT NOT NULL,
                  source_version TEXT NOT NULL,
                  source_record_id TEXT NOT NULL,
                  value_semantics TEXT NOT NULL,
                  observed_at_utc TEXT NOT NULL,
                  released_at_utc TEXT NOT NULL,
                  captured_at_utc TEXT NOT NULL,
                  payload_json TEXT NOT NULL,
                  UNIQUE(source_id,source_version,source_record_id)
                );
                """
            )

    def add(self, snapshot: SmoothedSsnSnapshot) -> bool:
        payload = snapshot.model_dump_json()
        with sqlite3.connect(self.path) as db:
            existing = db.execute(
                """SELECT canonical_sha256 FROM smoothed_ssn_snapshot_v1
                WHERE source_id=? AND source_version=? AND source_record_id=?""",
                (snapshot.source_id, snapshot.source_version, snapshot.source_record_id),
            ).fetchone()
            if existing is not None:
                if existing[0] != snapshot.canonical_sha256:
                    raise ValueError("SSN source record replay changed immutable content")
                return False
            db.execute(
                """INSERT INTO smoothed_ssn_snapshot_v1 VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    snapshot.canonical_sha256,
                    snapshot.source_id,
                    snapshot.source_version,
                    snapshot.source_record_id,
                    snapshot.value_semantics.value,
                    _time(snapshot.observed_at_utc),
                    _time(snapshot.released_at_utc),
                    _time(snapshot.captured_at_utc),
                    payload,
                ),
            )
        return True


class HamQslRawSunspotsAudit:
    """Read-only evidence that cannot be promoted to smoothed SSN."""

    def __init__(self, history_path: Path) -> None:
        self._history_path = history_path

    def latest(self) -> dict[str, str] | None:
        uri = f"file:{self._history_path.resolve()}?mode=ro"
        with sqlite3.connect(uri, uri=True) as db:
            db.execute("PRAGMA query_only=ON")
            row = db.execute(
                """SELECT collected_at_utc,source_url,source_updated,payload_json
                FROM solar_observation ORDER BY collected_at_utc DESC LIMIT 1"""
            ).fetchone()
        if row is None:
            return None
        payload = loads(row[3])
        return {
            "collected_at_utc": str(row[0]),
            "source_url": str(row[1]),
            "source_updated": str(row[2]),
            "raw_sunspots": str(payload.get("sunspots", "")),
            "eligibility": "ineligible_raw_observed_count_not_monthly_smoothed_ssn",
        }

    def as_smoothed_snapshot(self) -> SmoothedSsnSnapshot:
        raise ValueError("HamQSL raw sunspots are not monthly smoothed VOACAP SSN")


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
