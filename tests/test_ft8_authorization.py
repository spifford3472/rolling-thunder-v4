"""Tests for freezing one selected CQ into one QSO authorization."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from rolling_thunder.contact_logging import ContactLoggingService
from rolling_thunder.contact_repository import ContactRepository
from rolling_thunder.domain import (
    Frequency,
    GPSFixState,
    GPSPosition,
    RadioConnectionState,
    RadioMode,
    RadioState,
)
from rolling_thunder.ft8.authorization import (
    FT8QsoAuthorizationError,
    FT8QsoAuthorizationService,
)
from rolling_thunder.ft8.coordinator import FT8QsoResult
from rolling_thunder.ft8.domain import (
    FT8_PERIOD_SECONDS,
    FT8CQActivity,
    FT8Period,
    FT8PeriodParity,
    FT8QsoState,
)
from rolling_thunder.ft8.logging import FT8QsoLoggingService
from rolling_thunder.ft8.timing import FakeFT8Clock
from rolling_thunder.gps import GPSConnectionState, GPSState
from rolling_thunder.local_jurisdiction import LocalJurisdictionResolver, StateBoundary


def _activity(*, period: int = 100, snr_db: int = -10) -> FT8CQActivity:
    return FT8CQActivity(
        callsign="K1ABC",
        last_period=FT8Period(period),
        snr_db=snr_db,
        dt_seconds=0.1,
        audio_frequency_hz=1500,
        grid="FN31",
    )


def _radio(*, mode: RadioMode = RadioMode.DATA, transmitting: bool = False) -> RadioState:
    return RadioState(
        connection_state=RadioConnectionState.CONNECTED,
        frequency=Frequency(hz=14_074_000),
        mode=mode,
        transmitting=transmitting,
        updated_at=datetime(2026, 9, 30, tzinfo=UTC),
    )


def _gps() -> GPSState:
    updated = datetime(2026, 9, 30, tzinfo=UTC)
    return GPSState(
        connection_state=GPSConnectionState.CONNECTED,
        position=GPSPosition(
            fix_state=GPSFixState.THREE_DIMENSIONAL,
            latitude=39.529,
            longitude=-84.087,
            altitude_m=250.0,
            updated_at=updated,
        ),
        updated_at=updated,
    )


def _resolver() -> LocalJurisdictionResolver:
    return LocalJurisdictionResolver(
        (
            StateBoundary(
                state="OH",
                polygons=((((-85.0, 38.0), (-80.0, 38.0), (-80.0, 42.0), (-85.0, 42.0)),),),
            ),
            StateBoundary(
                state="IN",
                polygons=((((-90.0, 38.0), (-85.0, 38.0), (-85.0, 42.0), (-90.0, 42.0)),),),
            ),
        )
    )


def _service(period: int = 100) -> FT8QsoAuthorizationService:
    return FT8QsoAuthorizationService(
        local_callsign="KI5VNB",
        home_grid="EM79xm",
        clock=FakeFT8Clock(FT8Period(period).start_utc + timedelta(seconds=1)),
        jurisdiction_resolver=_resolver(),
    )


def test_authorization_freezes_selected_cq_radio_and_gps() -> None:
    service = _service(100)

    context = service.authorize(_activity(), radio_state=_radio(), gps_state=_gps())

    assert context.local_callsign == "KI5VNB"
    assert context.remote_callsign == "K1ABC"
    assert context.target_audio_frequency_hz == 1500
    assert context.radio_frequency_hz == 14_074_000
    assert context.radio_band == "20m"
    assert context.radio_mode == "DATA"
    assert context.local_grid.startswith("EM79")
    assert context.tx_parity is FT8PeriodParity.ODD
    assert context.signal_report_db == -10
    assert context.latitude == pytest.approx(39.529)
    assert context.longitude == pytest.approx(-84.087)
    assert (context.local_state, context.local_cq_zone, context.local_itu_zone) == ("OH", 4, 8)
    assert context.location_label == "GPS"


def test_authorization_accepts_usb_and_freezes_mode() -> None:
    service = _service(100)

    context = service.authorize(
        _activity(),
        radio_state=_radio(mode=RadioMode.USB),
        gps_state=None,
    )

    assert context.radio_mode == "USB"


def test_authorization_explicitly_falls_back_to_configured_home_grid() -> None:
    service = _service(100)

    context = service.authorize(_activity(), radio_state=_radio(), gps_state=None)

    assert context.local_grid == "EM79xm"
    assert context.latitude is None
    assert context.longitude is None
    assert context.local_state is None
    assert context.local_cq_zone is None
    assert context.local_itu_zone is None
    assert context.location_label == "configured home grid"


@pytest.mark.parametrize(
    ("radio_state", "message"),
    [
        (_radio(mode=RadioMode.LSB), "DATA or USB mode"),
        (_radio(transmitting=True), "radio in receive"),
        (
            RadioState(
                connection_state=RadioConnectionState.DISCONNECTED,
                updated_at=datetime(2026, 9, 30, tzinfo=UTC),
            ),
            "connected radio",
        ),
    ],
)
def test_authorization_rejects_unsafe_radio_state(
    radio_state: RadioState,
    message: str,
) -> None:
    with pytest.raises(FT8QsoAuthorizationError, match=message):
        _service().authorize(_activity(), radio_state=radio_state, gps_state=None)


def test_authorization_uses_frozen_selection_period_for_freshness() -> None:
    service = _service(105)

    context = service.authorize(
        _activity(period=100),
        radio_state=_radio(mode=RadioMode.USB),
        gps_state=None,
        freshness_reference_period=FT8Period(104),
    )

    assert context.remote_callsign == "K1ABC"
    assert context.radio_mode == "USB"


def test_valid_selection_remains_accepted_after_several_preparation_periods() -> None:
    clock = FakeFT8Clock(FT8Period(104).start_utc + timedelta(seconds=1))
    service = FT8QsoAuthorizationService(
        local_callsign="KI5VNB",
        home_grid="EM79xm",
        clock=clock,
    )
    activity = _activity(period=100)
    service.validate_selection_freshness(
        activity,
        selection_period=FT8Period(104),
    )

    clock.advance(FT8_PERIOD_SECONDS * 8)
    context = service.authorize(
        activity,
        radio_state=_radio(mode=RadioMode.USB),
        gps_state=None,
        selection_freshness_validated=True,
        tx_power_target_watts=35,
        tx_power_start_watts=35,
    )

    assert context.remote_callsign == "K1ABC"
    assert context.authorized_period == FT8Period(112)
    assert context.tx_power_target_watts == 35
    assert context.tx_power_start_watts == 35


def test_authorization_accepts_cq_through_fifth_age_period() -> None:
    context = _service(105).authorize(
        _activity(period=100),
        radio_state=_radio(mode=RadioMode.USB),
        gps_state=None,
    )

    assert context.remote_callsign == "K1ABC"


def test_authorization_rejects_stale_selected_cq() -> None:
    with pytest.raises(FT8QsoAuthorizationError, match="stale"):
        _service(106).authorize(_activity(period=100), radio_state=_radio(), gps_state=None)


def test_authorization_rejects_report_outside_protocol_range() -> None:
    with pytest.raises(FT8QsoAuthorizationError, match="report range"):
        _service().authorize(_activity(snr_db=-51), radio_state=_radio(), gps_state=None)


def test_authorized_location_survives_movement_and_next_qso(tmp_path: Path) -> None:
    service = _service()
    now = datetime(2026, 9, 30, tzinfo=UTC)

    def gps(latitude: float, longitude: float) -> GPSState:
        return GPSState(
            connection_state=GPSConnectionState.CONNECTED,
            position=GPSPosition(
                fix_state=GPSFixState.THREE_DIMENSIONAL,
                latitude=latitude,
                longitude=longitude,
                updated_at=now,
            ),
            updated_at=now,
        )

    current = gps(39.5309, -84.0866)
    first = service.authorize(_activity(), radio_state=_radio(), gps_state=current)
    current = gps(39.9, -86.0)
    second = service.authorize(_activity(), radio_state=_radio(), gps_state=current)
    repository = ContactRepository(tmp_path / "contacts.db")
    logger = FT8QsoLoggingService(ContactLoggingService(repository))
    for context in (first, second):
        result = FT8QsoResult(
            status=FT8QsoState.COMPLETED,
            context=context,
            sent_report_db=14,
            received_report_db=-10,
            started_utc=now,
            ended_utc=now + timedelta(seconds=75),
            terminal_reason=None,
        )
        logged = logger.handle_terminal_result(result)
        assert logged is not None
        assert logged.my_grid == context.local_grid
        assert (logged.my_latitude, logged.my_longitude) == (context.latitude, context.longitude)
        assert (logged.my_state, logged.my_cq_zone, logged.my_itu_zone) == (
            context.local_state,
            context.local_cq_zone,
            context.local_itu_zone,
        )
    assert (
        repository.get(first.qso_id).my_latitude,
        repository.get(first.qso_id).my_longitude,
    ) == (39.5309, -84.0866)
    assert (
        repository.get(second.qso_id).my_latitude,
        repository.get(second.qso_id).my_longitude,
    ) == (39.9, -86.0)
    assert (
        repository.get(first.qso_id).my_state,
        repository.get(first.qso_id).my_cq_zone,
        repository.get(first.qso_id).my_itu_zone,
    ) == ("OH", 4, 8)
    assert (
        repository.get(second.qso_id).my_state,
        repository.get(second.qso_id).my_cq_zone,
        repository.get(second.qso_id).my_itu_zone,
    ) == ("IN", 4, 8)
