"""Offline POTA park catalog import and query boundary."""

from __future__ import annotations

import csv
import hashlib
import os
import sqlite3
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

CATALOG_SCHEMA_VERSION: Final = 2

_HEADER_ALIASES: Final[dict[str, tuple[str, ...]]] = {
    "reference": ("reference", "parkreference", "park_reference"),
    "name": ("name", "parkname", "park_name"),
    "latitude": ("latitude", "lat"),
    "longitude": ("longitude", "lon", "lng"),
    "grid": ("grid", "maidenhead", "locator"),
    "locations": ("locationdesc", "location_desc", "locations", "location"),
    "website": ("website", "url"),
    "notes": ("notes", "note"),
    "status": ("status", "active"),
    "park_type": ("parktype", "parktypedesc", "park_type", "type"),
}


class PotaCatalogImportError(Exception):
    """Raised when a park catalog cannot be validated and promoted."""


@dataclass(frozen=True)
class PotaCatalogImportResult:
    """Summary of one successful atomic catalog replacement."""

    database_path: Path
    source_paths: tuple[Path, ...]
    source_sha256: str
    source_version: str | None
    imported_at: datetime
    park_count: int

    @property
    def source_path(self) -> Path:
        """Compatibility accessor for callers importing exactly one source."""
        return self.source_paths[0]


def _normalized_headers(fieldnames: Sequence[str] | None) -> dict[str, str]:
    if not fieldnames:
        raise PotaCatalogImportError("POTA catalog CSV has no header row.")
    available = {name.strip().lower(): name for name in fieldnames}
    mapped: dict[str, str] = {}
    for target, aliases in _HEADER_ALIASES.items():
        for alias in aliases:
            original = available.get(alias.lower())
            if original is not None:
                mapped[target] = original
                break
    required = {"reference", "name", "latitude", "longitude", "locations"}
    missing = sorted(required - mapped.keys())
    if missing:
        raise PotaCatalogImportError(
            "POTA catalog CSV is missing required column(s): " + ", ".join(missing)
        )
    return mapped


def _status(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "active", "yes"}:
        return "active"
    if normalized in {"0", "false", "inactive", "no"}:
        return "inactive"
    return normalized or "unknown"


def _parse_locations(value: str) -> tuple[str, ...]:
    locations = tuple(
        item.strip().upper()
        for item in value.replace(";", ",").split(",")
        if item.strip()
    )
    if not locations:
        raise ValueError("location is empty")
    return locations


