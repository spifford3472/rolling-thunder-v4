"""UTC-day suppression of already-completed FT8 callsign/band contacts."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, time
from threading import RLock
from typing import Protocol

from rolling_thunder.domain import Contact, Frequency, RadioMode
from rolling_thunder.radio import RadioBand
from rolling_thunder.radio_band import RadioBandResolutionError, resolve_radio_band


class FT8WorkedContactRepository(Protocol):
    """Read persisted contacts used to seed today's completed FT8 keys."""

    def list_since(
        self,
        started_at: datetime,
        *,
        mode: RadioMode | None = None,
    ) -> list[Contact]:
        ...


Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


class FT8WorkedTodayService:
    """Derived in-memory cache backed by the normal completed-contact repository."""

    def __init__(
        self,
        repository: FT8WorkedContactRepository,
        *,
        clock: Clock = _utc_now,
    ) -> None:
        self._repository = repository
        self._clock = clock
        self._lock = RLock()
        now = self._normalized_now()
        self._utc_date = now.date()
        self._worked: set[tuple[str, RadioBand]] = set()
        self._load_date(self._utc_date)

    def is_suppressed(self, callsign: str, band: RadioBand) -> bool:
        """Return whether this callsign/band already completed FT8 today."""
        normalized_callsign = callsign.strip().upper()
        if not normalized_callsign:
            return False
        with self._lock:
            self._roll_date_if_needed()
            return (normalized_callsign, band) in self._worked

    def record_completed(self, contact: Contact) -> None:
        """Update the derived cache only after an FT8 contact is durably committed."""
        if contact.mode is not RadioMode.FT8:
            return
        with self._lock:
            self._roll_date_if_needed()
            if contact.started_at.astimezone(UTC).date() != self._utc_date:
                return
            try:
                band = resolve_radio_band(Frequency(hz=contact.frequency_hz))
            except RadioBandResolutionError:
                return
            self._worked.add((contact.callsign.strip().upper(), band))

    def _load_date(self, utc_date: date) -> None:
        start = datetime.combine(utc_date, time.min, tzinfo=UTC)
        contacts = self._repository.list_since(start, mode=RadioMode.FT8)
        for contact in contacts:
            if contact.started_at.astimezone(UTC).date() != utc_date:
                continue
            try:
                band = resolve_radio_band(Frequency(hz=contact.frequency_hz))
            except RadioBandResolutionError:
                continue
            self._worked.add((contact.callsign.strip().upper(), band))

    def _roll_date_if_needed(self) -> None:
        current_date = self._normalized_now().date()
        if current_date == self._utc_date:
            return
        self._utc_date = current_date
        self._worked.clear()

    def _normalized_now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("FT8 worked-today clock must be timezone-aware")
        return now.astimezone(UTC)
