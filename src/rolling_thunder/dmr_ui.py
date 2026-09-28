"""Pure bounded presentation model for the mobile DMR hotspot panel."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from rolling_thunder.dmr_commit import DmrCommitStatus
from rolling_thunder.dmr_monitor import DmrMonitorSnapshot, monitored_dmr_active_calls
from rolling_thunder.dmr_selection import DmrSelectionState, DmrStageOrigin

_DEFAULT_MAX_HISTORY_ROWS = 12


@dataclass(frozen=True, slots=True)
class DmrAudioCard:
    """Compact CURRENT AUDIO presentation for one active timeslot."""

    callsign_line: str
    detail_line: str
    alias_line: str
    staged: bool


@dataclass(frozen=True, slots=True)
class DmrHistoryCard:
    """Compact completed-caller presentation for the encoder history viewport."""

    callsign_line: str
    detail_line: str
    selected: bool
    staged: bool


@dataclass(frozen=True, slots=True)
class DmrViewport:
    """Bounded DMR presentation consumed by the 1024x600 Tk dashboard."""

    title: str
    health_line: str
    error_line: str
    rf_line: str
    current_audio_cards: tuple[DmrAudioCard, ...]
    history_cards: tuple[DmrHistoryCard, ...]
    hidden_above_count: int
    hidden_below_count: int
    stage_line: str
    commit_line: str

    @property
    def current_audio_idle(self) -> bool:
        """Return whether no DMR voice transmission is active right now."""
        return not self.current_audio_cards

    @property
    def has_history(self) -> bool:
        """Return whether any completed caller rows are presentable."""
        return bool(self.history_cards)


def format_dmr_timestamp(occurred_at: datetime) -> str:
    """Format an authoritative UTC DMR timestamp with both date and time."""
    return occurred_at.strftime("%m/%d/%y %H:%MZ")


def build_dmr_viewport(
    monitor: DmrMonitorSnapshot,
    selection: DmrSelectionState,
    commit: DmrCommitStatus,
    *,
    max_history_rows: int = _DEFAULT_MAX_HISTORY_ROWS,
) -> DmrViewport:
    """Build a bounded read-only DMR dashboard presentation without I/O."""
    if max_history_rows < 1:
        raise ValueError("DMR history row limit must be positive")

    history = selection.history
    selected_index = next(
        (
            index
            for index, record in enumerate(history)
            if record.identity == selection.selected_identity
        ),
        None,
    )
    total_rows = len(history)
    if selected_index is None:
        start_index = 0
    else:
        start_index = max(0, selected_index - max_history_rows + 1)
        start_index = min(start_index, max(0, total_rows - max_history_rows))
    end_index = min(total_rows, start_index + max_history_rows)

    staged = selection.staged_qso
    active_cards = tuple(
        DmrAudioCard(
            callsign_line=call.identity.callsign,
            detail_line=(
                f"{format_dmr_timestamp(call.identity.started_at)} · "
                f"TS{call.identity.slot} · {call.identity.target} · "
                f"{call.identity.source.value.upper()}"
            ),
            alias_line=call.talker_alias or "LIVE VOICE",
            staged=(
                staged is not None
                and staged.origin is DmrStageOrigin.CURRENT_AUDIO
                and staged.identity == call.identity
            ),
        )
        for call in sorted(
            monitored_dmr_active_calls(monitor),
            key=lambda item: item.identity.slot,
        )
    )

    history_cards = tuple(
        DmrHistoryCard(
            callsign_line=record.callsign,
            detail_line=_history_detail_line(
                record.name,
                occurred_at=record.occurred_at,
                slot=record.slot,
                talkgroup=record.talkgroup,
                duration_s=record.duration_s,
                source=record.source.value.upper(),
            ),
            selected=record.identity == selection.selected_identity,
            staged=(
                staged is not None
                and staged.origin is DmrStageOrigin.HISTORY
                and staged.identity == record.identity
            ),
        )
        for record in history[start_index:end_index]
    )

    return DmrViewport(
        title=(
            f"DMR HOTSPOT — TG{monitor.monitored_talkgroup}"
            if monitor.monitored_talkgroup is not None
            else "DMR HOTSPOT — TG ?"
        ),
        health_line=_health_line(monitor),
        error_line=_error_line(monitor),
        rf_line=_rf_line(monitor),
        current_audio_cards=active_cards,
        history_cards=history_cards,
        hidden_above_count=start_index,
        hidden_below_count=max(0, total_rows - end_index),
        stage_line=_stage_line(selection, monitor.monitored_talkgroup),
        commit_line=_commit_line(commit),
    )


def _history_detail_line(
    name: str | None,
    *,
    occurred_at: datetime,
    slot: int,
    talkgroup: int,
    duration_s: float,
    source: str,
) -> str:
    """Build a compact history detail with authoritative date and time."""
    source_label = "NET" if source == "NETWORK" else source
    metadata = f"TG{talkgroup} · TS{slot} · {duration_s:.0f}s · {source_label}"
    timestamp = format_dmr_timestamp(occurred_at)
    if name is None or not name.strip():
        return f"{timestamp} · {metadata}"
    return f"{timestamp} · {name.strip()} · {metadata}"


def _health_line(monitor: DmrMonitorSnapshot) -> str:
    def availability(available: bool) -> str:
        return "OK" if available else "DOWN"

    return (
        f"{monitor.health.value.upper()}  "
        f"LIVE {availability(monitor.live_available)}  "
        f"HISTORY {availability(monitor.history_available)}  "
        f"RF {availability(monitor.radio_available)}"
    )


def _error_line(monitor: DmrMonitorSnapshot) -> str:
    errors = (
        ("LIVE", monitor.live_error),
        ("HISTORY", monitor.history_error),
        ("RF", monitor.radio_error),
    )
    return "  |  ".join(
        f"{label}: {message}" for label, message in errors if message
    )


def _rf_line(monitor: DmrMonitorSnapshot) -> str:
    radio = monitor.radio_info
    if radio is None:
        return "RF INFORMATION UNAVAILABLE"
    return (
        f"RX {_mhz(radio.radio_rx_hz)} MHz  "
        f"TX {_mhz(radio.radio_tx_hz)} MHz  "
        f"{radio.mode.upper()}"
    )


def _stage_line(
    selection: DmrSelectionState,
    monitored_talkgroup: int | None,
) -> str:
    staged = selection.staged_qso
    if staged is None:
        if monitored_talkgroup is None:
            return "MONITORED TG UNKNOWN — KEY DESIRED TG TO ARM LOGGING"
        return (
            f"TG{monitored_talkgroup}  •  BTN1 STAGE CURRENT  •  "
            "ENCODER SELECT  •  PRESS STAGE HISTORY"
        )

    target = f"TG{staged.talkgroup}" if staged.talkgroup is not None else staged.target
    return (
        f"STAGED {staged.callsign}  TS{staged.slot} {target}  "
        "•  BTN2 COMMIT  •  BACK CANCEL"
    )


def _commit_line(commit: DmrCommitStatus) -> str:
    if commit.committing:
        return "COMMITTING STAGED DMR QSO"
    if commit.last_error:
        return f"COMMIT FAILED: {commit.last_error}"
    if commit.committed_contact is not None:
        return f"LOGGED {commit.committed_contact.callsign}"
    return ""


def _mhz(frequency_hz: int) -> str:
    return f"{frequency_hz / 1_000_000:.4f}"
