"""Forge-side raw propagation observations and QSO correlation persistence."""

from __future__ import annotations

import gzip
import hashlib
import sqlite3
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from json import dumps, loads
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import Field, field_validator

from rolling_thunder.domain import Contact, DomainModel

PROPAGATION_HISTORY_SCHEMA_VERSION = 2


class PropagationHistoryStorageError(RuntimeError):
    """Raised when the independent propagation-history store is unusable."""


class IonosphereMetric(StrEnum):
    MUF_3000 = "mufd"
    FOF2 = "fof2"


class WeatherObservationRole(StrEnum):
    LOCAL = "local"
    CONTACT = "contact"


class PskReporterCollectionStatus(StrEnum):
    NOT_QUERIED = "not_queried"
    NOT_DUE = "not_due"
    QUERY_FAILED = "query_failed"
    QUERIED_ZERO_REPORTS = "queried_zero_reports"
    QUERIED_WITH_REPORTS = "queried_with_reports"


class SolarObservation(DomainModel):
    """One raw HamQSL observation with collection-time provenance."""

    source_url: str = Field(min_length=1, max_length=500)
    source_updated: str = Field(min_length=1, max_length=120)
    collected_at_utc: datetime
    raw_xml: str = Field(min_length=1)
    solarflux: str
    aindex: str
    kindex: str
    xray: str
    sunspots: str
    protonflux: str
    aurora: str
    normalization: str
    latdegree: str
    solarwind: str
    magneticfield: str
    geomagfield: str
    signalnoise: str

    @field_validator("collected_at_utc")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("collected_at_utc must be timezone-aware")
        return value.astimezone(UTC)


class Kc2gSnapshot(DomainModel):
    """Complete raw KC2G GeoJSON snapshot and its provenance."""

    metric: IonosphereMetric
    source_url: str = Field(min_length=1, max_length=500)
    collected_at_utc: datetime
    geojson: dict[str, Any]

    @field_validator("collected_at_utc")
    @classmethod
    def normalize_snapshot_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("collected_at_utc must be timezone-aware")
        return value.astimezone(UTC)


