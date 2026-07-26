"""Unified typed operational state for Rolling Thunder."""

from dataclasses import dataclass

from rolling_thunder.callsign_capture import CallsignCaptureState
from rolling_thunder.context_navigation import ContextNavigationState
from rolling_thunder.domain import RadioState
from rolling_thunder.station_health import StationHealthSnapshot, build_station_health


@dataclass(frozen=True)
class StationState:
    """Immutable application read model consumed by presentation code."""

    radio: RadioState
    callsign_capture: CallsignCaptureState
    context_navigation: ContextNavigationState
    health: StationHealthSnapshot


def build_station_state(
    radio_state: RadioState,
    callsign_capture: CallsignCaptureState,
    context_navigation: ContextNavigationState,
    *,
    speech_enabled: bool,
    logging_available: bool = True,
    storage_available: bool = True,
) -> StationState:
    """Combine current service state without performing I/O."""

    health = build_station_health(
        radio_state,
        callsign_capture,
        speech_enabled=speech_enabled,
        logging_available=logging_available,
        storage_available=storage_available,
    )

    return StationState(
        radio=radio_state,
        callsign_capture=callsign_capture,
        context_navigation=context_navigation,
        health=health,
    )
