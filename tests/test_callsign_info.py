"""Focused tests for callsign information presentation and lifecycle."""

from collections.abc import Callable
from concurrent.futures import Executor, Future
from datetime import UTC, datetime
from typing import Any

from rolling_thunder.callsign_info import (
    CallsignInfoFailure,
    CallsignInfoLastQso,
    CallsignInfoProfile,
    CallsignInfoResponse,
    CallsignInfoWeather,
)
from rolling_thunder.callsign_info_client import (
    CallsignInfoClientError,
    HttpCallsignInfoClient,
)
from rolling_thunder.callsign_info_service import CallsignInfoLookupService
from rolling_thunder.callsign_info_ui import (
    build_callsign_info_presentation,
    build_local_callsign_info_presentation,
    callsign_info_failure_status,
    callsign_map_zoom,
)
from rolling_thunder.http_home_platform import UrllibHttpResponse


class InlineExecutor(Executor):
    def submit(self, fn: Callable[..., Any], *args: object, **kwargs: object) -> Future[Any]:
        future: Future[Any] = Future()
        future.set_result(fn(*args, **kwargs))
        return future


class DeferredExecutor(Executor):
    def __init__(self) -> None:
        self.jobs: list[
            tuple[Callable[..., Any], tuple[object, ...], dict[str, object], Future[Any]]
        ] = []

    def submit(
        self,
        fn: Callable[..., Any],
        /,
        *args: object,
        **kwargs: object,
    ) -> Future[Any]:
        future: Future[Any] = Future()
        self.jobs.append((fn, args, kwargs, future))
        return future

    def run(self, index: int) -> None:
        fn, args, kwargs, future = self.jobs[index]
        future.set_result(fn(*args, **kwargs))


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def lookup(
        self,
        callsign: str,
        *,
        pota_latitude: float | None = None,
        pota_longitude: float | None = None,
    ) -> CallsignInfoResponse:
        del pota_latitude, pota_longitude
        self.calls.append(callsign)
        return CallsignInfoResponse(
            callsign=callsign,
            profile=CallsignInfoProfile(
                callsign=callsign,
                name="Test Operator",
                country="United States",
                state="OH",
                latitude=39.5,
                longitude=-84.1,
            ),
            last_qso=CallsignInfoLastQso(exists=False),
            weather=CallsignInfoWeather(
                temperature_f=72,
                condition="CLOUDY",
                location_source="qrz",
            ),
        )


class FailingClient:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def lookup(
        self,
        callsign: str,
        *,
        pota_latitude: float | None = None,
        pota_longitude: float | None = None,
    ) -> CallsignInfoResponse:
        del callsign, pota_latitude, pota_longitude
        raise self.error


def test_first_contact_replaces_empty_history_section() -> None:
    response = CallsignInfoResponse(
        callsign="W1AW",
        last_qso=CallsignInfoLastQso(exists=False),
        weather=CallsignInfoWeather(
            temperature_f=72,
            condition="CLEAR",
            location_source="qrz",
            timezone="UTC",
        ),
    )

    presentation = build_callsign_info_presentation(
        response,
        local_time=datetime(2026, 9, 28, 20, 17, tzinfo=UTC),
    )

    assert presentation.history_heading == "FIRST CONTACT"
    assert presentation.history_line is None
    assert presentation.local_time_text == "LOCAL 20:17"


def test_target_local_time_uses_iana_timezone_with_dst() -> None:
    response = CallsignInfoResponse(
        callsign="W6RO",
        last_qso=CallsignInfoLastQso(exists=False),
        weather=CallsignInfoWeather(
            temperature_f=74,
            condition="CLEAR",
            location_source="qrz",
            timezone="America/Los_Angeles",
        ),
    )

    presentation = build_callsign_info_presentation(
        response,
        local_time=datetime(2026, 7, 15, 20, 0, tzinfo=UTC),
    )

    assert presentation.local_time_text == "LOCAL 13:00"


def test_target_local_time_is_hidden_when_timezone_is_unavailable() -> None:
    response = CallsignInfoResponse(
        callsign="DX1AA",
        last_qso=CallsignInfoLastQso(exists=False),
    )

    presentation = build_callsign_info_presentation(
        response,
        local_time=datetime(2026, 7, 15, 20, 0, tzinfo=UTC),
    )

    assert presentation.local_time_text == ""


