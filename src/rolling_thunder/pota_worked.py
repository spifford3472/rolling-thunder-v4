"""Durable UTC-day POTA worked markers for the shared mobile spot panel."""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from threading import Lock

from rolling_thunder.contact_metadata import POTA_FREQUENCY_TOLERANCE_HZ
from rolling_thunder.domain import Contact, Frequency, RadioMode
from rolling_thunder.pota_spots import AmateurBand, PotaSpot, frequency_band
from rolling_thunder.storage import StorageError, initialize_database

_LOGGER = logging.getLogger(__name__)
_PHONE_MODES = frozenset({RadioMode.LSB, RadioMode.USB})
Clock = Callable[[], datetime]


@dataclass(frozen=True, slots=True)
class PotaWorkedKey:
    """Exact operator-facing key used to mark one POTA combination worked."""

    callsign: str
    band: AmateurBand
    display_mode: str

    def __post_init__(self) -> None:
        callsign = self.callsign.strip().upper()
        display_mode = self.display_mode.strip().upper()
        if not callsign:
            raise ValueError("POTA worked callsign must not be blank")
        if not display_mode:
            raise ValueError("POTA worked mode must not be blank")
        object.__setattr__(self, "callsign", callsign)
        object.__setattr__(self, "display_mode", display_mode)


@dataclass(frozen=True, slots=True)
class PotaWorkedMarker:
    """One durable worked key associated with the UTC day of the QSO."""

    key: PotaWorkedKey
    worked_at: datetime

    def __post_init__(self) -> None:
        if self.worked_at.tzinfo is None or self.worked_at.utcoffset() is None:
            raise ValueError("POTA worked timestamp must be timezone-aware")
        object.__setattr__(self, "worked_at", self.worked_at.astimezone(UTC))

    @property
    def utc_date(self) -> date:
        """Return the UTC calendar date controlling marker lifetime."""
        return self.worked_at.date()


class PotaWorkedRepository:
    """Persist exact POTA worked combinations in the existing local database."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        initialize_database(database_path)

    def record(self, marker: PotaWorkedMarker) -> None:
        """Insert or refresh one worked marker after a durable contact commit."""
        try:
            with sqlite3.connect(self._database_path) as connection:
                connection.execute(
                    """
                    INSERT INTO pota_worked_markers (
                        utc_date,
                        callsign,
                        band,
                        display_mode,
                        worked_at
                    )
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT (utc_date, callsign, band, display_mode)
                    DO UPDATE SET worked_at = excluded.worked_at
                    """,
                    (
                        marker.utc_date.isoformat(),
                        marker.key.callsign,
                        marker.key.band.value,
                        marker.key.display_mode,
                        marker.worked_at.isoformat().replace("+00:00", "Z"),
                    ),
                )
                connection.commit()
        except sqlite3.Error as error:
            raise StorageError(
                f"POTA worked marker could not be stored in {self._database_path}: {error}"
            ) from error

    def list_for_day(self, utc_date: date) -> tuple[PotaWorkedMarker, ...]:
        """Load the durable worked set for one UTC calendar day."""
        try:
            with sqlite3.connect(self._database_path) as connection:
                rows = connection.execute(
                    """
                    SELECT callsign, band, display_mode, worked_at
                    FROM pota_worked_markers
                    WHERE utc_date = ?
                    ORDER BY worked_at ASC, callsign ASC, band ASC, display_mode ASC
                    """,
                    (utc_date.isoformat(),),
                ).fetchall()
        except sqlite3.Error as error:
            raise StorageError(
                f"POTA worked markers could not be read from {self._database_path}: {error}"
            ) from error

        markers: list[PotaWorkedMarker] = []
        try:
            for callsign, band, display_mode, worked_at in rows:
                markers.append(
                    PotaWorkedMarker(
                        key=PotaWorkedKey(
                            callsign=str(callsign),
                            band=AmateurBand(str(band)),
                            display_mode=str(display_mode),
                        ),
                        worked_at=datetime.fromisoformat(str(worked_at).replace("Z", "+00:00")),
                    )
                )
        except (TypeError, ValueError) as error:
            raise StorageError("POTA worked marker data is invalid.") from error
        return tuple(markers)


class PotaWorkedTracker:
    """Maintain a no-I/O UI lookup set with durable same-day restart recovery."""

    def __init__(
        self,
        repository: PotaWorkedRepository,
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
        display_mode: str,
        reference_time: datetime | None = None,
    ) -> bool:
        """Return whether this exact callsign/mode/band key is worked today."""
        now = self._aware_utc(reference_time or self._clock())
        band = frequency_band(frequency)
        if band is None:
            return False
        key = PotaWorkedKey(
            callsign=callsign,
            band=band,
            display_mode=display_mode,
        )
        with self._lock:
            self._roll_day(now.date())
            return key in self._keys

    def record_contact(
        self,
        contact: Contact,
        pota_spots: tuple[PotaSpot, ...],
    ) -> PotaWorkedKey | None:
        """Record a unique exact POTA spot match after its contact is durable."""
        key = pota_worked_key_from_contact(contact, pota_spots)
        if key is None:
            return None

        marker = PotaWorkedMarker(key=key, worked_at=contact.started_at)
        try:
            self._repository.record(marker)
        except StorageError:
            _LOGGER.exception("POTA worked marker persistence failed after contact commit")

        now = self._aware_utc(self._clock())
        with self._lock:
            self._roll_day(now.date())
            if marker.utc_date == self._day:
                self._keys.add(marker.key)
        return key

    def _roll_day(self, utc_date: date) -> None:
        if utc_date == self._day:
            return
        self._day = utc_date
        self._keys.clear()

    @staticmethod
    def _aware_utc(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("POTA worked clock must return an aware datetime")
        return value.astimezone(UTC)


def pota_worked_key_from_contact(
    contact: Contact,
    pota_spots: tuple[PotaSpot, ...],
) -> PotaWorkedKey | None:
    """Resolve one exact display-mode key without guessing ambiguous POTA matches."""
    if contact.pota_reference is None:
        return None

    contact_frequency = Frequency(hz=contact.frequency_hz)
    band = frequency_band(contact_frequency)
    if band is None:
        return None

    display_modes: set[str] = set()
    for spot in pota_spots:
        if str(spot.activator) != str(contact.callsign):
            continue
        if str(spot.park.reference) != str(contact.pota_reference):
            continue
        if frequency_band(spot.frequency) is not band:
            continue
        if abs(spot.frequency.hz - contact.frequency_hz) > POTA_FREQUENCY_TOLERANCE_HZ:
            continue
        if not _modes_compatible(contact.mode, spot.mode):
            continue
        display_modes.add(spot.display_mode)

    if len(display_modes) != 1:
        return None

    return PotaWorkedKey(
        callsign=str(contact.callsign),
        band=band,
        display_mode=next(iter(display_modes)),
    )


def _modes_compatible(left: RadioMode, right: RadioMode) -> bool:
    if left is right:
        return True
    return left in _PHONE_MODES and right in _PHONE_MODES
