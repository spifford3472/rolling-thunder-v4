"""Presentation model for the mobile-readable FT8 CQ browser."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from rolling_thunder.friend_presentation import friend_marker
from rolling_thunder.ft8.attempt_history import FT8AttemptVisualState
from rolling_thunder.ft8.diagnostics import FT8ClockQuality
from rolling_thunder.ft8.domain import FT8CQActivity, FT8IncomingCall, FT8Period
from rolling_thunder.ft8.receive import FT8ReceiveState

FT8_BROWSER_HEADERS = ("CALL", "SNR", "AUDIO", "GRID")
FT8_POTA_TREE_GLYPH = "🌲"


def format_ft8_receive_diagnostic(state: FT8ReceiveState | None) -> str:
    """Build a compact glance-readable receive-chain health summary."""
    if state is None:
        return "RX DIAGNOSTICS UNAVAILABLE"
    warnings: list[str] = []
    if state.last_clock is not None and state.last_clock.quality is not FT8ClockQuality.TRUSTED:
        warnings.append(f"CLOCK {state.last_clock.quality.value.upper()}")
    if state.last_audio is not None and state.last_audio.quality.value != "healthy":
        warnings.append(f"AUDIO {state.last_audio.quality.value.upper()}")
    if state.periods_dropped:
        warnings.append(f"DROPPED {state.periods_dropped}")
    if state.last_error:
        warnings.append(state.last_error.upper())
    if state.last_diagnostic_error:
        warnings.append(state.last_diagnostic_error.upper())
    if warnings:
        return "RX DEGRADED — " + " • ".join(warnings)

    audio = state.last_audio
    decoder = state.last_decoder
    if audio is None or decoder is None:
        return "RX STARTING — WAITING FOR COMPLETE PERIOD"
    rms = "-INF" if audio.rms_dbfs is None else f"{audio.rms_dbfs:.1f}"
    summary = (
        f"RX OK • RMS {rms} dBFS • ALIGN {audio.boundary_lateness_ms:.1f}ms • "
        f"RAW {decoder.raw_line_count} • "
        f"DECODE {decoder.parsed_decode_count} • CQ {decoder.cq_decode_count} • "
        f"{decoder.runtime_seconds:.2f}s"
    )
    session = state.diagnostic_session
    if session is None:
        return summary
    status = "RUN" if session.active else "DONE"
    return (
        f"{summary}\nDIAG {status} • ALL "
        f"{session.primary_all_decodes}/{session.comparison_all_decodes} • CQ "
        f"{session.primary_cq_decodes}/{session.comparison_cq_decodes}"
    )


class FT8CallPresentation(StrEnum):
    """Lifecycle presentation independent of Tk colors."""

    YELLOW = "yellow"
    WHITE = "white"
    GRAY = "gray"
    RED = "red"
    BLUE = "blue"


@dataclass(frozen=True, slots=True)
class FT8BrowserRow:
    callsign: str
    call_text: str
    pota_cq: bool
    snr_text: str
    audio_text: str
    grid_text: str
    selected: bool
    call_presentation: FT8CallPresentation
    friend_marker: str = ""
    attempt_state: FT8AttemptVisualState | None = None


@dataclass(frozen=True, slots=True)
class FT8BrowserViewport:
    headers: tuple[str, str, str, str]
    rows: tuple[FT8BrowserRow, ...]
    hidden_above: int = 0
    hidden_below: int = 0


@dataclass(frozen=True, slots=True)
class FT8IncomingCallPresentation:
    callsign: str
    snr_text: str
    grid_text: str


def present_ft8_incoming_call(
    incoming_call: FT8IncomingCall | None,
) -> FT8IncomingCallPresentation | None:
    """Build the hardware-free, glance-readable incoming-call alert."""
    if incoming_call is None:
        return None
    return FT8IncomingCallPresentation(
        callsign=incoming_call.callsign,
        snr_text=f"SNR {incoming_call.snr_db:+d} dB",
        grid_text=f"GRID {incoming_call.grid or '------'}",
    )


def build_ft8_browser_viewport(
    activity: tuple[FT8CQActivity, ...],
    *,
    current_period: FT8Period | None,
    selected_callsign: str | None,
    visible_rows: int = 5,
    attempt_states: dict[str, FT8AttemptVisualState] | None = None,
    friends: frozenset[str] = frozenset(),
    pending_ranking_callsigns: frozenset[str] = frozenset(),
) -> FT8BrowserViewport:
    """Build a stable-order viewport that always keeps selection visible."""
    if visible_rows < 1:
        raise ValueError("visible_rows must be at least 1")
    if current_period is None:
        return FT8BrowserViewport(headers=FT8_BROWSER_HEADERS, rows=())

    visible_activity = tuple(
        item
        for item in activity
        if 0 <= current_period.index - item.last_cq.index < 6
    )

    start = 0
    if len(visible_activity) > visible_rows and selected_callsign is not None:
        callsigns = tuple(item.callsign for item in visible_activity)
        try:
            selected_index = callsigns.index(selected_callsign)
        except ValueError:
            selected_index = 0
        start = max(0, selected_index - visible_rows + 1)

    visible = visible_activity[start : start + visible_rows]
    state_map = attempt_states or {}
    rows = tuple(
        _row(
            item,
            selected=item.callsign == selected_callsign,
            friends=friends,
            pending_rank=item.callsign in pending_ranking_callsigns,
            attempt_state=state_map.get(item.callsign),
            current_period=current_period,
        )
        for item in visible
    )
    return FT8BrowserViewport(
        headers=FT8_BROWSER_HEADERS,
        rows=rows,
        hidden_above=start,
        hidden_below=max(0, len(visible_activity) - (start + len(visible))),
    )


def _row(
    activity: FT8CQActivity,
    *,
    selected: bool,
    attempt_state: FT8AttemptVisualState | None,
    friends: frozenset[str],
    pending_rank: bool,
    current_period: FT8Period,
) -> FT8BrowserRow:
    if attempt_state is FT8AttemptVisualState.FAILED:
        presentation = FT8CallPresentation.RED
        call_text = f"! {activity.callsign}"
    elif attempt_state is FT8AttemptVisualState.ABORTED:
        presentation = FT8CallPresentation.BLUE
        call_text = f"■ {activity.callsign}"
    else:
        age = current_period.index - activity.last_cq.index
        if age <= 1:
            presentation = FT8CallPresentation.YELLOW
        elif age <= 3:
            presentation = FT8CallPresentation.WHITE
        else:
            presentation = FT8CallPresentation.GRAY
        call_text = activity.callsign

    return FT8BrowserRow(
        callsign=activity.callsign,
        friend_marker=friend_marker(activity.callsign, friends),
        call_text=f"NEW {call_text}" if pending_rank else call_text,
        pota_cq=activity.pota_cq,
        snr_text=f"{activity.snr_db:+d}",
        audio_text=str(activity.audio_frequency_hz),
        grid_text=activity.grid or "------",
        selected=selected,
        call_presentation=presentation,
        attempt_state=attempt_state,
    )
