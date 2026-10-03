"""Hardware-independent FT8 CQ activity management."""

from rolling_thunder.ft8.domain import FT8CQActivity, FT8Decode, FT8MessageKind, FT8Period

DEFAULT_CQ_EXPIRY_PERIODS = 6


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

        callsign = decode.source_callsign
        if callsign is None:
            return

        existing = self._activity.get(callsign)

        if decode.kind is not FT8MessageKind.CQ:
            if existing is None:
                return
            existing_last_any = existing.last_any_decode or existing.last_period
            if decode.period < existing_last_any:
                return
            self._activity[callsign] = FT8CQActivity(
                callsign=existing.callsign,
                last_period=existing.last_cq,
                last_any_decode=decode.period,
                cq_count=existing.cq_count,
                snr_db=existing.snr_db,
                dt_seconds=existing.dt_seconds,
                audio_frequency_hz=existing.audio_frequency_hz,
                grid=decode.grid if decode.grid is not None else existing.grid,
                cq_qualifier=existing.cq_qualifier,
                pota_cq=existing.pota_cq,
                active_non_cq=True,
            )
            return

        if existing is not None and decode.period < existing.last_cq:
            return

        is_new_cq_period = existing is None or decode.period > existing.last_cq
        cq_count = 1 if existing is None else existing.cq_count + int(is_new_cq_period)
        qualifier = (
            decode.cq_qualifier
            if decode.cq_qualifier is not None
            else (existing.cq_qualifier if existing else None)
        )
        pota_cq = _decode_is_pota_cq(decode)

        self._activity[callsign] = FT8CQActivity(
            callsign=callsign,
            grid=decode.grid if decode.grid is not None else (existing.grid if existing else None),
            last_period=decode.period,
            last_any_decode=decode.period,
            cq_count=cq_count,
            snr_db=decode.snr_db,
            dt_seconds=decode.dt_seconds,
            audio_frequency_hz=decode.audio_frequency_hz,
            cq_qualifier=qualifier,
            pota_cq=pota_cq,
            active_non_cq=False,
        )

    def expire(self, current_period: FT8Period) -> None:
        """Expire entries after the configured number of periods without any traffic."""
        stale = [
            callsign
            for callsign, activity in self._activity.items()
            if current_period.index
            - (activity.last_any_decode or activity.last_period).index
            >= self._expiry_periods
        ]
        for callsign in stale:
            del self._activity[callsign]

    def snapshot(self, *, current_period: FT8Period | None = None) -> tuple[FT8CQActivity, ...]:
        """Return immutable insertion-ordered CQ activity for presentation."""
        if current_period is not None:
            self.expire(current_period)
        return tuple(self._activity.values())


def _decode_is_pota_cq(decode: FT8Decode) -> bool:
    """Return whether this decoded CQ explicitly carries a POTA token."""
    if decode.cq_qualifier is not None and decode.cq_qualifier.strip().upper() == "POTA":
        return True
    return "POTA" in {token.upper() for token in decode.raw_message.split()}
