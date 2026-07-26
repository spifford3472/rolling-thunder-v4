"""Pure station-health read model for the dashboard."""

from dataclasses import dataclass
from enum import StrEnum

from rolling_thunder.callsign_capture import CallsignCaptureState
from rolling_thunder.domain import GPSFixState, RadioConnectionState, RadioState
from rolling_thunder.gps import GPSConnectionState, GPSState


class HealthStatus(StrEnum):
    """Stable operator-facing health states."""

    READY = "READY"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"
    DISABLED = "DISABLED"


@dataclass(frozen=True)
class HealthItem:
    """Health state for one currently implemented subsystem."""

    label: str
    status: HealthStatus
    detail: str = ""


@dataclass(frozen=True)
class StationHealthSnapshot:
    """Immutable station-health snapshot consumed by presentation code."""

    radio: HealthItem
    gps: HealthItem
    voice: HealthItem
    logging: HealthItem
    storage: HealthItem
    overall: HealthStatus

    @property
    def items(self) -> tuple[HealthItem, ...]:
        """Return configured subsystem rows in dashboard display order."""
        required_items = (self.radio, self.voice, self.logging, self.storage)
        if self.gps.status is HealthStatus.DISABLED:
            return required_items
        return (self.radio, self.gps, self.voice, self.logging, self.storage)


def _radio_health(radio_state: RadioState) -> HealthItem:
    if radio_state.connection_state is RadioConnectionState.CONNECTED:
        return HealthItem("Radio", HealthStatus.READY)
    if radio_state.last_error:
        return HealthItem("Radio", HealthStatus.UNAVAILABLE, radio_state.last_error)
    return HealthItem("Radio", HealthStatus.UNAVAILABLE, "Disconnected")


def _gps_health(gps_state: GPSState | None) -> HealthItem:
    if gps_state is None:
        return HealthItem("GPS", HealthStatus.DISABLED, "Not configured")
    if gps_state.connection_state is GPSConnectionState.ERROR:
        return HealthItem(
            "GPS",
            HealthStatus.UNAVAILABLE,
            gps_state.last_error or "Receiver error",
        )
    if gps_state.connection_state is GPSConnectionState.DISCONNECTED:
        return HealthItem("GPS", HealthStatus.UNAVAILABLE, "Disconnected")

    position = gps_state.position
    if position is None or position.fix_state is GPSFixState.NO_FIX:
        return HealthItem("GPS", HealthStatus.DEGRADED, "No fix")
    return HealthItem("GPS", HealthStatus.READY, position.fix_state.value.upper())


def _voice_health(
    capture: CallsignCaptureState,
    *,
    speech_enabled: bool,
) -> HealthItem:
    if not speech_enabled:
        return HealthItem("Voice", HealthStatus.DISABLED, "Disabled by configuration")

    voice_state = capture.voice_state.upper()
    if voice_state in {"ACTIVE", "CAPTURING", "LISTENING", "RECORDING"}:
        return HealthItem("Voice", HealthStatus.READY, "Listening")
    if voice_state in {"FAILED", "ERROR", "UNAVAILABLE"}:
        return HealthItem("Voice", HealthStatus.DEGRADED, "Recognition error")
    return HealthItem("Voice", HealthStatus.READY)


def _availability_health(label: str, available: bool, unavailable_detail: str) -> HealthItem:
    if available:
        return HealthItem(label, HealthStatus.READY)
    return HealthItem(label, HealthStatus.UNAVAILABLE, unavailable_detail)


def build_station_health(
    radio_state: RadioState,
    callsign_capture: CallsignCaptureState | None = None,
    *,
    speech_enabled: bool,
    gps_state: GPSState | None = None,
    logging_available: bool = True,
    storage_available: bool = True,
) -> StationHealthSnapshot:
    """Build current health without performing I/O or touching UI state."""
    capture = callsign_capture or CallsignCaptureState()
    radio = _radio_health(radio_state)
    gps = _gps_health(gps_state)
    voice = _voice_health(capture, speech_enabled=speech_enabled)
    logging = _availability_health("Logging", logging_available, "Service unavailable")
    storage = _availability_health("Storage", storage_available, "Database unavailable")

    required = (radio.status, logging.status, storage.status)
    optional = (gps.status, voice.status)
    if HealthStatus.UNAVAILABLE in required:
        overall = HealthStatus.UNAVAILABLE
    elif any(
        status in {HealthStatus.DEGRADED, HealthStatus.UNAVAILABLE}
        for status in optional
    ) or voice.status is HealthStatus.DISABLED:
        overall = HealthStatus.DEGRADED
    else:
        overall = HealthStatus.READY

    return StationHealthSnapshot(
        radio=radio,
        gps=gps,
        voice=voice,
        logging=logging,
        storage=storage,
        overall=overall,
    )
