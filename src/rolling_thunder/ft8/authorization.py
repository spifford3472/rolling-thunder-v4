"""Freeze one explicit CQ selection into an immutable FT8 QSO authorization."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from rolling_thunder.domain import GPSFixState, RadioConnectionState, RadioMode, RadioState
from rolling_thunder.ft8.domain import FT8CQActivity, FT8Period, FT8PeriodParity, FT8QsoContext
from rolling_thunder.ft8.timing import FT8Clock
from rolling_thunder.gps import GPSConnectionState, GPSState
from rolling_thunder.local_jurisdiction import LocalJurisdictionResolver
from rolling_thunder.maidenhead import maidenhead_grid
from rolling_thunder.radio_band import RadioBandResolutionError, resolve_radio_band
from rolling_thunder.value_types import BaseCallsign, MaidenheadGrid

FT8_CQ_MAX_AGE_PERIODS = 5
FT8_QSO_ALLOWED_RADIO_MODES = frozenset({RadioMode.DATA, RadioMode.USB})


class FT8QsoAuthorizationError(RuntimeError):
    """Selection cannot safely become a transmit-authorized QSO."""


@dataclass(frozen=True, slots=True)
class FT8QsoAuthorizationService:
    """Build a frozen context from one explicit CQ selection and current state."""

    local_callsign: BaseCallsign
    home_grid: MaidenheadGrid
    clock: FT8Clock
    jurisdiction_resolver: LocalJurisdictionResolver | None = None

    def authorize(
        self,
        activity: FT8CQActivity,
        *,
        radio_state: RadioState,
        gps_state: GPSState | None,
        qso_id: UUID | None = None,
        freshness_reference_period: FT8Period | None = None,
        selection_freshness_validated: bool = False,
        tx_power_target_watts: int = 20,
        tx_power_start_watts: int | None = None,
    ) -> FT8QsoContext:
        """Freeze one selected CQ without tuning, keying, or starting a QSO."""
        current_period = self.clock.current_period()
        if not selection_freshness_validated:
            self.validate_selection_freshness(
                activity,
                selection_period=freshness_reference_period or current_period,
                current_period=current_period,
            )
        if not 20 <= tx_power_target_watts <= 70 or tx_power_target_watts % 5:
            raise FT8QsoAuthorizationError(
                "FT8 initial power target must be a 5 W step between 20 and 70 W"
            )

        if radio_state.connection_state is not RadioConnectionState.CONNECTED:
            raise FT8QsoAuthorizationError("FT8 QSO authorization requires a connected radio")
        if radio_state.transmitting:
            raise FT8QsoAuthorizationError("FT8 QSO authorization requires the radio in receive")
        if radio_state.frequency is None or radio_state.mode is None:
            raise FT8QsoAuthorizationError("FT8 QSO authorization requires known radio state")
        if radio_state.mode not in FT8_QSO_ALLOWED_RADIO_MODES:
            raise FT8QsoAuthorizationError(
                "FT8 QSO authorization requires DATA or USB mode"
            )

        try:
            band = resolve_radio_band(radio_state.frequency)
        except RadioBandResolutionError as exc:
            raise FT8QsoAuthorizationError("radio frequency is outside a supported band") from exc

        if not -50 <= activity.snr_db <= 49:
            raise FT8QsoAuthorizationError(
                "selected CQ signal report is outside the FT8 report range"
            )

        local_grid, latitude, longitude, location_label = freeze_ft8_location(
            gps_state,
            self.home_grid,
        )
        jurisdiction = (
            self.jurisdiction_resolver.resolve(latitude, longitude)
            if self.jurisdiction_resolver is not None
            and latitude is not None
            and longitude is not None
            else None
        )
        authorized_utc = self.clock.now_utc()
        if self.clock.current_period() != current_period:
            raise FT8QsoAuthorizationError("FT8 period changed during authorization")

        return FT8QsoContext(
            local_callsign=str(self.local_callsign),
            remote_callsign=activity.callsign,
            target_audio_frequency_hz=activity.audio_frequency_hz,
            radio_frequency_hz=radio_state.frequency.hz,
            radio_band=band.value,
            radio_mode=radio_state.mode.value,
            local_grid=local_grid,
            tx_parity=_opposite_parity(activity.last_period.parity),
            authorized_period=current_period,
            authorized_utc=authorized_utc,
            signal_report_db=activity.snr_db,
            latitude=latitude,
            longitude=longitude,
            local_state=jurisdiction.state if jurisdiction is not None else None,
            local_cq_zone=jurisdiction.cq_zone if jurisdiction is not None else None,
            local_itu_zone=jurisdiction.itu_zone if jurisdiction is not None else None,
            location_label=location_label,
            remote_grid=activity.grid,
            pota_cq=activity.pota_cq,
            tx_power_target_watts=tx_power_target_watts,
            tx_power_start_watts=tx_power_start_watts,
            **({} if qso_id is None else {"qso_id": qso_id}),
        )

    def validate_selection_freshness(
        self,
        activity: FT8CQActivity,
        *,
        selection_period: FT8Period,
        current_period: FT8Period | None = None,
    ) -> None:
        """Fail closed at operator selection, before any CAT preparation delay."""
        observed_current = current_period or self.clock.current_period()
        if selection_period.index > observed_current.index:
            raise FT8QsoAuthorizationError(
                "FT8 freshness reference period cannot be in the future"
            )
        age_periods = selection_period.index - activity.last_period.index
        if age_periods < 0:
            raise FT8QsoAuthorizationError("selected FT8 CQ is from a future period")
        if age_periods > FT8_CQ_MAX_AGE_PERIODS:
            raise FT8QsoAuthorizationError("selected FT8 CQ is stale")

def freeze_ft8_location(
    gps_state: GPSState | None,
    home_grid: MaidenheadGrid,
) -> tuple[str, float | None, float | None, str]:
    """Freeze the current mobile grid or configured home-grid fallback."""
    if (
        gps_state is not None
        and gps_state.connection_state is GPSConnectionState.CONNECTED
        and gps_state.position is not None
        and gps_state.position.fix_state is not GPSFixState.NO_FIX
        and gps_state.position.latitude is not None
        and gps_state.position.longitude is not None
    ):
        latitude = gps_state.position.latitude
        longitude = gps_state.position.longitude
        return (
            str(maidenhead_grid(latitude, longitude)),
            latitude,
            longitude,
            "GPS",
        )
    return str(home_grid), None, None, "configured home grid"


def _opposite_parity(parity: FT8PeriodParity) -> FT8PeriodParity:
    if parity is FT8PeriodParity.EVEN:
        return FT8PeriodParity.ODD
    return FT8PeriodParity.EVEN
