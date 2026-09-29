import pytest

"""Forge callsign-intelligence aggregation tests."""

from rolling_thunder.forge_callsign_info import ForgeCallsignInfoService
from rolling_thunder.qrz_xml import QrzCallsignProfile
from rolling_thunder.wavelog import (
    WavelogConnectionError,
    WavelogQsoSummary,
    WavelogStationLocation,
)


class Clock:
    def __init__(self) -> None:
        self.value = 100.0

    def __call__(self) -> float:
        return self.value


class FakeQrz:
    def __init__(self, profile: QrzCallsignProfile | None) -> None:
        self.profile = profile
        self.calls: list[str] = []

    def lookup_profile(self, callsign: str) -> QrzCallsignProfile | None:
        self.calls.append(callsign)
        return self.profile


class FakeWavelog:
    def __init__(self, qso: WavelogQsoSummary | None) -> None:
        self.qso = qso
        self.history_calls: list[str] = []
        self.station_calls = 0

    def latest_qso(self, callsign: str) -> WavelogQsoSummary | None:
        self.history_calls.append(callsign)
        return self.qso

    def list_station_locations(self) -> tuple[WavelogStationLocation, ...]:
        self.station_calls += 1
        return (
            WavelogStationLocation(
                station_id=42,
                name="Mobile",
                gridsquare="EM79XM",
            ),
        )


def profile() -> QrzCallsignProfile:
    return QrzCallsignProfile(
        callsign="W1AW",
        name="Test Operator",
        image_url=None,
        grid="FN31pr",
        address2="Newington",
        state="CT",
        country="United States",
        latitude=41.7,
        longitude=-72.7,
        geoloc="geocode",
        license_class="E",
    )


def test_static_qrz_profile_uses_long_cache_independently_of_history() -> None:
    clock = Clock()
    qrz = FakeQrz(profile())
    wavelog = FakeWavelog(None)
    service = ForgeCallsignInfoService(
        qrz,
        wavelog,
        None,
        profile_ttl_s=1000,
        history_ttl_s=10,
        monotonic_clock=clock,
    )

    first = service.lookup("W1AW")
    clock.value += 11
    second = service.lookup("W1AW")

    assert first.profile is not None
    assert second.profile is not None
    assert qrz.calls == ["W1AW"]
    assert wavelog.history_calls == ["W1AW", "W1AW"]


def test_no_previous_qso_is_explicit_first_contact_state() -> None:
    service = ForgeCallsignInfoService(
        FakeQrz(profile()),
        FakeWavelog(None),
        None,
    )

    result = service.lookup("W1AW")

    assert result.last_qso.exists is False


def test_previous_mobile_qso_uses_station_location_name() -> None:
    qso = WavelogQsoSummary(
        callsign="W1AW",
        qso_id=1,
        station_id=42,
        occurred_at=None,
        comments="Worked while driving",
        notes=None,
        qth=None,
        grid="FN31PR",
        pota_reference=None,
        my_pota_reference=None,
    )
    service = ForgeCallsignInfoService(
        FakeQrz(profile()),
        FakeWavelog(qso),
        None,
    )

    result = service.lookup("W1AW")

    assert result.last_qso.exists is True
    assert result.last_qso.station_location == "Mobile"
    assert result.last_qso.mobile is True
    assert result.last_qso.comments == "Worked while driving"


def test_negative_qrz_result_uses_short_cache() -> None:
    clock = Clock()
    qrz = FakeQrz(None)
    service = ForgeCallsignInfoService(
        qrz,
        FakeWavelog(None),
        None,
        negative_profile_ttl_s=5,
        monotonic_clock=clock,
    )

    service.lookup("W1AW")
    clock.value += 4
    service.lookup("W1AW")
    clock.value += 2
    service.lookup("W1AW")

    assert qrz.calls == ["W1AW", "W1AW"]



class FailingWavelog(FakeWavelog):
    def latest_qso(self, callsign: str) -> WavelogQsoSummary | None:
        del callsign
        raise WavelogConnectionError("offline")


def test_wavelog_failure_is_not_reported_as_first_contact() -> None:
    service = ForgeCallsignInfoService(
        FakeQrz(profile()),
        FailingWavelog(None),
        None,
    )

    with pytest.raises(WavelogConnectionError):
        service.lookup("W1AW")
