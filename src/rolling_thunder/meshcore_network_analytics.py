"""Bounded, read-only MeshCore network analytics over existing collector SQLite.

This module does not open serial devices, poll GPS, migrate the database, or
assert coverage/uptime from missing observations.
"""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ActivityCell:
    """Observed reception count in a coarse receiver-location bin."""

    latitude_bin: float
    longitude_bin: float
    observations: int
    signal_samples: int


@dataclass(frozen=True, slots=True)
class MeshcoreActivitySnapshot:
    """Time-bounded reception evidence, not node availability or route quality."""

    start_utc: datetime
    end_utc: datetime
    distinct_nodes: int
    distinct_repeaters_latest_role: int
    first_seen_nodes: int
    advertisement_events: int
    signal_samples: int
    receiver_cells: tuple[ActivityCell, ...]


class MeshcoreNetworkAnalytics:
    """Read only collector schema-2 history without acquiring write authority."""

    def __init__(self, database_path: Path) -> None:
        self._database = database_path

    def summarize(
        self,
        start: datetime,
        end: datetime,
        *,
        maximum_cells: int = 100,
    ) -> MeshcoreActivitySnapshot:
        """Summarize a bounded UTC window, with explicit observation semantics."""
        if (
            start.tzinfo is None
            or start.utcoffset() is None
            or end.tzinfo is None
            or end.utcoffset() is None
        ):
            raise ValueError("Time window must be timezone-aware")
        if not 1 <= maximum_cells <= 200:
            raise ValueError("Invalid cell limit")
        begin = start.astimezone(UTC)
        finish = end.astimezone(UTC)
        if not begin < finish or finish - begin > timedelta(days=31):
            raise ValueError("Invalid analytics time window")
        first, last = begin.isoformat(), finish.isoformat()

        # Query-only connection and SQLite's authorizer are intentionally scoped
        # to the service, not to UI or untrusted message input.
        with sqlite3.connect(
            f"file:{self._database}?mode=ro", uri=True, timeout=1.0
        ) as connection:
            connection.execute("PRAGMA query_only=ON")
            version = connection.execute(
                "SELECT version FROM meshcore_schema WHERE id=1"
            ).fetchone()
            if version != (2,):
                raise ValueError("Unsupported MeshCore observation database")

            def scalar(sql: str) -> int:
                """Execute one bounded aggregate with the same UTC window."""
                row = connection.execute(sql, (first, last)).fetchone()
                if row is None:
                    raise ValueError("Missing analytics aggregate")
                return int(row[0])

            nodes = scalar(
                "SELECT COUNT(DISTINCT public_key_hex) "
                "FROM meshcore_observations "
                "WHERE received_at_utc >= ? AND received_at_utc < ?"
            )
            repeaters = scalar(
                "SELECT COUNT(DISTINCT obs.public_key_hex) "
                "FROM meshcore_observations AS obs "
                "JOIN meshcore_observed_nodes AS nodes "
                "ON nodes.public_key_hex=obs.public_key_hex "
                "WHERE obs.received_at_utc >= ? AND obs.received_at_utc < ? "
                "AND nodes.node_type_code=2"
            )
            new_nodes = scalar(
                "SELECT COUNT(*) FROM meshcore_observed_nodes "
                "WHERE first_seen_utc >= ? AND first_seen_utc < ?"
            )
            adverts = scalar(
                "SELECT COUNT(*) FROM meshcore_observations "
                "WHERE received_at_utc >= ? AND received_at_utc < ?"
            )
            signals = scalar(
                "SELECT COUNT(*) FROM meshcore_signal_samples "
                "WHERE received_at_utc >= ? AND received_at_utc < ?"
            )

            # Receiver coordinates are where the car received traffic,
            # NEVER the peer/node physical coordinates.
            rows = connection.execute(
                """
                SELECT latitude_bin, longitude_bin, SUM(observations),
                       SUM(signal_samples) FROM (
                    SELECT ROUND(receiver_latitude, 2) AS latitude_bin,
                           ROUND(receiver_longitude, 2) AS longitude_bin,
                           COUNT(*) AS observations, 0 AS signal_samples
                    FROM meshcore_observations
                    WHERE received_at_utc >= ? AND received_at_utc < ?
                          AND receiver_latitude IS NOT NULL
                          AND receiver_longitude IS NOT NULL
                    GROUP BY 1, 2
                    UNION ALL
                    SELECT ROUND(receiver_latitude, 2),
                           ROUND(receiver_longitude, 2), 0, COUNT(*)
                    FROM meshcore_signal_samples
                    WHERE received_at_utc >= ? AND received_at_utc < ?
                          AND receiver_latitude IS NOT NULL
                          AND receiver_longitude IS NOT NULL
                    GROUP BY 1, 2
                )
                GROUP BY latitude_bin, longitude_bin
                ORDER BY SUM(observations) + SUM(signal_samples) DESC,
                         latitude_bin, longitude_bin
                LIMIT ?
                """,
                (first, last, first, last, maximum_cells),
            ).fetchall()
        cells = tuple(
            ActivityCell(float(lat), float(lon), int(obs), int(samples))
            for lat, lon, obs, samples in rows
            if lat is not None and lon is not None
            and math.isfinite(float(lat)) and math.isfinite(float(lon))
        )
        return MeshcoreActivitySnapshot(
            begin, finish, nodes, repeaters, new_nodes, adverts, signals, cells
        )
