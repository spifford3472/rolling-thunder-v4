"""SQLite-backed persistence for the latest successful POTA spot snapshot."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from rolling_thunder.domain import Frequency, RadioMode
from rolling_thunder.pota_spots import ParkReference, PotaSpot
from rolling_thunder.storage import StorageError, initialize_database


class PotaSpotCacheSnapshot:
    """Immutable cached POTA snapshot returned by the repository."""

    def __init__(
        self,
        *,
        spots: tuple[PotaSpot, ...],
        last_success_at: datetime,
    ) -> None:
        self.spots = spots
        self.last_success_at = last_success_at


class PotaSpotCacheRepository:
    """Replace and load the latest normalized POTA spot snapshot."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        initialize_database(database_path)

    def replace(
        self,
        spots: tuple[PotaSpot, ...],
        last_success_at: datetime,
    ) -> None:
        """Transactionally replace the complete cached snapshot."""
        normalized_success_at = self._aware_utc(last_success_at)

        rows = [
            {
                "position": position,
                "activator": str(spot.activator),
                "park_reference": spot.park.reference,
                "park_name": spot.park.name,
                "frequency_hz": spot.frequency.hz,
                "mode": spot.mode.value,
                "spotted_at": self._timestamp_text(spot.spotted_at),
                "comments": spot.comments,
            }
            for position, spot in enumerate(spots)
        ]

        try:
            with sqlite3.connect(self._database_path) as connection:
                connection.execute("BEGIN")
                connection.execute("DELETE FROM pota_spot_cache")
                connection.execute("DELETE FROM pota_spot_cache_metadata")

                if rows:
                    connection.executemany(
                        """
                        INSERT INTO pota_spot_cache (
                            position,
                            activator,
                            park_reference,
                            park_name,
                            frequency_hz,
                            mode,
                            spotted_at,
                            comments
                        )
                        VALUES (
                            :position,
                            :activator,
                            :park_reference,
                            :park_name,
                            :frequency_hz,
                            :mode,
                            :spotted_at,
                            :comments
                        )
                        """,
                        rows,
                    )

                connection.execute(
                    """
                    INSERT INTO pota_spot_cache_metadata (
                        singleton_id,
                        last_success_at
                    )
                    VALUES (1, ?)
                    """,
                    (self._timestamp_text(normalized_success_at),),
                )
                connection.commit()
        except sqlite3.Error as error:
            raise StorageError(
                f"POTA spot cache could not be replaced in "
                f"{self._database_path}: {error}"
            ) from error

    def load(self) -> PotaSpotCacheSnapshot | None:
        """Load the cached snapshot, or return None when none exists."""
        try:
            with sqlite3.connect(self._database_path) as connection:
                connection.row_factory = sqlite3.Row
                metadata = connection.execute(
                    """
                    SELECT last_success_at
                    FROM pota_spot_cache_metadata
                    WHERE singleton_id = 1
                    """
                ).fetchone()

                if metadata is None:
                    return None

                rows = connection.execute(
                    """
                    SELECT
                        activator,
                        park_reference,
                        park_name,
                        frequency_hz,
                        mode,
                        spotted_at,
                        comments
                    FROM pota_spot_cache
                    ORDER BY position
                    """
                ).fetchall()
        except sqlite3.Error as error:
            raise StorageError(
                f"POTA spot cache could not be read from "
                f"{self._database_path}: {error}"
            ) from error

        try:
            last_success_at = self._parse_timestamp(
                metadata["last_success_at"],
            )
            spots = tuple(
                PotaSpot(
                    activator=row["activator"],
                    park=ParkReference(
                        reference=row["park_reference"],
                        name=row["park_name"],
                    ),
                    frequency=Frequency(hz=row["frequency_hz"]),
                    mode=RadioMode(row["mode"]),
                    spotted_at=self._parse_timestamp(row["spotted_at"]),
                    comments=row["comments"],
                )
                for row in rows
            )
        except (
            KeyError,
            TypeError,
            ValueError,
            ValidationError,
        ) as error:
            raise StorageError(
                f"POTA spot cache contains invalid data in "
                f"{self._database_path}: {error}"
            ) from error

        return PotaSpotCacheSnapshot(
            spots=spots,
            last_success_at=last_success_at,
        )

    @staticmethod
    def _aware_utc(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(
                "POTA cache success timestamp must be timezone-aware."
            )
        return value.astimezone(UTC)

    @classmethod
    def _timestamp_text(cls, value: datetime) -> str:
        return cls._aware_utc(value).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _parse_timestamp(value: object) -> datetime:
        if not isinstance(value, str):
            raise TypeError("cached timestamp must be text")

        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)

        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("cached timestamp must include a timezone")

        return parsed.astimezone(UTC)