def test_target_local_time_is_hidden_when_timezone_is_invalid() -> None:
    response = CallsignInfoResponse(
        callsign="DX1AA",
        last_qso=CallsignInfoLastQso(exists=False),
        weather=CallsignInfoWeather(
            temperature_f=70,
            condition="CLEAR",
            location_source="qrz",
            timezone="Not/A_Real_Zone",
        ),
    )

    presentation = build_callsign_info_presentation(
        response,
        local_time=datetime(2026, 7, 15, 20, 0, tzinfo=UTC),
    )

    assert presentation.local_time_text == ""


def test_license_is_separated_from_identity_for_call_header() -> None:
    response = CallsignInfoResponse(
        callsign="W1AW",
        profile=CallsignInfoProfile(
            callsign="W1AW",
            name="ARRL HQ",
            license_class="E",
            license_expiration_date="2030-01-01",
            country="United States",
            state="CT",
        ),
        last_qso=CallsignInfoLastQso(exists=False),
    )

    presentation = build_callsign_info_presentation(response)

    assert presentation.license_line == "License: E  Exp 2030-01-01"
    assert all(not line.startswith("License:") for line in presentation.identity_lines)
    assert all(not line.startswith("QSO Local Time:") for line in presentation.identity_lines)


def test_previous_contact_is_flattened_to_one_summary_line() -> None:
    response = CallsignInfoResponse(
        callsign="W8LRJ",
        last_qso=CallsignInfoLastQso(
            exists=True,
            occurred_at=datetime(2026, 9, 9, 14, 10, tzinfo=UTC),
            station_location="US-1456 - High Cliff State Park",
        ),
    )

    presentation = build_callsign_info_presentation(response)

    assert presentation.history_heading == "LAST CONTACT"
    assert presentation.history_line is not None
    assert "From: US-1456 - High Cliff State Park" in presentation.history_line
    assert "\n" not in presentation.history_line


def test_pota_location_wins_for_map_and_weather_context() -> None:
    response = CallsignInfoResponse(
        callsign="W1AW",
        profile=CallsignInfoProfile(
            callsign="W1AW",
            latitude=41.0,
            longitude=-72.0,
            country="United States",
            state="CT",
        ),
        last_qso=CallsignInfoLastQso(exists=False),
        weather=CallsignInfoWeather(
            temperature_f=55,
            condition="RAIN",
            location_source="pota",
        ),
    )

    presentation = build_callsign_info_presentation(
        response,
        pota_latitude=39.7,
        pota_longitude=-84.2,
    )

    assert presentation.target is not None
    assert presentation.target.latitude == 39.7
    assert presentation.target.longitude == -84.2
    assert presentation.weather_temperature == "55°F"
    assert presentation.weather_condition == "RAIN"


def test_one_pending_callsign_gets_only_one_lookup_even_after_timeout() -> None:
    client = FakeClient()
    now = [100.0]
    service = CallsignInfoLookupService(
        client,
        overlay_timeout_s=10.0,
        executor=InlineExecutor(),
        clock=lambda: now[0],
    )

    assert service.observe_callsign("W1AW") is True
    assert service.state.response is not None
    assert service.state.presentation_active is True
    now[0] = 111.0
    expired = service.state
    assert expired.response is None
    assert expired.presentation_active is False
    assert service.observe_callsign("W1AW") is False
    assert client.calls == ["W1AW"]


def test_failed_local_presentation_expires_without_retrying() -> None:
    now = [100.0]
    service = CallsignInfoLookupService(
        FailingClient(
            CallsignInfoClientError(CallsignInfoFailure.FORGE_UNREACHABLE)
        ),
        overlay_timeout_s=10.0,
        executor=InlineExecutor(),
        clock=lambda: now[0],
    )
    assert service.observe_callsign("W1AW") is True
    assert service.state.presentation_active is True
    assert service.state.failure is CallsignInfoFailure.FORGE_UNREACHABLE

    now[0] = 111.0

    assert service.state.presentation_active is False
    assert service.state.failure is None
    assert service.observe_callsign("W1AW") is False


