"""Pure presentation model for the vehicle bottom status icon strip."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum

from rolling_thunder.dashboard_state import DashboardState
from rolling_thunder.domain import RadioConnectionState, RadioState
from rolling_thunder.status_monitor import StatusMonitorSnapshot, StatusState


class StatusItemId(StrEnum):
    """Stable display identities for status-strip cells."""

    HF_RADIO = "hf_radio"
    INTERNET = "internet"
    FORGE = "forge"
    MICROPHONE = "microphone"
    VOICE = "voice"
    GPS = "gps"


STATUS_ITEM_ORDER = (
    StatusItemId.HF_RADIO,
    StatusItemId.INTERNET,
    StatusItemId.FORGE,
    StatusItemId.MICROPHONE,
)


@dataclass(frozen=True, slots=True)
class StatusStripItem:
    """One glanceable status-strip cell."""

    item_id: StatusItemId
    state: StatusState


@dataclass(frozen=True, slots=True)
class StatusStripSnapshot:
    """Ordered immutable status-strip presentation."""

    items: tuple[StatusStripItem, ...]


def build_status_strip_snapshot(
    radio: RadioState,
    monitored: StatusMonitorSnapshot,
) -> StatusStripSnapshot:
    """Combine authoritative radio state with background health snapshots."""
    radio_state = (
        StatusState.HEALTHY
        if radio.connection_state is RadioConnectionState.CONNECTED
        else StatusState.UNAVAILABLE
    )
    return StatusStripSnapshot(
        items=(
            StatusStripItem(StatusItemId.HF_RADIO, radio_state),
            StatusStripItem(StatusItemId.INTERNET, monitored.internet.state),
            StatusStripItem(StatusItemId.FORGE, monitored.forge.state),
            StatusStripItem(StatusItemId.MICROPHONE, monitored.microphone.state),
        )
    )


def build_status_bar_routine_message(
    state: DashboardState,
    *,
    now: datetime | None = None,
) -> str:
    """Build hidden auxiliary icon metadata plus the visible local/UTC date text."""
    instant = now or datetime.now().astimezone()
    if instant.tzinfo is None:
        instant = instant.astimezone()
    local_date = instant.astimezone().strftime("%Y-%b-%d")
    utc_date = instant.astimezone(timezone.utc).strftime("%Y-%b-%d")
    voice_state = state.voice_state.strip().upper() or "UNKNOWN"
    gps_state = state.gps_state.strip().upper() or "UNKNOWN"
    return (
        f"[[VOICE={voice_state}]][[GPS={gps_state}]]"
        f"Local Date: {local_date} | UTC Date: {utc_date}"
    )
