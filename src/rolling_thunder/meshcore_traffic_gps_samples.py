"""Read-only, rate-limited adapter to Rolling Thunder's existing GPS publication.

A caller drives the lifecycle; sampling never blocks for a GPS fix and never
opens hardware, starts a poller, or writes to the shared snapshot file.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from rolling_thunder.domain import GPSPosition
from rolling_thunder.gps import GPSState
from rolling_thunder.meshcore_geographic_relevance import (
    GeoPoint,
    PublishedGpsHeading,
    VehicleFix,
)
from rolling_thunder.meshcore_gps_bridge import read_meshcore_gps_snapshot


class ExistingGpsSampler:
    """Offer the already-published GPS snapshot at no more than one Hz."""

    def __init__(
        self,
        snapshot: Path,
        *,
        reader: Callable[[Path], GPSState | None] = read_meshcore_gps_snapshot,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._snapshot = snapshot
        self._reader = reader
        self._clock = clock
        self._last_read: float | None = None
        self.history = PublishedGpsHeading()

    def sample(self) -> bool:
        """Read once if due; reject invalid or unavailable published fixes."""

        now = self._clock()
        if not math.isfinite(now):
            return False
        if self._last_read is not None and now - self._last_read < 1.0:
            return False
        self._last_read = now
        state = self._reader(self._snapshot)
        if state is None or state.position is None:
            return False
        position = state.position
        if position.latitude is None or position.longitude is None or position.accuracy_m is None:
            return False
        return self.history.offer(
            self._adapt(position, position.latitude, position.longitude, position.accuracy_m)
        )

    @staticmethod
    def _adapt(
        position: GPSPosition, latitude: float, longitude: float, accuracy_m: float
    ) -> VehicleFix:
        """Consume the authoritative position and accuracy without inventing speed."""

        return VehicleFix(
            GeoPoint(latitude, longitude),
            position.updated_at.astimezone(UTC),
            accuracy_m,
        )


def fresh_gps_sample_span(history: PublishedGpsHeading, now: datetime) -> bool:
    """Require 2–5 seconds of already-accepted fixes for movement analysis."""

    return history.has_recent_span(now)