def test_disable_hides_and_reenable_allows_current_callsign_to_lookup_again() -> None:
    client = FakeClient()
    service = CallsignInfoLookupService(
        client,
        executor=InlineExecutor(),
    )
    service.observe_callsign("W1AW")
    assert service.state.response is not None

    assert service.set_enabled(False) is True
    assert service.state.response is None
    assert service.state.enabled is False
    assert service.set_enabled(True) is True
    assert service.observe_callsign("W1AW") is True
    assert client.calls == ["W1AW", "W1AW"]


def test_missing_location_does_not_invent_map_pin() -> None:
    response = CallsignInfoResponse(
        callsign="W1AW",
        profile=CallsignInfoProfile(callsign="W1AW", name="Test Operator"),
        last_qso=CallsignInfoLastQso(exists=False),
    )

    presentation = build_callsign_info_presentation(response)

    assert presentation.target is None


def test_local_ft8_grid_presents_immediately_before_enrichment() -> None:
    presentation = build_local_callsign_info_presentation(
        "w1aw",
        target_grid="EM79xm",
    )

    assert presentation.callsign == "W1AW"
    assert presentation.target is not None
    assert presentation.pin_visible is True
    assert presentation.location_note == "APPROX FT8 GRID CENTER"
    assert presentation.service_status == "LOOKING UP LOCATION"


def test_local_invalid_grid_never_invents_location_or_pin() -> None:
    presentation = build_local_callsign_info_presentation(
        "W1AW",
        target_grid="NOT-A-GRID",
    )

    assert presentation.target is None
    assert presentation.pin_visible is False
    assert presentation.location_note is None


def test_failure_status_uses_only_published_network_evidence() -> None:
    assert (
        callsign_info_failure_status(
            CallsignInfoFailure.FORGE_UNREACHABLE,
            network_status="OFFLINE",
        )
        == "NETWORK UNAVAILABLE"
    )
    assert (
        callsign_info_failure_status(
            CallsignInfoFailure.FORGE_UNREACHABLE,
            network_status="ONLINE",
        )
        == "FORGE SERVICE NOT RESPONDING"
    )
    assert (
        callsign_info_failure_status(
            CallsignInfoFailure.FORGE_UNREACHABLE,
            network_status="UNKNOWN",
        )
        == "LOCATION SERVICE UNAVAILABLE"
    )
    assert (
        callsign_info_failure_status(
            CallsignInfoFailure.SERVICE_UNAVAILABLE,
            network_status="ONLINE",
        )
        == "LOCATION SERVICE UNAVAILABLE"
    )


def test_lookup_failure_publishes_only_safe_category() -> None:
    service = CallsignInfoLookupService(
        FailingClient(OSError("secret endpoint and credential detail")),
        executor=InlineExecutor(),
    )

    service.observe_callsign("W1AW")

    state = service.state
    assert state.failure is CallsignInfoFailure.SERVICE_UNAVAILABLE
    assert state.last_error == "service_unavailable"
    assert "secret" not in state.last_error


def test_http_client_classifies_transport_and_response_failures() -> None:
    class OfflineTransport:
        def request(self, *args: object, **kwargs: object) -> UrllibHttpResponse:
            del args, kwargs
            raise OSError("private network detail")

    offline = HttpCallsignInfoClient(
        "http://forge.invalid",
        transport=OfflineTransport(),
    )
    try:
        offline.lookup("W1AW")
    except CallsignInfoClientError as error:
        assert error.failure is CallsignInfoFailure.FORGE_UNREACHABLE
        assert "private" not in str(error)
    else:
        raise AssertionError("transport failure must raise")

    class InvalidTransport:
        def request(self, *args: object, **kwargs: object) -> UrllibHttpResponse:
            del args, kwargs
            return UrllibHttpResponse(200, b"not json")

    invalid = HttpCallsignInfoClient(
        "http://forge.invalid",
        transport=InvalidTransport(),
    )
    try:
        invalid.lookup("W1AW")
    except CallsignInfoClientError as error:
        assert error.failure is CallsignInfoFailure.SERVICE_UNAVAILABLE
    else:
        raise AssertionError("invalid response must raise")


