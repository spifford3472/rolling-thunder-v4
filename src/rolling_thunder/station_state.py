"""Unified typed operational state for Rolling Thunder."""

from dataclasses import dataclass

from rolling_thunder.callsign_capture import CallsignCaptureState
from rolling_thunder.context_navigation import ContextNavigationState
from rolling_thunder.domain import RadioState
from rolling_thunder.gps import GPSConnectionState, GPSState
from rolling_thunder.maidenhead import maidenhead_grid
from rolling_thunder.station_health import StationHealthSnapshot, build_station_health
from rolling_thunder.value_types import MaidenheadGrid


@dataclass(frozen=True)
class StationState:
    """Immutable application read model consumed by presentation code."""

    radio: RadioState
    gps: GPSState | None
    grid: MaidenheadGrid | None
    callsign_capture: CallsignCaptureState
    context_navigation: ContextNavigationState
    health: StationHealthSnapshot


def _grid_from_gps(gps_state: GPSState | None) -> MaidenheadGrid | None:
    if gps_state is None:
        return None
    if gps_state.connection_state is not GPSConnectionState.CONNECTED:
        return None

    position = gps_state.position
    if position is None or position.latitude is None or position.longitude is None:
        return None
    return maidenhead_grid(position.latitude, position.longitude)


def build_station_state(
    radio_state: RadioState,
    callsign_capture: CallsignCaptureState,
    context_navigation: ContextNavigationState,
    *,
    speech_enabled: bool,
    gps_state: GPSState | None = None,
    logging_available: bool = True,
    storage_available: bool = True,
) -> StationState:
    """Combine current service state without performing I/O."""

    health = build_station_health(
        radio_state,
        callsign_capture,
        speech_enabled=speech_enabled,
        gps_state=gps_state,
        logging_available=logging_available,
        storage_available=storage_available,
    )

    return StationState(
        radio=radio_state,
        gps=gps_state,
        grid=_grid_from_gps(gps_state),
        callsign_capture=callsign_capture,
        context_navigation=context_navigation,
        health=health,
    )
