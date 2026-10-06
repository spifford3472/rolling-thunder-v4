"""SQLite persistence for the Pi's latest valid Forge shared-spot snapshot."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from rolling_thunder.domain import Frequency, RadioMode
from rolling_thunder.forge_client import (
    ForgeRemoteProviderHealth,
    ForgeRemoteProviderStatus,
    ForgeSpotClientResult,
)
from rolling_thunder.spot_domain import (
    DxSpotIdentity,
    PotaSpotIdentity,
    PotaSpotMetadata,
    SpotProvider,
    SpotRecord,
    SpotSnapshot,
    SpotSourceMetadataItem,
)
from rolling_thunder.storage import StorageError, initialize_database


class ForgeSpotCacheRepository:
    """Transactionally replace and load one complete Pi-side Forge snapshot."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        initialize_database(database_path)

    def replace(self, result: ForgeSpotClientResult) -> None:
        """Persist a complete validated Forge result in one SQLite transaction."""
        spot_rows: list[dict[str, object]] = []
        metadata_rows: list[dict[str, object]] = []

        for position, spot in enumerate(result.snapshot.spots):
            pota = spot.pota
            spot_rows.append(
                {
                    "position": position,
                    "provider": spot.provider.value,
                    "stable_key": spot.stable_key,
                    "callsign": str(spot.callsign),
                    "operator_name": spot.operator_name,
                    "grid": str(spot.grid) if spot.grid is not None else None,
                    "frequency_hz": spot.frequency.hz,
                    "mode": spot.mode.value,
                    "display_mode": spot.display_mode,
                    "spotted_at": self._timestamp_text(spot.spotted_at),
                    "pota_park_reference": (
                        str(pota.park_reference) if pota is not None else None
                    ),
                    "pota_park_name": pota.park_name if pota is not None else None,
                    "pota_location_code": pota.location_code if pota is not None else None,
                    "pota_latitude": pota.latitude if pota is not None else None,
                    "pota_longitude": pota.longitude if pota is not None else None,
                }
            )
            metadata_rows.extend(
                {
                    "spot_position": position,
                    "metadata_position": metadata_position,
                    "metadata_key": item.key,
                    "metadata_value": item.value,
                }
                for metadata_position, item in enumerate(spot.source_metadata)
            )

        provider_rows = [
            {
                "provider": health.provider.value,
                "status": health.status.value,
                "active_spot_count": health.active_spot_count,
                "last_attempt_at": self._optional_timestamp_text(health.last_attempt_at),
                "last_success_at": self._optional_timestamp_text(health.last_success_at),
                "last_error": health.last_error,
            }
            for health in result.providers
        ]

        try:
            with sqlite3.connect(self._database_path) as connection:
                connection.execute("PRAGMA foreign_keys = ON")
                connection.execute("BEGIN")
                connection.execute("DELETE FROM forge_spot_cache_source_metadata")
                connection.execute("DELETE FROM forge_spot_cache_provider_health")
                connection.execute("DELETE FROM forge_spot_cache")
                connection.execute("DELETE FROM forge_spot_cache_metadata")

                if spot_rows:
                    connection.executemany(
                        """
                        INSERT INTO forge_spot_cache (
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
                            :pota_park_reference,
                            :pota_park_name,
                            :pota_location_code,
                            :pota_latitude,
                            :pota_longitude
                        )
                        """,
                        spot_rows,
                    )

                if metadata_rows:
                    connection.executemany(
                        """
                        INSERT INTO forge_spot_cache_source_metadata (
                            spot_position,
                            metadata_position,
                            metadata_key,
                            metadata_value
                        )
                        VALUES (
                            :spot_position,
                            :metadata_position,
                            :metadata_key,
                            :metadata_value
                        )
                        """,
                        metadata_rows,
                    )

                if provider_rows:
                    connection.executemany(
                        """
                        INSERT INTO forge_spot_cache_provider_health (
                            provider,
                            status,
                            active_spot_count,
                            last_attempt_at,
                            last_success_at,
                            last_error
                        )
                        VALUES (
                            :provider,
                            :status,
                            :active_spot_count,
                            :last_attempt_at,
                            :last_success_at,
                            :last_error
                        )
                        """,
                        provider_rows,
                    )

                connection.execute(
                    """
                    INSERT INTO forge_spot_cache_metadata (
                        singleton_id,
                        snapshot_revision,
                        generated_at,
                        received_at
                    )
                    VALUES (1, ?, ?, ?)
                    """,
                    (
                        result.snapshot_revision,
                        self._timestamp_text(result.snapshot.generated_at),
                        self._timestamp_text(result.received_at),
                    ),
                )
                connection.commit()
        except sqlite3.Error as error:
            raise StorageError(
                f"Forge spot cache could not be replaced in {self._database_path}: {error}"
            ) from error

    def load(self) -> ForgeSpotClientResult | None:
        """Load and fully revalidate the durable Forge snapshot, if one exists."""
        try:
            with sqlite3.connect(self._database_path) as connection:
                connection.row_factory = sqlite3.Row
                metadata = connection.execute(
                    """
                    SELECT snapshot_revision, generated_at, received_at
                    FROM forge_spot_cache_metadata
                    WHERE singleton_id = 1
                    """
                ).fetchone()
                if metadata is None:
                    return None

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
                        pota_park_reference,
                        pota_park_name,
                        pota_location_code,
                        pota_latitude,
                        pota_longitude
                    FROM forge_spot_cache
                    ORDER BY position
                    """
                ).fetchall()
                metadata_rows = connection.execute(
                    """
                    SELECT
                        spot_position,
                        metadata_position,
                        metadata_key,
                        metadata_value
                    FROM forge_spot_cache_source_metadata
                    ORDER BY spot_position, metadata_position
                    """
                ).fetchall()
                provider_rows = connection.execute(
                    """
                    SELECT
                        provider,
                        status,
                        active_spot_count,
                        last_attempt_at,
                        last_success_at,
                        last_error
                    FROM forge_spot_cache_provider_health
                    ORDER BY provider
                    """
                ).fetchall()
        except sqlite3.Error as error:
            raise StorageError(
                f"Forge spot cache could not be read from {self._database_path}: {error}"
            ) from error

        try:
            source_metadata = self._group_source_metadata(metadata_rows)
            spots = tuple(
                self._spot_from_row(row, source_metadata.get(int(row["position"]), ()))
                for row in spot_rows
            )
            snapshot = SpotSnapshot(
                generated_at=self._parse_timestamp(metadata["generated_at"]),
                spots=spots,
            )
            providers = tuple(self._provider_from_row(row) for row in provider_rows)
            self._validate_provider_health(snapshot, providers)
            return ForgeSpotClientResult(
                snapshot_revision=self._strict_nonnegative_int(
                    metadata["snapshot_revision"],
                    field_name="snapshot_revision",
                ),
                snapshot=snapshot,
                providers=providers,
                received_at=self._parse_timestamp(metadata["received_at"]),
            )
        except (KeyError, TypeError, ValueError, ValidationError) as error:
            raise StorageError(
                f"Forge spot cache contains invalid data in {self._database_path}: {error}"
            ) from error

    @classmethod
    def _spot_from_row(
        cls,
        row: sqlite3.Row,
        source_metadata: tuple[SpotSourceMetadataItem, ...],
    ) -> SpotRecord:
        provider = SpotProvider(row["provider"])
        frequency = Frequency(hz=row["frequency_hz"])
        callsign = row["callsign"]
        identity: PotaSpotIdentity | DxSpotIdentity
        pota: PotaSpotMetadata | None

        if provider is SpotProvider.POTA:
            park_reference = row["pota_park_reference"]
            if not isinstance(park_reference, str):
                raise TypeError("POTA cache row is missing its park reference")
            legacy_key = f"pota:{park_reference}:{frequency.hz}"
            identity = PotaSpotIdentity(
                callsign=None if row["stable_key"] == legacy_key else callsign,
                park_reference=park_reference,
                frequency=frequency,
            )
            pota = PotaSpotMetadata(
                park_reference=park_reference,
                park_name=row["pota_park_name"],
                location_code=row["pota_location_code"],
                latitude=row["pota_latitude"],
                longitude=row["pota_longitude"],
            )
        else:
            identity = DxSpotIdentity(callsign=callsign, frequency=frequency)
            pota = None

        spot = SpotRecord(
            identity=identity,
            callsign=callsign,
            operator_name=row["operator_name"],
            grid=row["grid"],
            frequency=frequency,
            mode=RadioMode(row["mode"]),
            display_mode=row["display_mode"],
            spotted_at=cls._parse_timestamp(row["spotted_at"]),
            source_metadata=source_metadata,
            pota=pota,
        )
        legacy_stable_key = (
            f"pota:{spot.pota.park_reference}:{spot.frequency.hz}"
            if spot.provider is SpotProvider.POTA and spot.pota is not None
            else None
        )
        if row["stable_key"] not in {spot.stable_key, legacy_stable_key}:
            raise ValueError("cached stable spot identity does not match reconstructed spot")
        return spot

    @classmethod
    def _group_source_metadata(
        cls,
        rows: list[sqlite3.Row],
    ) -> dict[int, tuple[SpotSourceMetadataItem, ...]]:
        grouped: dict[int, list[SpotSourceMetadataItem]] = {}
        expected_position: dict[int, int] = {}
        for row in rows:
            spot_position = cls._strict_nonnegative_int(
                row["spot_position"],
                field_name="spot_position",
            )
            metadata_position = cls._strict_nonnegative_int(
                row["metadata_position"],
                field_name="metadata_position",
            )
            expected = expected_position.get(spot_position, 0)
            if metadata_position != expected:
                raise ValueError("cached source metadata positions must be contiguous")
            expected_position[spot_position] = expected + 1
            grouped.setdefault(spot_position, []).append(
                SpotSourceMetadataItem(
                    key=row["metadata_key"],
                    value=row["metadata_value"],
                )
            )
        return {key: tuple(value) for key, value in grouped.items()}

    @classmethod
    def _provider_from_row(cls, row: sqlite3.Row) -> ForgeRemoteProviderHealth:
        return ForgeRemoteProviderHealth(
            provider=SpotProvider(row["provider"]),
            status=ForgeRemoteProviderStatus(row["status"]),
            active_spot_count=cls._strict_nonnegative_int(
                row["active_spot_count"],
                field_name="active_spot_count",
            ),
            last_attempt_at=cls._parse_optional_timestamp(row["last_attempt_at"]),
            last_success_at=cls._parse_optional_timestamp(row["last_success_at"]),
            last_error=row["last_error"],
        )

    @staticmethod
    def _validate_provider_health(
        snapshot: SpotSnapshot,
        providers: tuple[ForgeRemoteProviderHealth, ...],
    ) -> None:
        provider_ids = tuple(item.provider for item in providers)
        if not provider_ids:
            raise ValueError("cached provider health must contain at least one provider")
        if provider_ids != tuple(sorted(provider_ids, key=lambda item: item.value)):
            raise ValueError("cached provider health is not in deterministic order")
        if len(provider_ids) != len(set(provider_ids)):
            raise ValueError("cached provider health contains duplicate providers")

        represented = {spot.provider for spot in snapshot.spots}
        if not represented.issubset(set(provider_ids)):
            raise ValueError("cached spot provider has no provider health row")
        for health in providers:
            active_count = sum(spot.provider is health.provider for spot in snapshot.spots)
            if active_count != health.active_spot_count:
                raise ValueError("cached provider active spot count does not match snapshot")

    @staticmethod
    def _strict_nonnegative_int(value: object, *, field_name: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise TypeError(f"cached {field_name} must be a nonnegative integer")
        return value

    @classmethod
    def _timestamp_text(cls, value: datetime) -> str:
        return cls._aware_utc(value).isoformat().replace("+00:00", "Z")

    @classmethod
    def _optional_timestamp_text(cls, value: datetime | None) -> str | None:
        return None if value is None else cls._timestamp_text(value)

    @staticmethod
    def _aware_utc(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Forge cache timestamps must be timezone-aware")
        return value.astimezone(UTC)

    @staticmethod
    def _parse_timestamp(value: object) -> datetime:
        if not isinstance(value, str):
            raise TypeError("cached timestamp must be text")
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("cached timestamp must include a timezone")
        return parsed.astimezone(UTC)

    @classmethod
    def _parse_optional_timestamp(cls, value: object) -> datetime | None:
        return None if value is None else cls._parse_timestamp(value)
