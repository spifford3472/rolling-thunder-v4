"""Dedicated SQLite persistence for complete canonical Forge spot snapshots."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Protocol

from pydantic import Field, ValidationError, field_validator, model_validator

from rolling_thunder.domain import DomainModel, Frequency, RadioMode
from rolling_thunder.forge_spot_provider import ForgeProviderSlice
from rolling_thunder.spot_domain import (
    DxSpotIdentity,
    PotaSpotIdentity,
    PotaSpotMetadata,
    SpotIdentity,
    SpotProvider,
    SpotRecord,
    SpotSnapshot,
    SpotSourceMetadataItem,
    canonicalize_spots,
)

_FORGE_SCHEMA_VERSION: Final = 1
_MAX_ERROR_LENGTH: Final = 500


class ForgeSnapshotStorageError(Exception):
    """Raised when the dedicated Forge snapshot store cannot be used safely."""


class ForgeStoredSnapshot(DomainModel):
    """One durable aggregate snapshot and its complete provider slices."""

    revision: int = Field(ge=0)
    snapshot: SpotSnapshot
    provider_slices: tuple[ForgeProviderSlice, ...] = ()

    @field_validator("provider_slices")
    @classmethod
    def normalize_provider_slices(
        cls,
        value: tuple[ForgeProviderSlice, ...],
    ) -> tuple[ForgeProviderSlice, ...]:
        """Order provider slices and reject duplicate provider families."""
        ordered = tuple(sorted(value, key=lambda item: item.provider.value))
        providers = [item.provider for item in ordered]
        if len(providers) != len(set(providers)):
            raise ValueError("stored snapshot provider slices must be unique")
        return ordered

    @model_validator(mode="after")
    def validate_complete_snapshot(self) -> ForgeStoredSnapshot:
        """Require provider slices to compose the complete canonical snapshot."""
        combined = canonicalize_spots(
            spot
            for provider_slice in self.provider_slices
            for spot in provider_slice.spots
        )
        if combined != self.snapshot.spots:
            raise ValueError("provider slices do not compose the stored aggregate snapshot")
        return self


class ForgeSnapshotRepository(Protocol):
    """Persistence boundary used by the Forge aggregation core."""

    def load(self) -> ForgeStoredSnapshot | None:
        """Load and revalidate the latest durable snapshot, when present."""
        ...

    def replace(
        self,
        snapshot: SpotSnapshot,
        provider_slices: tuple[ForgeProviderSlice, ...],
    ) -> ForgeStoredSnapshot:
        """Transactionally persist a complete snapshot and increment its revision."""
        ...


class SqliteForgeSnapshotRepository:
    """Store one complete Forge snapshot in a dedicated SQLite database."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        self._initialize()

    def load(self) -> ForgeStoredSnapshot | None:
        """Load all metadata and rows, then reconstruct the canonical snapshot."""
        try:
            with self._connect() as connection:
                metadata = connection.execute(
                    """
                    SELECT revision, generated_at
                    FROM forge_snapshot_metadata
                    WHERE singleton_id = 1
                    """
                ).fetchone()
                if metadata is None:
                    return None

                provider_rows = connection.execute(
                    """
                    SELECT provider, fetched_at
                    FROM forge_provider_slices
                    ORDER BY provider
                    """
                ).fetchall()
                spot_rows = connection.execute(
                    """
                    SELECT
                        position,
                        provider,
                        stable_key,
                        callsign,
                        operator_name,
                        grid,
                        frequency_hz,
                        mode,
                        display_mode,
                        spotted_at,
                        source_metadata_json,
                        pota_park_reference,
                        pota_park_name,
                        pota_location_code,
                        pota_latitude,
                        pota_longitude
                    FROM forge_spots
                    ORDER BY position
                    """
                ).fetchall()
        except sqlite3.Error as error:
            raise ForgeSnapshotStorageError(
                f"Forge snapshot database could not be read: {self._database_path}: {error}"
            ) from error

        try:
            revision = self._require_int(metadata["revision"], "revision")
            generated_at = self._parse_timestamp(metadata["generated_at"])
            spots = tuple(self._spot_from_row(row) for row in spot_rows)
            snapshot = SpotSnapshot(
                generated_at=generated_at,
                spots=spots,
            )
            slices = self._provider_slices_from_rows(provider_rows, spots)
            return ForgeStoredSnapshot(
                revision=revision,
                snapshot=snapshot,
                provider_slices=slices,
            )
        except (
            KeyError,
            TypeError,
            ValueError,
            ValidationError,
            json.JSONDecodeError,
        ) as error:
            raise ForgeSnapshotStorageError(
                f"Forge snapshot database contains invalid data: {self._database_path}: "
                f"{self._bounded_error(error)}"
            ) from error

    def replace(
        self,
        snapshot: SpotSnapshot,
        provider_slices: tuple[ForgeProviderSlice, ...],
    ) -> ForgeStoredSnapshot:
        """Persist all rows and metadata before returning the new active revision."""
        validated = ForgeStoredSnapshot(
            revision=0,
            snapshot=snapshot,
            provider_slices=provider_slices,
        )
        rows = tuple(self._spot_row(position, spot) for position, spot in enumerate(snapshot.spots))

        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                current = connection.execute(
                    """
                    SELECT revision
                    FROM forge_snapshot_metadata
                    WHERE singleton_id = 1
                    """
                ).fetchone()
                revision = 1 if current is None else self._require_int(current["revision"], "revision") + 1

                connection.execute("DELETE FROM forge_spots")
                connection.execute("DELETE FROM forge_provider_slices")
                connection.execute("DELETE FROM forge_snapshot_metadata")
                connection.execute(
                    """
                    INSERT INTO forge_snapshot_metadata (
                        singleton_id,
                        revision,
                        generated_at
                    )
                    VALUES (1, ?, ?)
                    """,
                    (revision, self._timestamp_text(snapshot.generated_at)),
                )
                connection.executemany(
                    """
                    INSERT INTO forge_provider_slices (provider, fetched_at)
                    VALUES (?, ?)
                    """,
                    (
                        (
                            provider_slice.provider.value,
                            self._timestamp_text(provider_slice.fetched_at),
                        )
                        for provider_slice in validated.provider_slices
                    ),
                )
                if rows:
                    connection.executemany(
                        """
                        INSERT INTO forge_spots (
                            position,
                            provider,
                            stable_key,
                            callsign,
                            operator_name,
                            grid,
                            frequency_hz,
                            mode,
                            display_mode,
                            spotted_at,
                            source_metadata_json,
                            pota_park_reference,
                            pota_park_name,
                            pota_location_code,
                            pota_latitude,
                            pota_longitude
                        )
                        VALUES (
                            :position,
                            :provider,
                            :stable_key,
                            :callsign,
                            :operator_name,
                            :grid,
                            :frequency_hz,
                            :mode,
                            :display_mode,
                            :spotted_at,
                            :source_metadata_json,
                            :pota_park_reference,
                            :pota_park_name,
                            :pota_location_code,
                            :pota_latitude,
                            :pota_longitude
                        )
                        """,
                        rows,
                    )
                connection.commit()
        except (sqlite3.Error, TypeError, ValueError) as error:
            raise ForgeSnapshotStorageError(
                f"Forge snapshot database could not be replaced: {self._database_path}: "
                f"{self._bounded_error(error)}"
            ) from error

        return validated.model_copy(update={"revision": revision})

    def _initialize(self) -> None:
        try:
            self._database_path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as connection:
                existing_tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    ).fetchall()
                }
                if (
                    "forge_schema_metadata" not in existing_tables
                    and {"schema_metadata", "contacts"} & existing_tables
                ):
                    raise ForgeSnapshotStorageError(
                        "Refusing to initialize Forge snapshots in a Rolling Thunder "
                        "application database. Configure a separate Forge database path."
                    )

                connection.execute("BEGIN")
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS forge_schema_metadata (
                        singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
                        schema_version INTEGER NOT NULL CHECK (schema_version >= 1)
                    )
                    """
                )
                version_row = connection.execute(
                    """
                    SELECT schema_version
                    FROM forge_schema_metadata
                    WHERE singleton_id = 1
                    """
                ).fetchone()
                if version_row is None:
                    connection.execute(
                        """
                        INSERT INTO forge_schema_metadata (singleton_id, schema_version)
                        VALUES (1, ?)
                        """,
                        (_FORGE_SCHEMA_VERSION,),
                    )
                elif version_row[0] != _FORGE_SCHEMA_VERSION:
                    raise ForgeSnapshotStorageError(
                        "Unsupported Forge snapshot schema version: "
                        f"{version_row[0]!r}; expected {_FORGE_SCHEMA_VERSION}."
                    )

                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS forge_snapshot_metadata (
                        singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
                        revision INTEGER NOT NULL CHECK (revision >= 1),
                        generated_at TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS forge_provider_slices (
                        provider TEXT PRIMARY KEY CHECK (provider IN ('pota', 'dx')),
                        fetched_at TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS forge_spots (
                        position INTEGER PRIMARY KEY CHECK (position >= 0),
                        provider TEXT NOT NULL,
                        stable_key TEXT NOT NULL UNIQUE,
                        callsign TEXT NOT NULL,
                        operator_name TEXT,
                        grid TEXT,
                        frequency_hz INTEGER NOT NULL CHECK (frequency_hz > 0),
                        mode TEXT NOT NULL CHECK (mode IN ('AM', 'CW', 'DATA', 'FM', 'LSB', 'USB')),
                        display_mode TEXT NOT NULL,
                        spotted_at TEXT NOT NULL,
                        source_metadata_json TEXT NOT NULL,
                        pota_park_reference TEXT,
                        pota_park_name TEXT,
                        pota_location_code TEXT,
                        pota_latitude REAL,
                        pota_longitude REAL,
                        FOREIGN KEY (provider)
                            REFERENCES forge_provider_slices (provider)
                            ON DELETE CASCADE
                    )
                    """
                )
                connection.commit()
        except ForgeSnapshotStorageError:
            raise
        except (OSError, sqlite3.Error) as error:
            raise ForgeSnapshotStorageError(
                f"Forge snapshot database could not be initialized: "
                f"{self._database_path}: {self._bounded_error(error)}"
            ) from error

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()
        if foreign_keys is None or foreign_keys[0] != 1:
            connection.close()
            raise ForgeSnapshotStorageError(
                f"SQLite foreign-key enforcement could not be enabled: {self._database_path}"
            )
        return connection

    @classmethod
    def _provider_slices_from_rows(
        cls,
        provider_rows: Iterable[sqlite3.Row],
        spots: tuple[SpotRecord, ...],
    ) -> tuple[ForgeProviderSlice, ...]:
        slices: list[ForgeProviderSlice] = []
        for row in provider_rows:
            provider = SpotProvider(cls._require_text(row["provider"], "provider"))
            slices.append(
                ForgeProviderSlice(
                    provider=provider,
                    fetched_at=cls._parse_timestamp(row["fetched_at"]),
                    spots=tuple(spot for spot in spots if spot.provider is provider),
                )
            )
        return tuple(slices)

    @classmethod
    def _spot_from_row(cls, row: sqlite3.Row) -> SpotRecord:
        provider = SpotProvider(cls._require_text(row["provider"], "provider"))
        frequency = Frequency(hz=cls._require_int(row["frequency_hz"], "frequency_hz"))
        callsign = cls._require_text(row["callsign"], "callsign")
        park_reference = cls._optional_text(row["pota_park_reference"])

        identity: SpotIdentity
        if provider is SpotProvider.POTA:
            if park_reference is None:
                raise ValueError("stored POTA spot is missing its park reference")
            legacy_key = f"pota:{park_reference}:{frequency.hz}"
            identity = PotaSpotIdentity(
                callsign=None if row["stable_key"] == legacy_key else callsign,
                park_reference=park_reference,
                frequency=frequency,
            )
            pota = PotaSpotMetadata(
                park_reference=park_reference,
                park_name=cls._optional_text(row["pota_park_name"]),
                location_code=cls._optional_text(row["pota_location_code"]),
                latitude=cls._optional_float(row["pota_latitude"]),
                longitude=cls._optional_float(row["pota_longitude"]),
            )
        else:
            identity = DxSpotIdentity(callsign=callsign, frequency=frequency)
            pota = None

        spot = SpotRecord(
            identity=identity,
            callsign=callsign,
            operator_name=cls._optional_text(row["operator_name"]),
            grid=cls._optional_text(row["grid"]),
            frequency=frequency,
            mode=RadioMode(cls._require_text(row["mode"], "mode")),
            display_mode=cls._require_text(row["display_mode"], "display_mode"),
            spotted_at=cls._parse_timestamp(row["spotted_at"]),
            source_metadata=cls._parse_source_metadata(row["source_metadata_json"]),
            pota=pota,
        )
        stable_key = cls._require_text(row["stable_key"], "stable_key")
        legacy_stable_key = (
            f"pota:{spot.pota.park_reference}:{spot.frequency.hz}"
            if spot.provider is SpotProvider.POTA and spot.pota is not None
            else None
        )
        if stable_key not in {spot.stable_key, legacy_stable_key}:
            raise ValueError("stored spot stable identity does not match its fields")
        return spot

    @classmethod
    def _spot_row(cls, position: int, spot: SpotRecord) -> dict[str, object]:
        pota = spot.pota
        return {
            "position": position,
            "provider": spot.provider.value,
            "stable_key": spot.stable_key,
            "callsign": str(spot.callsign),
            "operator_name": spot.operator_name,
            "grid": str(spot.grid) if spot.grid is not None else None,
            "frequency_hz": spot.frequency.hz,
            "mode": spot.mode.value,
            "display_mode": spot.display_mode,
            "spotted_at": cls._timestamp_text(spot.spotted_at),
            "source_metadata_json": json.dumps(
                [item.model_dump(mode="json") for item in spot.source_metadata],
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ),
            "pota_park_reference": str(pota.park_reference) if pota is not None else None,
            "pota_park_name": pota.park_name if pota is not None else None,
            "pota_location_code": pota.location_code if pota is not None else None,
            "pota_latitude": pota.latitude if pota is not None else None,
            "pota_longitude": pota.longitude if pota is not None else None,
        }

    @classmethod
    def _parse_source_metadata(cls, value: object) -> tuple[SpotSourceMetadataItem, ...]:
        text = cls._require_text(value, "source_metadata_json")
        payload = json.loads(text)
        if not isinstance(payload, list):
            raise TypeError("source metadata must decode to a JSON array")
        return tuple(SpotSourceMetadataItem.model_validate(item) for item in payload)

    @staticmethod
    def _timestamp_text(value: datetime) -> str:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Forge snapshot timestamps must be timezone-aware")
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")

    @classmethod
    def _parse_timestamp(cls, value: object) -> datetime:
        text = cls._require_text(value, "timestamp").replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("stored Forge timestamp must include timezone information")
        return parsed.astimezone(UTC)

    @staticmethod
    def _require_text(value: object, field_name: str) -> str:
        if not isinstance(value, str):
            raise TypeError(f"{field_name} must be text")
        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{field_name} must not be blank")
        return normalized

    @staticmethod
    def _optional_text(value: object) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise TypeError("optional stored text must be text or null")
        normalized = value.strip()
        return normalized or None

    @staticmethod
    def _require_int(value: object, field_name: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{field_name} must be an integer")
        return value

    @staticmethod
    def _optional_float(value: object) -> float | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("stored coordinate must be numeric or null")
        return float(value)

    @staticmethod
    def _bounded_error(error: BaseException) -> str:
        text = str(error).strip() or error.__class__.__name__
        return text[:_MAX_ERROR_LENGTH]
