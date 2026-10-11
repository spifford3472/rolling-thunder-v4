"""Append-only, optional Forge-side VOACAP forecast archive (no provider I/O)."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from rolling_thunder.voacap_forecast_trends import ForecastPoint


class ForecastConflict(ValueError):
    """A previously captured forecast identity was submitted with new content."""


@dataclass(frozen=True)
class ArchivedForecast:
    provider: str
    point: ForecastPoint
    station_grid6: str
    target_grid: str
    target_uncertainty: str
    model_inputs_hash: str
    collected_at_utc: datetime
    status: str = "available"

    def __post_init__(self) -> None:
        if self.collected_at_utc.tzinfo is None or self.collected_at_utc.utcoffset() is None:
            raise ValueError("collected_at_utc must be timezone-aware")
        if len(self.station_grid6) != 6:
            raise ValueError("station grid must contain six Maidenhead characters")
        if not self.provider or not self.model_inputs_hash:
            raise ValueError("provider and model input hash are required")

    @property
    def identity(self) -> str:
        """Stable event identity: capture revisits dedupe; forecast revisions append."""
        p = self.point
        fields = (
            self.provider, p.model_version, p.path_identity, p.equipment_identity,
            p.band, p.issued_at_utc.astimezone(UTC).isoformat(),
            p.valid_at_utc.astimezone(UTC).isoformat(),
            self.station_grid6, self.target_grid, self.model_inputs_hash,
        )
        return hashlib.sha256(json.dumps(fields, separators=(",", ":")).encode()).hexdigest()

    def serialized(self) -> str:
        data = asdict(self)
        point = data["point"]
        point["issued_at_utc"] = self.point.issued_at_utc.astimezone(UTC).isoformat()
        point["valid_at_utc"] = self.point.valid_at_utc.astimezone(UTC).isoformat()
        data["collected_at_utc"] = self.collected_at_utc.astimezone(UTC).isoformat()
        return json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False)


class ForecastArchive:
    """Opt-in archive for a dedicated non-production SQLite file.

    The writer is an API to be composed into a future bounded Forge scheduler.
    It does not query external providers or change installed service lifecycle.
    """

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path
        with sqlite3.connect(path) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS voacap_forecast_event ("
                "event_id TEXT PRIMARY KEY, payload_sha256 TEXT NOT NULL,"
                "provider TEXT NOT NULL, model_version TEXT NOT NULL,"
                "path_identity TEXT NOT NULL, band TEXT NOT NULL,"
                "issued_at_utc TEXT NOT NULL, valid_at_utc TEXT NOT NULL,"
                "collected_at_utc TEXT NOT NULL, is_forward_forecast INTEGER NOT NULL,"
                "payload_json TEXT NOT NULL)"
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS voacap_forecast_path_valid "
                "ON voacap_forecast_event(path_identity,band,valid_at_utc)"
            )

    def append(self, event: ArchivedForecast) -> bool:
        """True if added; False if exact replay; reject identity payload conflicts."""
        payload = event.serialized()
        if len(payload) > 16384:
            raise ValueError("forecast payload exceeds storage limit")
        digest = hashlib.sha256(payload.encode()).hexdigest()
        p = event.point
        with sqlite3.connect(self._path, timeout=10) as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute(
                "SELECT payload_sha256 FROM voacap_forecast_event WHERE event_id=?",
                (event.identity,),
            ).fetchone()
            if previous:
                if previous[0] != digest:
                    raise ForecastConflict("forecast identity changed under replay")
                return False
            db.execute(
                "INSERT INTO voacap_forecast_event VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    event.identity, digest, event.provider, p.model_version,
                    p.path_identity, p.band,
                    p.issued_at_utc.astimezone(UTC).isoformat(),
                    p.valid_at_utc.astimezone(UTC).isoformat(),
                    event.collected_at_utc.astimezone(UTC).isoformat(),
                    int(p.issued_at_utc < p.valid_at_utc), payload,
                ),
            )
        return True

    def count(self) -> int:
        with sqlite3.connect(
            f"file:{self._path.as_posix()}?mode=ro", uri=True
        ) as db:
            row = db.execute("SELECT count(*) FROM voacap_forecast_event").fetchone()
            assert row is not None
            return int(row[0])
