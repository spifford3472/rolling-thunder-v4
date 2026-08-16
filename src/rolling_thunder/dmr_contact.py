"""Pure conversion from immutable staged DMR activity into a local Contact."""

from __future__ import annotations

from datetime import datetime, timedelta

from rolling_thunder.dmr_selection import StagedDmrQso
from rolling_thunder.domain import Contact, RadioMode


class DmrContactBuildError(ValueError):
    """Raised when a staged DMR QSO cannot produce a complete local contact."""


def build_dmr_contact(
    staged: StagedDmrQso,
    *,
    rst_sent: str = "59",
    rst_received: str = "59",
) -> Contact:
    """Build one immutable local Contact without persistence or live-state reads."""
    started_at = _contact_started_at(staged)
    return Contact(
        callsign=staged.callsign,
        frequency_hz=staged.radio_tx_hz,
        mode=RadioMode.DMR,
        started_at=started_at,
        rst_sent=rst_sent,
        rst_received=rst_received,
        my_grid=staged.my_grid,
        notes=_dmr_notes(staged),
    )


def _contact_started_at(staged: StagedDmrQso) -> datetime:
    if staged.started_at is not None:
        return staged.started_at
    if staged.ended_at is None:
        raise DmrContactBuildError("Staged DMR QSO has no usable contact timestamp.")
    if staged.duration_s is None:
        return staged.ended_at
    return staged.ended_at - timedelta(seconds=staged.duration_s)


def _dmr_notes(staged: StagedDmrQso) -> str:
    metadata = [
        "DMR",
        f"TG {staged.talkgroup}" if staged.talkgroup is not None else staged.target,
        f"TS{staged.slot}",
        f"source={staged.source.value}",
        f"TX={_mhz(staged.radio_tx_hz)} MHz",
        f"RX={_mhz(staged.radio_rx_hz)} MHz",
    ]
    if staged.name:
        metadata.append(f"name={staged.name}")
    if staged.country:
        metadata.append(f"country={staged.country}")
    if staged.talker_alias:
        metadata.append(f"alias={staged.talker_alias}")
    if staged.duration_s is not None:
        metadata.append(f"duration={staged.duration_s:.1f}s")
    if staged.packet_loss_percent is not None:
        metadata.append(f"loss={staged.packet_loss_percent:.1f}%")
    if staged.ber_percent is not None:
        metadata.append(f"BER={staged.ber_percent:.1f}%")
    return "; ".join(metadata)


def _mhz(frequency_hz: int) -> str:
    return f"{frequency_hz / 1_000_000:.6f}"