class WeatherObservation(DomainModel):
    """Weather observation associated with one side of a contact."""

    contact_id: UUID
    role: WeatherObservationRole
    provider_id: str = Field(min_length=1, max_length=120)
    provider_name: str | None = Field(default=None, max_length=160)
    attribution_text: str | None = Field(default=None, max_length=500)
    attribution_url: str | None = Field(default=None, max_length=500)
    license_name: str | None = Field(default=None, max_length=500)
    license_url: str | None = Field(default=None, max_length=500)
    source_at_utc: datetime | None = None
    fetched_at_utc: datetime
    latitude: float = Field(ge=-90.0, le=90.0)
    longitude: float = Field(ge=-180.0, le=180.0)
    condition: str | None = Field(default=None, max_length=80)
    temperature_c: float | None = None
    relative_humidity_percent: float | None = Field(default=None, ge=0.0, le=100.0)
    payload_json: dict[str, Any]

    @field_validator("source_at_utc", "fetched_at_utc")
    @classmethod
    def normalize_weather_time(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("weather timestamps must be timezone-aware")
        return value.astimezone(UTC)


class IonosphereCorrelation(DomainModel):
    """Ionosphere snapshot references captured for a contact."""

    contact_id: UUID
    captured_at_utc: datetime
    muf_snapshot_at_utc: datetime | None = None
    fof2_snapshot_at_utc: datetime | None = None
    payload_json: dict[str, Any]

    @field_validator("captured_at_utc", "muf_snapshot_at_utc", "fof2_snapshot_at_utc")
    @classmethod
    def normalize_correlation_time(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("ionosphere timestamps must be timezone-aware")
        return value.astimezone(UTC)


class VoacapPrediction(DomainModel):
    """Versioned VOACAP request/response captured for an immutable contact."""

    contact_id: UUID
    captured_at_utc: datetime
    request_json: dict[str, Any]
    service_version: str = Field(min_length=1, max_length=120)
    response_json: dict[str, Any]
    actual_hour_muf_mhz: float | None = None
    actual_hour_reliability: float | None = None
    actual_hour_rating: str | None = Field(default=None, max_length=80)
    actual_hour_snr_db: float | None = None


class PskReporterSummary(DomainModel):
    """Explicit collection state; absent reports are zero only after a successful query."""

    contact_id: UUID
    query_id: UUID | None = None
    status: PskReporterCollectionStatus = PskReporterCollectionStatus.NOT_QUERIED
    queried_at_utc: datetime | None = None
    raw_response_json: dict[str, Any] | None = None
    summary_json: dict[str, Any] | None = None
    last_error: str | None = Field(default=None, max_length=1000)

    @field_validator("queried_at_utc")
    @classmethod
    def normalize_query_time(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("queried_at_utc must be timezone-aware")
        return value.astimezone(UTC)


class PskReporterProviderQuery(DomainModel):
    """One provider retrieval stored once and referenced by every correlated QSO."""

    query_id: UUID
    queried_at_utc: datetime
    endpoint: str = Field(min_length=1, max_length=500)
    status: str = Field(min_length=1, max_length=64)
    query_parameters: dict[str, str | int]
    raw_xml: str | None = None
    skipped_record_count: int = Field(default=0, ge=0)
    error: str | None = Field(default=None, max_length=1000)

    @field_validator("queried_at_utc")
    @classmethod
    def normalize_provider_query_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("queried_at_utc must be timezone-aware")
        return value.astimezone(UTC)


class ForgePropagationHistoryRepository:
    """Dedicated SQLite repository; never shares contact-sync or spot tables."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        self._initialize()

    def add_solar(self, observation: SolarObservation) -> None:
        values = observation.model_dump(mode="json")
        self._execute(
            """
            INSERT OR IGNORE INTO solar_observation (
                collected_at_utc, source_url, source_updated, payload_json, raw_xml
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                values["collected_at_utc"],
                observation.source_url,
                observation.source_updated,
                _json(values),
                observation.raw_xml,
            ),
        )

    def add_kc2g(self, snapshot: Kc2gSnapshot) -> None:
        raw = _json(snapshot.geojson).encode("utf-8")
        self._execute(
            """
            INSERT OR IGNORE INTO kc2g_snapshot (
                metric, collected_at_utc, source_url, sha256, compression, snapshot_blob
            ) VALUES (?, ?, ?, ?, 'gzip', ?)
            """,
            (
                snapshot.metric.value,
                _time(snapshot.collected_at_utc),
                snapshot.source_url,
                hashlib.sha256(raw).hexdigest(),
                gzip.compress(raw, mtime=0),
            ),
        )

    def add_qso(self, contact: Contact) -> None:
        contact_id = str(contact.contact_id)
        payload_json = _json(contact.model_dump(mode="json"))
        try:
            with sqlite3.connect(self._database_path) as connection:
                connection.execute(
                    """
                    INSERT INTO qso_observation (contact_id, occurred_at_utc, payload_json)
                    VALUES (?, ?, ?)
                    ON CONFLICT(contact_id) DO NOTHING
                    """,
                    (contact_id, _time(contact.started_at), payload_json),
                )
                row = connection.execute(
                    "SELECT payload_json FROM qso_observation WHERE contact_id = ?",
                    (contact_id,),
                ).fetchone()
                if row is None or row[0] != payload_json:
                    raise PropagationHistoryStorageError(
                        f"QSO idempotency conflict for contact_id {contact_id}: "
                        "stored payload differs from replay"
                    )
                connection.commit()
        except PropagationHistoryStorageError:
            raise
        except sqlite3.Error as error:
            raise PropagationHistoryStorageError("propagation-history write failed") from error

    def save_weather(self, observation: WeatherObservation) -> None:
        self._execute(
            """
            INSERT INTO weather_observation (
                contact_id, role, provider_id, provider_name, attribution_text,
                attribution_url, license_name, license_url, source_at_utc,
                fetched_at_utc, latitude, longitude, condition, temperature_c,
                relative_humidity_percent, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(contact_id, role) DO UPDATE SET
                provider_id=excluded.provider_id,
                provider_name=excluded.provider_name,
                attribution_text=excluded.attribution_text,
                attribution_url=excluded.attribution_url,
                license_name=excluded.license_name,
                license_url=excluded.license_url,
                source_at_utc=excluded.source_at_utc,
                fetched_at_utc=excluded.fetched_at_utc,
                latitude=excluded.latitude,
                longitude=excluded.longitude,
                condition=excluded.condition,
                temperature_c=excluded.temperature_c,
                relative_humidity_percent=excluded.relative_humidity_percent,
                payload_json=excluded.payload_json
            """,
            (
                str(observation.contact_id),
                observation.role.value,
                observation.provider_id,
                observation.provider_name,
                observation.attribution_text,
                observation.attribution_url,
                observation.license_name,
                observation.license_url,
                None if observation.source_at_utc is None else _time(observation.source_at_utc),
                _time(observation.fetched_at_utc),
                observation.latitude,
                observation.longitude,
                observation.condition,
                observation.temperature_c,
                observation.relative_humidity_percent,
                _json(observation.payload_json),
            ),
        )

    def save_ionosphere(self, correlation: IonosphereCorrelation) -> None:
        self._execute(
            """
            INSERT INTO qso_ionosphere (
                contact_id, captured_at_utc, muf_snapshot_at_utc,
                fof2_snapshot_at_utc, payload_json
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(contact_id) DO UPDATE SET
                captured_at_utc=excluded.captured_at_utc,
                muf_snapshot_at_utc=excluded.muf_snapshot_at_utc,
                fof2_snapshot_at_utc=excluded.fof2_snapshot_at_utc,
                payload_json=excluded.payload_json
            """,
            (
                str(correlation.contact_id),
                _time(correlation.captured_at_utc),
                None
                if correlation.muf_snapshot_at_utc is None
                else _time(correlation.muf_snapshot_at_utc),
                None
                if correlation.fof2_snapshot_at_utc is None
                else _time(correlation.fof2_snapshot_at_utc),
                _json(correlation.payload_json),
            ),
        )

    def save_voacap(self, prediction: VoacapPrediction) -> None:
        self._execute(
            """
            INSERT INTO qso_voacap_prediction (
                contact_id, captured_at_utc, request_json, service_version,
                response_json, actual_hour_muf_mhz, actual_hour_reliability,
                actual_hour_rating, actual_hour_snr_db
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(contact_id) DO UPDATE SET
                captured_at_utc=excluded.captured_at_utc,
                request_json=excluded.request_json,
                service_version=excluded.service_version,
                response_json=excluded.response_json,
                actual_hour_muf_mhz=excluded.actual_hour_muf_mhz,
                actual_hour_reliability=excluded.actual_hour_reliability,
                actual_hour_rating=excluded.actual_hour_rating,
                actual_hour_snr_db=excluded.actual_hour_snr_db
            """,
            (
                str(prediction.contact_id),
                _time(prediction.captured_at_utc),
                _json(prediction.request_json),
                prediction.service_version,
                _json(prediction.response_json),
                prediction.actual_hour_muf_mhz,
                prediction.actual_hour_reliability,
                prediction.actual_hour_rating,
                prediction.actual_hour_snr_db,
            ),
        )

    def save_pskreporter(self, summary: PskReporterSummary) -> None:
        self._execute(
            """
            INSERT INTO qso_pskreporter_summary (
                contact_id, query_id, status, queried_at_utc, raw_response_json,
                summary_json, last_error
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(contact_id) DO UPDATE SET
                query_id=excluded.query_id,
                status=excluded.status,
                queried_at_utc=excluded.queried_at_utc,
                raw_response_json=excluded.raw_response_json,
                summary_json=excluded.summary_json,
                last_error=excluded.last_error
            """,
            (
                str(summary.contact_id),
                None if summary.query_id is None else str(summary.query_id),
                summary.status.value,
                None if summary.queried_at_utc is None else _time(summary.queried_at_utc),
                None if summary.raw_response_json is None else _json(summary.raw_response_json),
                None if summary.summary_json is None else _json(summary.summary_json),
                summary.last_error,
            ),
        )

    def save_pskreporter_batch(
        self,
        query: PskReporterProviderQuery,
        summaries: tuple[PskReporterSummary, ...],
    ) -> None:
        """Atomically store one provider payload and all QSO references to it."""
        if any(summary.query_id != query.query_id for summary in summaries):
            raise ValueError("every PSK Reporter summary must reference the provider query")
        try:
            with sqlite3.connect(self._database_path) as connection:
                connection.execute("PRAGMA foreign_keys = ON")
                connection.execute(
                    """
                    INSERT INTO pskreporter_query (
                        query_id, queried_at_utc, endpoint, status,
                        query_parameters_json, raw_xml, skipped_record_count, last_error
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(query.query_id),
                        _time(query.queried_at_utc),
                        query.endpoint,
                        query.status,
                        _json(query.query_parameters),
                        query.raw_xml,
                        query.skipped_record_count,
                        query.error,
                    ),
                )
                for summary in summaries:
                    connection.execute(
                        """
                        INSERT INTO qso_pskreporter_summary (
                            contact_id, query_id, status, queried_at_utc,
                            raw_response_json, summary_json, last_error
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(contact_id) DO UPDATE SET
                            query_id=excluded.query_id,
                            status=excluded.status,
                            queried_at_utc=excluded.queried_at_utc,
                            raw_response_json=excluded.raw_response_json,
                            summary_json=excluded.summary_json,
                            last_error=excluded.last_error
                        """,
                        (
                            str(summary.contact_id),
                            str(query.query_id),
                            summary.status.value,
                            None
                            if summary.queried_at_utc is None
                            else _time(summary.queried_at_utc),
                            None
                            if summary.raw_response_json is None
                            else _json(summary.raw_response_json),
                            None if summary.summary_json is None else _json(summary.summary_json),
                            summary.last_error,
                        ),
                    )
                connection.commit()
        except sqlite3.Error as error:
            raise PropagationHistoryStorageError(
                "PSK Reporter batch persistence failed"
            ) from error

    def read_pskreporter_query(self, query_id: UUID) -> PskReporterProviderQuery | None:
        """Read one provider query archive for audit and recomputation."""
        try:
            with sqlite3.connect(self._database_path) as connection:
                row = connection.execute(
                    """
                    SELECT queried_at_utc, endpoint, status, query_parameters_json,
                           raw_xml, skipped_record_count, last_error
                    FROM pskreporter_query
                    WHERE query_id = ?
                    """,
                    (str(query_id),),
                ).fetchone()
        except sqlite3.Error as error:
            raise PropagationHistoryStorageError("PSK Reporter query read failed") from error
        if row is None:
            return None
        try:
            parameters = loads(row[3])
            if not isinstance(parameters, dict):
                raise TypeError("query parameters must be an object")
            return PskReporterProviderQuery(
                query_id=query_id,
                queried_at_utc=row[0],
                endpoint=row[1],
                status=row[2],
                query_parameters=parameters,
                raw_xml=row[4],
                skipped_record_count=row[5],
                error=row[6],
            )
        except (TypeError, ValueError) as error:
            raise PropagationHistoryStorageError(
                "PSK Reporter query payload validation failed"
            ) from error

    def read_pskreporter(self, contact_id: UUID) -> PskReporterSummary | None:
        """Read one validated PSK Reporter outcome for restart-safe finalization."""
        try:
            with sqlite3.connect(self._database_path) as connection:
                row = connection.execute(
                    """
                    SELECT query_id, status, queried_at_utc, raw_response_json,
                           summary_json, last_error
                    FROM qso_pskreporter_summary
                    WHERE contact_id = ?
                    """,
                    (str(contact_id),),
                ).fetchone()
        except sqlite3.Error as error:
            raise PropagationHistoryStorageError("PSK Reporter summary read failed") from error
        if row is None:
            return None
        try:
            raw_response = None if row[3] is None else loads(row[3])
            summary = None if row[4] is None else loads(row[4])
            if raw_response is not None and not isinstance(raw_response, dict):
                raise TypeError("raw response must be an object")
            if summary is not None and not isinstance(summary, dict):
                raise TypeError("summary must be an object")
            return PskReporterSummary(
                contact_id=contact_id,
                query_id=row[0],
                status=row[1],
                queried_at_utc=row[2],
                raw_response_json=raw_response,
                summary_json=summary,
                last_error=row[5],
            )
        except (TypeError, ValueError) as error:
            raise PropagationHistoryStorageError(
                "PSK Reporter summary payload validation failed"
            ) from error

    def latest_collection_time(self, table: str, *, metric: IonosphereMetric | None = None) -> datetime | None:
        if table not in {"solar_observation", "kc2g_snapshot"}:
            raise ValueError("unsupported propagation observation table")
        query = f"SELECT MAX(collected_at_utc) FROM {table}"
        parameters: tuple[object, ...] = ()
        if metric is not None:
            if table != "kc2g_snapshot":
                raise ValueError("metric applies only to KC2G snapshots")
            query += " WHERE metric = ?"
            parameters = (metric.value,)
        try:
            with sqlite3.connect(self._database_path) as connection:
                row = connection.execute(query, parameters).fetchone()
        except sqlite3.Error as error:
            raise PropagationHistoryStorageError("propagation collection time read failed") from error
        if row is None or row[0] is None:
            return None
        return datetime.fromisoformat(str(row[0])).astimezone(UTC)

    def nearest_kc2g_snapshot(
        self,
        metric: IonosphereMetric,
        qso_time: datetime,
        max_age: timedelta = timedelta(minutes=90),
    ) -> Kc2gSnapshot | None:
        """Return the absolute closest snapshot, preferring earlier on an exact tie."""
        if qso_time.tzinfo is None or qso_time.utcoffset() is None:
            raise ValueError("qso_time must be timezone-aware")
        if max_age < timedelta(0):
            raise ValueError("max_age must not be negative")
        qso_utc = qso_time.astimezone(UTC)
        lower = _time(qso_utc - max_age)
        upper = _time(qso_utc + max_age)
        try:
            with sqlite3.connect(self._database_path) as connection:
                rows = connection.execute(
                    """
                    SELECT collected_at_utc
                    FROM kc2g_snapshot
                    WHERE metric = ? AND collected_at_utc BETWEEN ? AND ?
                    ORDER BY collected_at_utc ASC
                    """,
                    (metric.value, lower, upper),
                ).fetchall()
        except sqlite3.Error as error:
            raise PropagationHistoryStorageError("KC2G snapshot lookup failed") from error
        if not rows:
            return None
        candidates = tuple(datetime.fromisoformat(str(row[0])).astimezone(UTC) for row in rows)
        selected = min(candidates, key=lambda value: (abs(value - qso_utc), value))
        return self.read_kc2g(metric, selected)

    def read_weather(self, contact_id: UUID) -> tuple[WeatherObservation, ...]:
        try:
            with sqlite3.connect(self._database_path) as connection:
                rows = connection.execute(
                    """
                    SELECT role, provider_id, provider_name, attribution_text,
                           attribution_url, license_name, license_url, source_at_utc,
                           fetched_at_utc, latitude, longitude, condition,
                           temperature_c, relative_humidity_percent, payload_json
                    FROM weather_observation
                    WHERE contact_id = ?
                    ORDER BY role
                    """,
                    (str(contact_id),),
                ).fetchall()
        except sqlite3.Error as error:
            raise PropagationHistoryStorageError("weather observation read failed") from error
        try:
            return tuple(
                WeatherObservation(
                    contact_id=contact_id,
                    role=row[0],
                    provider_id=row[1],
                    provider_name=row[2],
                    attribution_text=row[3],
                    attribution_url=row[4],
                    license_name=row[5],
                    license_url=row[6],
                    source_at_utc=row[7],
                    fetched_at_utc=row[8],
                    latitude=row[9],
                    longitude=row[10],
                    condition=row[11],
                    temperature_c=row[12],
                    relative_humidity_percent=row[13],
                    payload_json=loads(row[14]),
                )
                for row in rows
            )
        except (TypeError, ValueError) as error:
            raise PropagationHistoryStorageError(
                "weather observation payload validation failed"
            ) from error

    def read_kc2g(
        self, metric: IonosphereMetric, collected_at_utc: datetime
    ) -> Kc2gSnapshot | None:
        try:
            with sqlite3.connect(self._database_path) as connection:
                row = connection.execute(
                    """
                    SELECT source_url, sha256, compression, snapshot_blob
                    FROM kc2g_snapshot
                    WHERE metric = ? AND collected_at_utc = ?
                    """,
                    (metric.value, _time(collected_at_utc)),
                ).fetchone()
        except sqlite3.Error as error:
            raise PropagationHistoryStorageError("KC2G snapshot read failed") from error
        if row is None:
            return None
        if row[2] != "gzip":
            raise PropagationHistoryStorageError("unsupported KC2G snapshot compression")
        try:
            raw = gzip.decompress(row[3])
        except (OSError, TypeError) as error:
            raise PropagationHistoryStorageError("KC2G snapshot decompression failed") from error
        if hashlib.sha256(raw).hexdigest() != row[1]:
            raise PropagationHistoryStorageError("KC2G snapshot checksum mismatch")
        try:
            geojson = loads(raw.decode("utf-8"))
            if not isinstance(geojson, dict):
                raise TypeError("KC2G snapshot must decode to an object")
            return Kc2gSnapshot(
                metric=metric,
                source_url=row[0],
                collected_at_utc=collected_at_utc,
                geojson=geojson,
            )
        except (UnicodeDecodeError, TypeError, ValueError) as error:
            raise PropagationHistoryStorageError("KC2G snapshot validation failed") from error

    def read_ionosphere(self, contact_id: UUID) -> IonosphereCorrelation | None:
        """Read and validate one stored QSO ionosphere correlation."""
        try:
            with sqlite3.connect(self._database_path) as connection:
                row = connection.execute(
                    """
                    SELECT captured_at_utc, muf_snapshot_at_utc,
                           fof2_snapshot_at_utc, payload_json
                    FROM qso_ionosphere
                    WHERE contact_id = ?
                    """,
                    (str(contact_id),),
                ).fetchone()
        except sqlite3.Error as error:
            raise PropagationHistoryStorageError("ionosphere correlation read failed") from error
        if row is None:
            return None
        try:
            payload = loads(row[3])
            if not isinstance(payload, dict):
                raise TypeError("ionosphere payload must be an object")
            return IonosphereCorrelation(
                contact_id=contact_id,
                captured_at_utc=row[0],
                muf_snapshot_at_utc=row[1],
                fof2_snapshot_at_utc=row[2],
                payload_json=payload,
            )
        except (TypeError, ValueError) as error:
            raise PropagationHistoryStorageError(
                "ionosphere correlation payload validation failed"
            ) from error

    def get_qso(self, contact_id: UUID) -> Contact | None:
        try:
            with sqlite3.connect(self._database_path) as connection:
                row = connection.execute(
                    "SELECT payload_json FROM qso_observation WHERE contact_id = ?",
                    (str(contact_id),),
                ).fetchone()
        except sqlite3.Error as error:
            raise PropagationHistoryStorageError("QSO observation read failed") from error
        if row is None:
            return None
        try:
            return Contact.model_validate_json(row[0])
        except (TypeError, ValueError) as error:
            raise PropagationHistoryStorageError(
                "QSO observation payload validation failed"
            ) from error

    def table_names(self) -> frozenset[str]:
        try:
            with sqlite3.connect(self._database_path) as connection:
                rows = connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
        except sqlite3.Error as error:
            raise PropagationHistoryStorageError("propagation table-name read failed") from error
        return frozenset(str(row[0]) for row in rows)

    def _execute(self, query: str, parameters: tuple[object, ...]) -> None:
        try:
            with sqlite3.connect(self._database_path) as connection:
                connection.execute(query, parameters)
                connection.commit()
        except sqlite3.Error as error:
            raise PropagationHistoryStorageError("propagation-history write failed") from error

    def _initialize(self) -> None:
        try:
            self._database_path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(self._database_path) as connection:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS propagation_schema_metadata (
                        singleton_id INTEGER PRIMARY KEY CHECK(singleton_id=1),
                        schema_version INTEGER NOT NULL
                    );
                    INSERT OR IGNORE INTO propagation_schema_metadata VALUES (1, 2);
                    CREATE TABLE IF NOT EXISTS solar_observation (
                        collected_at_utc TEXT PRIMARY KEY, source_url TEXT NOT NULL,
                        source_updated TEXT NOT NULL, payload_json TEXT NOT NULL,
                        raw_xml TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS kc2g_snapshot (
                        metric TEXT NOT NULL, collected_at_utc TEXT NOT NULL,
                        source_url TEXT NOT NULL, sha256 TEXT NOT NULL,
                        compression TEXT NOT NULL, snapshot_blob BLOB NOT NULL,
                        PRIMARY KEY(metric, collected_at_utc)
                    );
                    CREATE TABLE IF NOT EXISTS weather_observation (
                        contact_id TEXT NOT NULL, role TEXT NOT NULL,
                        provider_id TEXT NOT NULL, provider_name TEXT,
                        attribution_text TEXT, attribution_url TEXT,
                        license_name TEXT, license_url TEXT, source_at_utc TEXT,
                        fetched_at_utc TEXT NOT NULL, latitude REAL NOT NULL,
                        longitude REAL NOT NULL, condition TEXT, temperature_c REAL,
                        relative_humidity_percent REAL, payload_json TEXT NOT NULL,
                        PRIMARY KEY(contact_id, role)
                    );
                    CREATE TABLE IF NOT EXISTS qso_observation (
                        contact_id TEXT PRIMARY KEY, occurred_at_utc TEXT NOT NULL,
                        payload_json TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS qso_ionosphere (
                        contact_id TEXT PRIMARY KEY, captured_at_utc TEXT NOT NULL,
                        muf_snapshot_at_utc TEXT, fof2_snapshot_at_utc TEXT,
                        payload_json TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS qso_voacap_prediction (
                        contact_id TEXT PRIMARY KEY, captured_at_utc TEXT NOT NULL,
                        request_json TEXT NOT NULL, service_version TEXT NOT NULL,
                        response_json TEXT NOT NULL, actual_hour_muf_mhz REAL,
                        actual_hour_reliability REAL, actual_hour_rating TEXT,
                        actual_hour_snr_db REAL
                    );
                    CREATE TABLE IF NOT EXISTS pskreporter_query (
                        query_id TEXT PRIMARY KEY, queried_at_utc TEXT NOT NULL,
                        endpoint TEXT NOT NULL, status TEXT NOT NULL,
                        query_parameters_json TEXT NOT NULL, raw_xml TEXT,
                        skipped_record_count INTEGER NOT NULL, last_error TEXT
                    );
                    CREATE TABLE IF NOT EXISTS qso_pskreporter_summary (
                        contact_id TEXT PRIMARY KEY,
                        query_id TEXT REFERENCES pskreporter_query(query_id),
                        status TEXT NOT NULL,
                        queried_at_utc TEXT, raw_response_json TEXT,
                        summary_json TEXT, last_error TEXT
                    );
                    """
                )
                version = connection.execute(
                    "SELECT schema_version FROM propagation_schema_metadata WHERE singleton_id=1"
                ).fetchone()
                if version == (1,):
                    connection.execute(
                        "ALTER TABLE qso_pskreporter_summary "
                        "ADD COLUMN query_id TEXT REFERENCES pskreporter_query(query_id)"
                    )
                    connection.execute(
                        "UPDATE propagation_schema_metadata SET schema_version = 2 "
                        "WHERE singleton_id = 1"
                    )
                    version = (2,)
                if version != (PROPAGATION_HISTORY_SCHEMA_VERSION,):
                    raise PropagationHistoryStorageError("unsupported propagation schema version")
                connection.commit()
        except PropagationHistoryStorageError:
            raise
        except (OSError, sqlite3.Error) as error:
            raise PropagationHistoryStorageError("propagation-history initialization failed") from error


def _json(value: object) -> str:
    return dumps(value, sort_keys=True, separators=(",", ":"))


def _time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def decode_kc2g_blob(blob: bytes) -> dict[str, Any]:
    """Decode one repository-format compressed snapshot for analysis/tests."""
    value = loads(gzip.decompress(blob).decode("utf-8"))
    if not isinstance(value, dict):
        raise TypeError("KC2G snapshot must decode to an object")
    return value
