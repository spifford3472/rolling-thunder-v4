"""Focused tests for callsign information presentation and lifecycle."""

from collections.abc import Callable
from concurrent.futures import Executor, Future
from datetime import UTC, datetime
from typing import Any

from rolling_thunder.callsign_info import (
    CallsignInfoLastQso,
    CallsignInfoProfile,
    CallsignInfoResponse,
    CallsignInfoWeather,
)
from rolling_thunder.callsign_info_service import CallsignInfoLookupService
from rolling_thunder.callsign_info_ui import build_callsign_info_presentation


class InlineExecutor(Executor):
    def submit(self, fn: Callable[..., Any], *args: object, **kwargs: object) -> Future[Any]:
        future: Future[Any] = Future()
        future.set_result(fn(*args, **kwargs))
        return future


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


def test_first_contact_replaces_empty_history_section() -> None:
    response = CallsignInfoResponse(
        callsign="W1AW",
        last_qso=CallsignInfoLastQso(exists=False),
    )

    presentation = build_callsign_info_presentation(
        response,
        local_time=datetime(2026, 9, 28, 20, 17, tzinfo=UTC),
    )

    assert presentation.history_heading == "FIRST CONTACT"
    assert presentation.history_lines == ()


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
    now[0] = 111.0
    assert service.state.response is None
    assert service.observe_callsign("W1AW") is False
    assert client.calls == ["W1AW"]


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