def _optional(row: dict[str, str | None], headers: dict[str, str], field: str) -> str | None:
    header = headers.get(field)
    if header is None:
        return None
    value = row.get(header)
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _source_digest(source_paths: Sequence[Path]) -> str:
    digest = hashlib.sha256()
    for source_path in source_paths:
        data = source_path.read_bytes()
        digest.update(source_path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(data).digest())
    return digest.hexdigest()


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        PRAGMA foreign_keys = ON;
        CREATE TABLE catalog_metadata (
            singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
            schema_version INTEGER NOT NULL,
            source_name TEXT NOT NULL,
            source_sha256 TEXT NOT NULL,
            source_file_count INTEGER NOT NULL CHECK (source_file_count > 0),
            source_version TEXT,
            imported_at TEXT NOT NULL,
            park_count INTEGER NOT NULL CHECK (park_count >= 0)
        );
        CREATE TABLE parks (
            reference TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            program TEXT NOT NULL,
            status TEXT NOT NULL,
            park_type TEXT,
            latitude REAL NOT NULL CHECK (latitude BETWEEN -90 AND 90),
            longitude REAL NOT NULL CHECK (longitude BETWEEN -180 AND 180),
            grid TEXT,
            website TEXT,
            notes TEXT
        );
        CREATE TABLE park_locations (
            park_reference TEXT NOT NULL,
            location_code TEXT NOT NULL,
            PRIMARY KEY (park_reference, location_code),
            FOREIGN KEY (park_reference) REFERENCES parks(reference) ON DELETE CASCADE
        );
        CREATE INDEX parks_program_index ON parks(program, reference);
        CREATE INDEX parks_latitude_index ON parks(latitude);
        CREATE INDEX parks_longitude_index ON parks(longitude);
        CREATE INDEX parks_grid_index ON parks(grid);
        CREATE INDEX park_locations_code_index
            ON park_locations(location_code, park_reference);
        """
    )


def import_pota_catalog_csvs(
    source_paths: Sequence[Path],
    database_path: Path,
    *,
    source_version: str | None = None,
    program: str = "US",
    imported_at: datetime | None = None,
) -> PotaCatalogImportResult:
    """Validate CSV files into staging and atomically replace the live catalog."""

    resolved_sources = tuple(
        sorted(
            (path.expanduser().resolve() for path in source_paths),
            key=lambda path: str(path),
        )
    )
    if not resolved_sources:
        raise PotaCatalogImportError("At least one POTA catalog CSV is required.")
    for source_path in resolved_sources:
        if not source_path.is_file():
            raise PotaCatalogImportError(
                f"POTA catalog source does not exist: {source_path}"
            )

    database_path = database_path.expanduser().resolve()
    requested_program = program.strip().upper()
    if not requested_program:
        raise PotaCatalogImportError("program must not be empty")
    when = imported_at or datetime.now(UTC)
    if when.tzinfo is None:
        raise PotaCatalogImportError("imported_at must be timezone-aware")

    try:
        digest = _source_digest(resolved_sources)
    except OSError as error:
        raise PotaCatalogImportError(f"POTA catalog source read failed: {error}") from error

    database_path.parent.mkdir(parents=True, exist_ok=True)
    fd, staging_name = tempfile.mkstemp(
        prefix=f".{database_path.name}.",
        suffix=".staging",
        dir=database_path.parent,
    )
    os.close(fd)
    staging_path = Path(staging_name)

    try:
        with sqlite3.connect(staging_path) as connection:
            _create_schema(connection)
            park_count = 0
            for source_path in resolved_sources:
                try:
                    handle = source_path.open("r", encoding="utf-8-sig", newline="")
                except OSError as error:
                    raise PotaCatalogImportError(
                        f"{source_path.name}: cannot open source: {error}"
                    ) from error
                with handle:
                    reader = csv.DictReader(handle)
                    try:
                        headers = _normalized_headers(reader.fieldnames)
                    except PotaCatalogImportError as error:
                        raise PotaCatalogImportError(
                            f"{source_path.name}: {error}"
                        ) from error
                    for line_number, row in enumerate(reader, start=2):
                        try:
                            reference = row[headers["reference"]].strip().upper()
                            name = row[headers["name"]].strip()
                            latitude = float(row[headers["latitude"]])
                            longitude = float(row[headers["longitude"]])
                            locations = _parse_locations(row[headers["locations"]])
                            if not reference or "-" not in reference:
                                raise ValueError("invalid park reference")
                            if not name:
                                raise ValueError("park name is empty")
                            if not -90 <= latitude <= 90:
                                raise ValueError("latitude is outside -90..90")
                            if not -180 <= longitude <= 180:
                                raise ValueError("longitude is outside -180..180")
                            record_program = reference.split("-", 1)[0]
                            if record_program != requested_program:
                                continue
                            status = _status(
                                row.get(headers.get("status", ""), "") or "unknown"
                            )
                            park_type = _optional(row, headers, "park_type")
                            grid = _optional(row, headers, "grid")
                            website = _optional(row, headers, "website")
                            notes = _optional(row, headers, "notes")
                            connection.execute(
                                """
                                INSERT INTO parks (
                                    reference, name, program, status, park_type,
                                    latitude, longitude, grid, website, notes
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                """,
                                (
                                    reference,
                                    name,
                                    record_program,
                                    status,
                                    park_type,
                                    latitude,
                                    longitude,
                                    grid,
                                    website,
                                    notes,
                                ),
                            )
                            connection.executemany(
                                """
                                INSERT INTO park_locations (
                                    park_reference, location_code
                                ) VALUES (?, ?)
                                """,
                                ((reference, location) for location in locations),
                            )
                            park_count += 1
                        except (
                            KeyError,
                            TypeError,
                            ValueError,
                            sqlite3.IntegrityError,
                        ) as error:
                            raise PotaCatalogImportError(
                                f"{source_path.name}: invalid row {line_number}: {error}"
                            ) from error

            if park_count == 0:
                raise PotaCatalogImportError(
                    f"POTA catalog contains no {requested_program} park records."
                )

            source_name = (
                resolved_sources[0].name
                if len(resolved_sources) == 1
                else f"{len(resolved_sources)} CSV files"
            )
            connection.execute(
                """
                INSERT INTO catalog_metadata (
                    singleton_id, schema_version, source_name, source_sha256,
                    source_file_count, source_version, imported_at, park_count
                ) VALUES (1, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    CATALOG_SCHEMA_VERSION,
                    source_name,
                    digest,
                    len(resolved_sources),
                    source_version,
                    when.astimezone(UTC).isoformat().replace("+00:00", "Z"),
                    park_count,
                ),
            )
            connection.commit()

        os.replace(staging_path, database_path)
    except PotaCatalogImportError:
        raise
    except (OSError, sqlite3.Error) as error:
        raise PotaCatalogImportError(f"POTA catalog import failed: {error}") from error
    finally:
        staging_path.unlink(missing_ok=True)

    return PotaCatalogImportResult(
        database_path=database_path,
        source_paths=resolved_sources,
        source_sha256=digest,
        source_version=source_version,
        imported_at=when,
        park_count=park_count,
    )


def import_pota_catalog_csv(
    source_path: Path,
    database_path: Path,
    *,
    source_version: str | None = None,
    program: str = "US",
    imported_at: datetime | None = None,
) -> PotaCatalogImportResult:
    """Compatibility wrapper for importing one POTA CSV."""

    return import_pota_catalog_csvs(
        (source_path,),
        database_path,
        source_version=source_version,
        program=program,
        imported_at=imported_at,
    )
