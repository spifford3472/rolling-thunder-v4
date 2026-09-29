"""Hardware-independent FT8 CQ activity management."""

from rolling_thunder.ft8.domain import FT8CQActivity, FT8Decode, FT8MessageKind, FT8Period

DEFAULT_CQ_EXPIRY_PERIODS = 4


class FT8CQActivityManager:
    """Collect, deduplicate, refresh, expire, and snapshot CQ activity."""

    def __init__(self, *, expiry_periods: int = DEFAULT_CQ_EXPIRY_PERIODS) -> None:
        if expiry_periods < 1:
            raise ValueError("expiry_periods must be at least 1")
        self._expiry_periods = expiry_periods
        self._activity: dict[str, FT8CQActivity] = {}
        self._latest_period: FT8Period | None = None

    @property
    def latest_period(self) -> FT8Period | None:
        return self._latest_period

    def ingest(self, decode: FT8Decode) -> None:
        """Ingest one normalized decode without selecting or contacting a station."""
        if self._latest_period is None or decode.period > self._latest_period:
            self._latest_period = decode.period
        self.expire(decode.period)

        if decode.kind is not FT8MessageKind.CQ or decode.source_callsign is None:
            return

        existing = self._activity.get(decode.source_callsign)
        if existing is not None and decode.period < existing.last_period:
            return

        self._activity[decode.source_callsign] = FT8CQActivity(
            callsign=decode.source_callsign,
            grid=decode.grid if decode.grid is not None else (existing.grid if existing else None),
            last_period=decode.period,
            snr_db=decode.snr_db,
            dt_seconds=decode.dt_seconds,
            audio_frequency_hz=decode.audio_frequency_hz,
            cq_qualifier=(
                decode.cq_qualifier
                if decode.cq_qualifier is not None
                else (existing.cq_qualifier if existing else None)
            ),
        )

    def expire(self, current_period: FT8Period) -> None:
        """Expire entries at or beyond the configured period age."""
        stale = [
            callsign
            for callsign, activity in self._activity.items()
            if current_period.index - activity.last_period.index >= self._expiry_periods
        ]
        for callsign in stale:
            del self._activity[callsign]

    def snapshot(self, *, current_period: FT8Period | None = None) -> tuple[FT8CQActivity, ...]:
        """Return an immutable recency-ordered snapshot for future presentation."""
        if current_period is not None:
            self.expire(current_period)
        return tuple(
            sorted(
                self._activity.values(),
                key=lambda item: (-item.last_period.index, item.callsign),
            )
        )
