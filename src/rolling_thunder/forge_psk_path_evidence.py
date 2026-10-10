"""Read-only, bounded historical outbound PSK reception evidence.

Provides observed station-to-receiver paths; NEVER claims target QSO probability,
polls PSK Reporter, modifies production data, or controls the radio.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from rolling_thunder.ft8.distance import maidenhead_distance_km

MAX_AGE = timedelta(minutes=30)
MAX_ROWS = 500
BAND_TOLERANCE_HZ = 100_000
NEAR_TARGET_KM = 600


@dataclass(frozen=True)
class PskOutboundPathEvidence:
    sender_callsign: str
    target_grid: str
    frequency_hz: int
    latest_reception_utc: datetime | None
    independent_receivers: int
    nearby_receivers: int
    median_snr_db: float | None
    provenance: str = "forge_psk_normalized_history"
    directional: bool = True
    usable_for_calibrated_probability: bool = False

    @property
    def has_relevant_evidence(self) -> bool:
        return self.nearby_receivers > 0


def lookup_outbound_evidence(
    database_path: Path,
    *,
    sender_callsign: str,
    target_grid: str,
    frequency_hz: int,
    now_utc: datetime,
) -> PskOutboundPathEvidence:
    """Inspect only our own recent transmissions received near a target.

    Historical query associations do not establish live coverage. Require exact
    sender match, same mode and band frequency neighborhood, known receiver
    grid and nonfuture timestamp; dedupe receiver callsigns.
    """
    if now_utc.utcoffset() is None:
        raise ValueError("now_utc must be timezone-aware")
    if frequency_hz <= 0:
        raise ValueError("frequency_hz must be positive")
    sender = sender_callsign.strip().upper()
    if not sender:
        raise ValueError("sender_callsign required")
    if not target_grid.strip():
        raise ValueError("target_grid required")
    empty = PskOutboundPathEvidence(sender, target_grid.upper(), frequency_hz, None, 0, 0, None)
    cutoff = (now_utc.astimezone(UTC) - MAX_AGE).isoformat().replace("+00:00", "Z")
    end = now_utc.astimezone(UTC).isoformat().replace("+00:00", "Z")
    uri = f"file:{database_path.resolve().as_posix()}?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True, timeout=0.2) as db:
            records = db.execute(
                """SELECT receiver_callsign, receiver_locator_normalized,
                          flow_start_utc, snr_db
                   FROM psk_reception
                   WHERE sender_callsign = ? COLLATE NOCASE
                     AND frequency_hz BETWEEN ? AND ?
                     AND flow_start_utc BETWEEN ? AND ?
                     AND upper(mode) = 'FT8'
                   ORDER BY flow_start_utc DESC
                   LIMIT ?""",
                (sender, frequency_hz - BAND_TOLERANCE_HZ,
                 frequency_hz + BAND_TOLERANCE_HZ, cutoff, end, MAX_ROWS),
            ).fetchall()
    except (sqlite3.Error, OSError):
        return empty

    receivers: dict[str, tuple[datetime, int | None, bool]] = {}
    for receiver, grid, stamp, snr in records:
        if not receiver or not grid:
            continue
        try:
            distance = maidenhead_distance_km(target_grid, grid)
            observed = datetime.fromisoformat(stamp).astimezone(UTC)
        except (ValueError, TypeError):
            continue
        if observed > now_utc.astimezone(UTC) or observed < now_utc.astimezone(UTC) - MAX_AGE:
            continue
        call = str(receiver).upper().strip()
        if call not in receivers:
            receivers[call] = (observed, snr, distance <= NEAR_TARGET_KM)
    nearby = [(date, snr) for date, snr, close in receivers.values() if close]
    values = sorted(snr for _, snr in nearby if isinstance(snr, int))
    median = None
    if values:
        n = len(values)
        median = (values[(n - 1) // 2] + values[n // 2]) / 2
    return PskOutboundPathEvidence(
        sender, target_grid.upper(), frequency_hz,
        max((date for date, _ in nearby), default=None),
        len(receivers), len(nearby), median,
    )
