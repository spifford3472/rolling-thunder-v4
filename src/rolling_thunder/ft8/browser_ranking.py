"""Local-first asynchronous CQ ranking adapter; no radio or provider authority."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import BoundedSemaphore
from typing import Protocol

from rolling_thunder.ft8.bands import FT8_DIAL_FREQUENCY_HZ
from rolling_thunder.ft8.domain import FT8CQActivity
from rolling_thunder.ft8.dx_ranking import CQCandidate, RankedCQ, ReachabilityEvidence, score_cq
from rolling_thunder.ft8.psk_evidence_client import OutboundReceptionObservation
from rolling_thunder.ft8.ranking_cache import FT8RankingCache
from rolling_thunder.radio import RadioBand

_LOG = logging.getLogger(__name__)


class OutboundEvidenceReader(Protocol):
    def lookup(
        self, *, sender_callsign: str, target_grid: str,
        frequency_hz: int, now_utc: datetime,
    ) -> OutboundReceptionObservation | None: ...


def _evidence_quality(observation: OutboundReceptionObservation) -> float:
    """Conservative ordinal evidence strength, never a QSO probability."""
    # A valid outbound reception near the target supports some reachability,
    # but one reception is not confirmation the target can decode us.
    snr = observation.median_snr_db
    snr_component = 0.0 if snr is None else max(-0.08, min(0.08, snr / 150))
    return max(0.5, min(0.75, 0.60 + snr_component))


class FT8BrowserRanking:
    """Rank visible stations using a bounded local worker, never wait in UI."""

    def __init__(
        self, *, max_workers: int = 2,
        evidence_reader: OutboundEvidenceReader | None = None,
        sender_callsign: str = "KI5VNB",
    ) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="ft8-rank")
        self._cache = FT8RankingCache(self._executor)
        self._pending: frozenset[str] = frozenset()
        self._latest_rankings: dict[str, RankedCQ] = {}
        self._evidence_reader = evidence_reader
        self._sender_callsign = sender_callsign
        # Never queue an unbounded number of HTTP lookups behind the GUI.
        self._network_slots = BoundedSemaphore(max_workers * 2)

    @property
    def pending_callsigns(self) -> frozenset[str]:
        return self._pending

    @property
    def latest_rankings(self) -> dict[str, RankedCQ]:
        """Visible computed priorities, not probabilities."""
        return dict(self._latest_rankings)

    def order(
        self,
        activity: tuple[FT8CQActivity, ...],
        *,
        local_grid: str | None,
        band: str,
    ) -> tuple[FT8CQActivity, ...]:
        rankings = []
        for item in activity:
            candidate = CQCandidate(item.callsign, item.grid, item.snr_db)
            def calculate(candidate: CQCandidate = candidate) -> RankedCQ:
                evidence = None
                reader = self._evidence_reader
                try:
                    radio_band = RadioBand(band.lower())
                    freq = FT8_DIAL_FREQUENCY_HZ.get(radio_band)
                except ValueError:
                    freq = None
                if (
                    reader is not None and candidate.grid and freq is not None
                    and self._network_slots.acquire(blocking=False)
                ):
                    try:
                        observation = reader.lookup(
                            sender_callsign=self._sender_callsign,
                            target_grid=candidate.grid,
                            frequency_hz=freq, now_utc=datetime.now(UTC),
                        )
                        if observation is not None:
                            evidence = ReachabilityEvidence(
                                quality=_evidence_quality(observation),
                                observed_at_utc=observation.observed_at_utc,
                                independent_receivers=observation.receiver_count,
                            )
                    except Exception:  # noqa: BLE001 - optional provider must not affect CQ display
                        _LOG.warning("FT8 optional outbound evidence unavailable", exc_info=True)
                    finally:
                        self._network_slots.release()
                enriched = CQCandidate(candidate.callsign, candidate.grid, candidate.snr_db, evidence)
                return score_cq(enriched, local_grid=local_grid, now_utc=datetime.now(UTC))

            rankings.append(
                self._cache.view(item.callsign, band, local_grid, item.grid, calculate)
            )
        self._latest_rankings = {
            entry.callsign: entry.ranking
            for entry in rankings if entry.ranking is not None
        }
        self._pending = frozenset(
            entry.callsign for entry in rankings if entry.ranking is None
        )
        by_callsign = {item.callsign: item for item in activity}
        return tuple(by_callsign[entry.callsign] for entry in self._cache.order(tuple(rankings)))

    def close(self) -> None:
        self._cache.invalidate()
        self._executor.shutdown(wait=False, cancel_futures=True)