def test_regional_map_framing_distinguishes_alaska_hawaii_and_large_dx() -> None:
    assert callsign_map_zoom("United States", "AK") == 4
    assert callsign_map_zoom("United States", "HI") == 6
    assert callsign_map_zoom("United States", "OH") == 6
    assert callsign_map_zoom("Australia", None) == 4
    assert callsign_map_zoom("Germany", None) == 5


def test_lookup_state_retains_pota_target_for_async_presentation() -> None:
    client = FakeClient()
    service = CallsignInfoLookupService(client, executor=InlineExecutor())

    service.observe_callsign(
        "W1AW",
        pota_latitude=39.7,
        pota_longitude=-84.2,
    )

    state = service.state
    assert state.target_latitude == 39.7
    assert state.target_longitude == -84.2


def test_late_response_for_replaced_callsign_cannot_resurrect_old_overlay() -> None:
    client = FakeClient()
    executor = DeferredExecutor()
    service = CallsignInfoLookupService(client, executor=executor)

    assert service.observe_callsign("K1AAA") is True
    assert service.observe_callsign("W1AW") is True

    executor.run(0)
    state_after_old = service.state
    assert state_after_old.callsign == "W1AW"
    assert state_after_old.response is None
    assert state_after_old.loading is True

    executor.run(1)
    final = service.state
    assert final.callsign == "W1AW"
    assert final.response is not None
    assert final.response.callsign == "W1AW"


def test_late_response_after_clear_cannot_resurrect_overlay() -> None:
    executor = DeferredExecutor()
    service = CallsignInfoLookupService(FakeClient(), executor=executor)
    assert service.observe_callsign("W1AW") is True
    assert executor.jobs[0][3].set_running_or_notify_cancel() is True

    service.clear()
    executor.run(0)

    state = service.state
    assert state.callsign is None
    assert state.response is None
    assert state.loading is False


def test_dxcc_center_can_frame_map_without_inventing_station_pin() -> None:
    response = CallsignInfoResponse(
        callsign="DX1AA",
        profile=CallsignInfoProfile(
            callsign="DX1AA",
            country="Example Country",
            latitude=10.0,
            longitude=20.0,
            coordinate_source="dxcc",
        ),
        last_qso=CallsignInfoLastQso(exists=False),
    )

    presentation = build_callsign_info_presentation(response)

    assert presentation.target is not None
    assert presentation.pin_visible is False
    assert presentation.location_note == "COUNTRY / REGION VIEW"


def test_ft8_target_grid_overrides_qrz_location_for_map_target() -> None:
    response = CallsignInfoResponse(
        callsign="W1AW",
        profile=CallsignInfoProfile(
            callsign="W1AW",
            country="United States",
            state="CT",
            latitude=41.0,
            longitude=-72.0,
            coordinate_source="qrz",
        ),
        last_qso=CallsignInfoLastQso(exists=False),
    )

    presentation = build_callsign_info_presentation(
        response,
        target_grid="EM79xm",
    )

    assert presentation.target is not None
    assert 39.0 < presentation.target.latitude < 40.0
    assert -85.0 < presentation.target.longitude < -83.0
    assert presentation.pin_visible is True
    assert presentation.location_note == "APPROX FT8 GRID CENTER"


def test_grid_center_fallback_is_marked_approximate() -> None:
    response = CallsignInfoResponse(
        callsign="W1AW",
        profile=CallsignInfoProfile(
            callsign="W1AW",
            country="United States",
            state="CT",
            grid="FN31pr",
        ),
        last_qso=CallsignInfoLastQso(exists=False),
    )

    presentation = build_callsign_info_presentation(response)

    assert presentation.target is not None
    assert presentation.pin_visible is True
    assert presentation.location_note == "APPROX GRID CENTER"


def test_friend_overlay_marker_does_not_change_contact_identity() -> None:
    from dataclasses import replace

    response = CallsignInfoResponse(callsign="W1ABC", last_qso=CallsignInfoLastQso(exists=False))
    clock = datetime(2026, 10, 4, tzinfo=UTC)
    ordinary = build_callsign_info_presentation(response, local_time=clock)
    decorated = build_callsign_info_presentation(response, local_time=clock, friends=frozenset({"W1ABC"}))
    assert decorated.friend_marker == "★"
    assert replace(decorated, friend_marker="") == ordinary
