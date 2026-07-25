"""Pure presentation state for the persistent dashboard."""

from dataclasses import dataclass

from rolling_thunder.callsign_capture import CallsignCaptureState
from rolling_thunder.domain import Frequency, RadioConnectionState, RadioState


@dataclass(frozen=True)
class DashboardState:
    """Text values displayed by the first Milestone 5 dashboard shell."""

    pending_callsign: str
    voice_state: str
    radio_state: str
    frequency: str
    band: str
    mode: str
    commit_state: str
    last_result: str
    ticker: str


def _format_frequency(frequency: Frequency | None) -> str:
    if frequency is None:
        return "---.--- MHz"
    return f"{frequency.hz / 1_000_000:.3f} MHz"


def _format_band(frequency: Frequency | None) -> str:
    if frequency is None:
        return "--"
    mhz = frequency.hz / 1_000_000
    ranges = (
        (1.8, 2.0, "160 m"),
        (3.5, 4.0, "80 m"),
        (5.3, 5.5, "60 m"),
        (7.0, 7.3, "40 m"),
        (10.1, 10.15, "30 m"),
        (14.0, 14.35, "20 m"),
        (18.068, 18.168, "17 m"),
        (21.0, 21.45, "15 m"),
        (24.89, 24.99, "12 m"),
        (28.0, 29.7, "10 m"),
        (50.0, 54.0, "6 m"),
    )
    for lower, upper, label in ranges:
        if lower <= mhz <= upper:
            return label
    return "Out of band"


def build_dashboard_state(
    radio_state: RadioState,
    callsign_capture: CallsignCaptureState | None = None,
) -> DashboardState:
    """Convert domain and callsign state into stable UI-facing text."""
    capture = callsign_capture or CallsignCaptureState()
    connected = radio_state.connection_state is RadioConnectionState.CONNECTED
    mode = radio_state.mode.value if radio_state.mode is not None else "--"
    if connected:
        ticker = "RADIO CONNECTED — MOCK VOICE READY"
    elif radio_state.last_error:
        ticker = f"RADIO ERROR — {radio_state.last_error}"
    else:
        ticker = "RADIO DISCONNECTED — LOGGING DISABLED"

    return DashboardState(
        pending_callsign=capture.pending_callsign or "—",
        voice_state=capture.voice_state,
        radio_state=radio_state.connection_state.value.upper(),
        frequency=_format_frequency(radio_state.frequency),
        band=_format_band(radio_state.frequency),
        mode=mode,
        commit_state=capture.commit_state,
        last_result=capture.last_result,
        ticker=ticker,
    )
