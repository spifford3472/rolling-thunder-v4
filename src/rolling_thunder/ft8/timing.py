"""Injectable UTC/monotonic timing for FT8 application logic."""

from datetime import UTC, datetime, timedelta
from time import monotonic
from typing import Protocol

from rolling_thunder.ft8.domain import FT8Period


class FT8Clock(Protocol):
    """Minimal clock boundary needed by FT8 domain/application code."""

    def now_utc(self) -> datetime:
        """Return the current timezone-aware UTC time."""
        ...

    def monotonic(self) -> float:
        """Return monotonic elapsed-time source."""
        ...

    def current_period(self) -> FT8Period:
        """Return the current UTC-aligned FT8 period."""
        ...


class SystemFT8Clock:
    """Production adapter that observes, but never adjusts, system time."""

    def now_utc(self) -> datetime:
        return datetime.now(UTC)

    def monotonic(self) -> float:
        return monotonic()

    def current_period(self) -> FT8Period:
        return FT8Period.from_utc(self.now_utc())


class FakeFT8Clock:
    """Deterministic fake clock for slot and deadline tests."""

    def __init__(self, now_utc: datetime, *, monotonic_seconds: float = 0.0) -> None:
        if now_utc.tzinfo is None or now_utc.utcoffset() is None:
            raise ValueError("fake FT8 clock requires timezone-aware UTC time")
        self._now_utc = now_utc.astimezone(UTC)
        self._monotonic_seconds = float(monotonic_seconds)

    def now_utc(self) -> datetime:
        return self._now_utc

    def monotonic(self) -> float:
        return self._monotonic_seconds

    def current_period(self) -> FT8Period:
        return FT8Period.from_utc(self._now_utc)

    def advance(self, seconds: float) -> None:
        """Advance UTC and monotonic clocks together without sleeping."""
        if seconds < 0:
            raise ValueError("fake FT8 clock cannot move backward")
        self._now_utc += timedelta(seconds=seconds)
        self._monotonic_seconds += seconds
