"""Durable UTC-day DX worked markers for the shared mobile spot panel."""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from threading import Lock

from rolling_thunder.domain import Contact, Frequency
from rolling_thunder.pota_spots import AmateurBand, frequency_band
from rolling_thunder.storage import StorageError, initialize_database

_LOGGER = logging.getLogger(__name__)
Clock = Callable[[], datetime]


@dataclass(frozen=True, slots=True)
class DxWorkedKey:
    """Callsign and amateur band defining one worked DX combination."""

    callsign: str
    band: AmateurBand

    def __post_init__(self) -> None:
        callsign = self.callsign.strip().upper()
        if not callsign:
            raise ValueError("DX worked callsign must not be blank")
        object.__setattr__(self, "callsign", callsign)


@dataclass(frozen=True, slots=True)
class DxWorkedMarker:
    """One durable DX worked key associated with the UTC day of the QSO."""

    key: DxWorkedKey
    worked_at: datetime

    def __post_init__(self) -> None:
        if self.worked_at.tzinfo is None or self.worked_at.utcoffset() is None:
            raise ValueError("DX worked timestamp must be timezone-aware")
        object.__setattr__(self, "worked_at", self.worked_at.astimezone(UTC))

    @property
    def utc_date(self) -> date:
        """Return the UTC calendar date controlling marker lifetime."""
        return self.worked_at.date()


class DxWorkedRepository:
    """Persist DX callsign-and-band markers in the local application database."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        initialize_database(database_path)

    def record(self, marker: DxWorkedMarker) -> None:
        """Insert or refresh one marker after a durable contact commit."""
        try:
            with sqlite3.connect(self._database_path) as connection:
                connection.execute(
                    """
                    INSERT INTO dx_worked_markers (
                        utc_date,
                        callsign,
                        band,
                        worked_at
                    )
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT (utc_date, callsign, band)
                    DO UPDATE SET worked_at = excluded.worked_at
                    """,
                    (
                        marker.utc_date.isoformat(),
                        marker.key.callsign,
                        marker.key.band.value,
                        marker.worked_at.isoformat().replace("+00:00", "Z"),
                    ),
                )
                connection.commit()
        except sqlite3.Error as error:
            raise StorageError(
                f"DX worked marker could not be stored in {self._database_path}: {error}"
            ) from error

    def list_for_day(self, utc_date: date) -> tuple[DxWorkedMarker, ...]:
        """Load the durable DX worked set for one UTC calendar day."""
        try:
            with sqlite3.connect(self._database_path) as connection:
                rows = connection.execute(
                    """
                    SELECT callsign, band, worked_at
                    FROM dx_worked_markers
                    WHERE utc_date = ?
                    ORDER BY worked_at ASC, callsign ASC, band ASC
                    """,
                    (utc_date.isoformat(),),
                ).fetchall()
        except sqlite3.Error as error:
            raise StorageError(
                f"DX worked markers could not be read from {self._database_path}: {error}"
            ) from error

        markers: list[DxWorkedMarker] = []
        try:
            for callsign, band, worked_at in rows:
                markers.append(
                    DxWorkedMarker(
                        key=DxWorkedKey(
                            callsign=str(callsign),
                            band=AmateurBand(str(band)),
                        ),
                        worked_at=datetime.fromisoformat(str(worked_at)),
                    )
                )
        except (TypeError, ValueError) as error:
            raise StorageError("DX worked marker data is invalid.") from error
        return tuple(markers)


class DxWorkedTracker:
    """Maintain a no-I/O DX lookup set with same-day restart recovery."""

    def __init__(
        self,
        repository: DxWorkedRepository,
        *,
        clock: Clock | None = None,
    ) -> None:
        self._repository = repository
        self._clock = clock or (lambda: datetime.now(UTC))
        now = self._aware_utc(self._clock())
        self._day = now.date()
        self._keys = {marker.key for marker in repository.list_for_day(self._day)}
        self._lock = Lock()

    def is_worked(
        self,
        *,
        callsign: str,
        frequency: Frequency,
        reference_time: datetime | None = None,
    ) -> bool:
        """Return whether the callsign and frequency band are worked today."""
        now = self._aware_utc(reference_time or self._clock())
        band = frequency_band(frequency)
        if band is None:
            return False
        key = DxWorkedKey(callsign=callsign, band=band)
        with self._lock:
            self._roll_day(now.date())
            return key in self._keys

    def record_contact(self, contact: Contact) -> DxWorkedKey | None:
        """Record one callsign-and-band marker after its contact is durable."""
        band = frequency_band(Frequency(hz=contact.frequency_hz))
        if band is None:
            return None
        marker = DxWorkedMarker(
            key=DxWorkedKey(callsign=str(contact.callsign), band=band),
            worked_at=contact.started_at,
        )
        try:
            self._repository.record(marker)
        except StorageError:
            _LOGGER.exception("DX worked marker persistence failed after contact commit")

        now = self._aware_utc(self._clock())
        with self._lock:
            self._roll_day(now.date())
            if marker.utc_date == self._day:
                self._keys.add(marker.key)
        return marker.key

    def _roll_day(self, utc_date: date) -> None:
        if utc_date == self._day:
            return
        self._day = utc_date
        self._keys.clear()

    @staticmethod
    def _aware_utc(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("DX worked clock must return an aware datetime")
        return value.astimezone(UTC)
