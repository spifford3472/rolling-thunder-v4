"""Tests for Wavelog v2 previous-QSO reads used by callsign information."""

from collections.abc import Mapping
from json import dumps

import pytest
from pydantic import SecretStr

from rolling_thunder.http_home_platform import UrllibHttpResponse
from rolling_thunder.wavelog import WavelogClient, WavelogResponseError


class ScriptedTransport:
    def __init__(self, responses: list[UrllibHttpResponse]) -> None:
        self.responses = responses
        self.requests: list[tuple[str, str, Mapping[str, str], bytes | None, float]] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout_s: float,
    ) -> UrllibHttpResponse:
        self.requests.append((method, url, headers, body, timeout_s))
        return self.responses.pop(0)


def response(payload: object) -> UrllibHttpResponse:
    return UrllibHttpResponse(200, dumps(payload).encode())


def client(transport: ScriptedTransport) -> WavelogClient:
    return WavelogClient(
        "http://wavelog:8086",
        SecretStr("secret"),
        station_location_name="Mobile",
        transport=transport,
    )


def test_latest_qso_returns_none_for_first_contact() -> None:
    transport = ScriptedTransport([response({"data": []})])

    assert client(transport).latest_qso("W1AW") is None

    method, url, headers, body, _ = transport.requests[0]
    assert method == "GET"
    assert body is None
    assert "callsign=W1AW" in url
    assert "limit=1" in url
    assert headers["Authorization"] == "Bearer secret"


def test_latest_qso_normalizes_history_fields() -> None:
    transport = ScriptedTransport(
        [
            response(
                {
                    "data": [
                        {
                            "id": 123,
                            "station_id": 42,
                            "call": "W1AW",
                            "qso_date": "2026-09-28 20:17:00",
                            "comment": "Worked mobile",
                            "notes": "Previous note",
                            "qth": "Newington",
                            "gridsquare": "FN31PR",
                            "pota_ref": "US-1234",
                            "my_pota_ref": "US-5678",
                        }
                    ]
                }
            )
        ]
    )

    qso = client(transport).latest_qso("W1AW")

    assert qso is not None
    assert qso.station_id == 42
    assert qso.occurred_at is not None
    assert qso.occurred_at.strftime("%Y%m%d%H%M%S") == "20260928201700"
    assert qso.comments == "Worked mobile"
    assert qso.pota_reference == "US-1234"
    assert qso.my_pota_reference == "US-5678"


def test_station_locations_return_names_for_historical_station_ids() -> None:
    transport = ScriptedTransport(
        [
            response(
                {
                    "data": [
                        {
                            "id": 1,
                            "uuid": "home",
                            "name": "Home",
                            "callsign": "KI5VNB",
                            "gridsquare": "EM79XM",
                            "dxcc": 291,
                            "cq": 4,
                            "itu": 8,
                            "state": "OH",
                        },
                        {
                            "id": 42,
                            "uuid": "mobile",
                            "name": "Mobile",
                            "callsign": "KI5VNB",
                            "gridsquare": "EM89LX",
                            "dxcc": 291,
                            "cq": 4,
                            "itu": 8,
                            "state": "OH",
                        },
                    ]
                }
            )
        ]
    )

    locations = client(transport).list_station_locations()

    assert [(item.station_id, item.name) for item in locations] == [
        (1, "Home"),
        (42, "Mobile"),
    ]


def test_latest_qso_uses_total_across_pages_and_latest_band_without_extra_requests():
    transport = ScriptedTransport([response({
        "data": [{"call": "W1AW", "band": "20m", "id": 123}],
        "meta": {"count": 1, "total": 12, "per_page": 1, "has_more": True},
    })])
    qso = client(transport).latest_qso("w1aw")
    assert qso is not None
    assert qso.worked_count == 12
    assert qso.band == "20m"
    assert len(transport.requests) == 1
    url = transport.requests[0][1]
    assert "callsign=W1AW" in url
    assert "station_id" not in url and "band=" not in url and "mode=" not in url


@pytest.mark.parametrize("total", [True, -1, "12", 0])
def test_invalid_or_contradictory_worked_total_fails_closed(total):
    transport = ScriptedTransport([response({
        "data": [{"call": "W1AW"}], "meta": {"total": total},
    })])
    with pytest.raises(WavelogResponseError):
        client(transport).latest_qso("W1AW")


def test_positive_total_with_empty_data_is_not_first_contact():
    transport = ScriptedTransport([response({"data": [], "meta": {"total": 12}})])
    with pytest.raises(WavelogResponseError):
        client(transport).latest_qso("W1AW")


def test_old_history_response_has_unknown_count_and_band_not_an_invented_one():
    transport = ScriptedTransport([response({"data": [{"call": "W1AW"}]})])
    qso = client(transport).latest_qso("W1AW")
    assert qso is not None and qso.worked_count is None and qso.band is None
