"""Independent append-only traffic-analysis decisions and read-only projection.

No raw message text, sender identity, token, RF data, broker cursor, location
trail or private messages are persisted. Does not modify the existing traffic
ledger or acknowledge any broker message.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from rolling_thunder.meshcore_traffic_relevance import TrafficRelevanceDecision

_MAX_ROWS = 250_000


class TrafficAssessmentError(ValueError):
    """Fail-closed input, integrity or storage error."""


@dataclass(frozen=True, slots=True)
class PersistedAssessment:
    """Immutable, non-notifying analysis projection."""

    message_id: int
    evaluated_at: str
    relevance: str
    confidence: str
    reason: str
    source: str | None
    distance_m: float | None
    digest: str


class TrafficAssessmentRepository:
    """Separate schema-1 audit store, never the durable broker/worker ledger."""

    def __init__(self, path: Path, *, create: bool = False) -> None:
        self._path = path
        if create:
            if path.parent.is_symlink():
                raise TrafficAssessmentError("Unsafe directory")
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if stat.S_IMODE(path.parent.stat().st_mode) & 0o077:
                raise TrafficAssessmentError("Unsafe directory mode")
            if not path.exists():
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
                os.close(fd)
            self._check_file()
            with sqlite3.connect(path) as db:
                db.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS assessment_schema(
                        version INTEGER PRIMARY KEY CHECK(version=1)
                    );
                    INSERT OR IGNORE INTO assessment_schema VALUES (1);
                    CREATE TABLE IF NOT EXISTS assessments(
                        message_id INTEGER NOT NULL CHECK(message_id>0),
                        evaluated_at TEXT NOT NULL,
                        relevance TEXT NOT NULL,
                        confidence TEXT NOT NULL,
                        reason TEXT NOT NULL,
                        source TEXT,
                        distance_m REAL,
                        digest TEXT NOT NULL,
                        PRIMARY KEY(message_id, evaluated_at)
                    );
                    """
                )
        self._verify()

    def _check_file(self) -> None:
        if (
            self._path.is_symlink()
            or not self._path.is_file()
            or stat.S_IMODE(self._path.stat().st_mode) & 0o077
            or self._path.stat().st_uid != os.geteuid()
        ):
            raise TrafficAssessmentError("Unsafe analysis database")

    def _readonly(self) -> sqlite3.Connection:
        self._check_file()
        db = sqlite3.connect(
            f"file:{self._path.resolve().as_posix()}?mode=ro", uri=True, timeout=1.0
        )
        db.execute("PRAGMA query_only=ON")
        return db

    def _verify(self) -> None:
        with self._readonly() as db:
            if db.execute("SELECT version FROM assessment_schema").fetchall() != [(1,)]:
                raise TrafficAssessmentError("Unknown assessment schema")
            if db.execute("PRAGMA quick_check").fetchone() != ("ok",):
                raise TrafficAssessmentError("Corrupt assessment database")

    def record(
        self, message_id: int, decision: TrafficRelevanceDecision, *, evaluated_at: datetime
    ) -> bool:
        """Write a single immutable result; changed replay fails closed."""

        if type(message_id) is not int or message_id < 1:
            raise TrafficAssessmentError("Invalid message ID")
        if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
            raise TrafficAssessmentError("Invalid evaluation time")
        if decision.driver_alert_permitted or decision.is_verified_incident:
            raise TrafficAssessmentError("Active or verified incident not authorized")
        if (
            len(decision.reason) > 96
            or not decision.reason.isascii()
            or not decision.reason.replace("_", "").isalnum()
            or (
                decision.verified_geocode_source is not None
                and (
                    len(decision.verified_geocode_source) > 64
                    or not decision.verified_geocode_source.isascii()
                )
            )
        ):
            raise TrafficAssessmentError("Unsafe assessment metadata")
        fields = (
            message_id,
            evaluated_at.astimezone(UTC).isoformat(),
            decision.relevance.value,
            decision.confidence.value,
            decision.reason,
            decision.verified_geocode_source,
            decision.distance_m,
        )
        canonical = json.dumps(fields, separators=(",", ":"), allow_nan=False)
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        with sqlite3.connect(self._path, timeout=3) as db:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            old = db.execute(
                "SELECT digest FROM assessments WHERE message_id=? AND evaluated_at=?",
                (message_id, fields[1]),
            ).fetchone()
            if old is not None:
                if old[0] != digest:
                    raise TrafficAssessmentError("Conflicting analysis replay")
                return False
            if db.execute("SELECT COUNT(*) FROM assessments").fetchone()[0] >= _MAX_ROWS:
                raise TrafficAssessmentError("Assessment store full")
            db.execute("INSERT INTO assessments VALUES (?,?,?,?,?,?,?,?)", (*fields, digest))
        return True

    def recent(self, *, limit: int = 50) -> tuple[PersistedAssessment, ...]:
        """Bounded, query-only read; cannot expose original report payload."""

        if type(limit) is not int or not 1 <= limit <= 100:
            raise TrafficAssessmentError("Invalid query bound")
        with self._readonly() as db:
            rows = db.execute(
                "SELECT message_id,evaluated_at,relevance,confidence,reason,"
                "source,distance_m,digest FROM assessments "
                "ORDER BY evaluated_at DESC, message_id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return tuple(PersistedAssessment(*row) for row in rows)

    def counts(self) -> dict[str, int]:
        """Provider-free aggregate health for any future authorized reader."""

        with self._readonly() as db:
            rows = db.execute(
                "SELECT relevance,COUNT(*) FROM assessments GROUP BY relevance"
            ).fetchall()
        return {str(label): int(count) for label, count in rows}
