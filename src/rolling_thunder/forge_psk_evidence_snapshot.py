"""Bounded cached publication model for Forge outbound PSK reception evidence.

Pure service-layer component: no listener, no provider polling, and no radio
authority. A separate authenticated private API may expose its snapshots.
"""
from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import Any

from rolling_thunder.forge_psk_path_evidence import (
    PskOutboundPathEvidence,
    lookup_outbound_evidence,
)

CACHE_TTL = timedelta(minutes=2)
MAX_CACHE_KEYS = 256


@dataclass(frozen=True)
class EvidenceSnapshot:
    status: str
    evidence: PskOutboundPathEvidence | None
    checked_at_utc: datetime
    expires_at_utc: datetime
    schema_version: int = 1

    def public_data(self) -> dict[str, Any]:
        """Safe JSON-compatible payload without database locations or secrets."""
        result = asdict(self)
        result["checked_at_utc"] = self.checked_at_utc.isoformat()
        result["expires_at_utc"] = self.expires_at_utc.isoformat()
        if self.evidence is not None:
            result["evidence"]["latest_reception_utc"] = (
                None if self.evidence.latest_reception_utc is None
                else self.evidence.latest_reception_utc.isoformat()
            )
        return result


class PskEvidenceSnapshotService:
    """Forge-local, bounded request cache; no network or provider side effects."""

    def __init__(
        self,
        history_database: Path,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        reader: Callable[..., PskOutboundPathEvidence] = lookup_outbound_evidence,
    ) -> None:
        self._history_database = history_database
        self._clock = clock
        self._reader = reader
        self._lock = Lock()
        self._cache: OrderedDict[tuple[str, str, int], EvidenceSnapshot] = OrderedDict()

    def get(self, *, sender_callsign: str, target_grid: str, frequency_hz: int) -> EvidenceSnapshot:
        now = self._clock()
        if now.utcoffset() is None:
            raise ValueError("clock must be timezone-aware")
        if not sender_callsign.strip() or not target_grid.strip() or frequency_hz <= 0:
            raise ValueError("sender, target grid and frequency are required")
        key = (sender_callsign.strip().upper(), target_grid.strip().upper(), frequency_hz)
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None and now < cached.expires_at_utc:
                self._cache.move_to_end(key)
                return cached
        evidence = self._reader(
            self._history_database,
            sender_callsign=key[0], target_grid=key[1],
            frequency_hz=key[2], now_utc=now,
        )
        snapshot = EvidenceSnapshot(
            "observed" if evidence.has_relevant_evidence else "no_recent_evidence",
            evidence, now, now + CACHE_TTL,
        )
        with self._lock:
            self._cache[key] = snapshot
            self._cache.move_to_end(key)
            while len(self._cache) > MAX_CACHE_KEYS:
                self._cache.popitem(last=False)
        return snapshot
