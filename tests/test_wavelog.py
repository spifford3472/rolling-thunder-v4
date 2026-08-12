"""Tests for Forge-local Wavelog target resolution and contact mapping."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from json import dumps, loads
from typing import Final

import pytest
from pydantic import SecretStr

from rolling_thunder.domain import Contact, RadioMode
from rolling_thunder.http_home_platform import UrllibHttpResponse
from rolling_thunder.wavelog import (
    WavelogAuthenticationError,
    WavelogClient,
    WavelogStationLocationError,
    WavelogUploadDisposition,
    contact_to_adif,
)


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
        assert self.responses
        return self.responses.pop(0)


CONTACT_ID: Final = "11111111-2222-3333-4444-555555555555"


def contact() -> Contact:
    return Contact(
        contact_id=CONTACT_ID,
        callsign="W1AW",
        frequency_hz=14_250_125,
        mode=RadioMode.USB,
        started_at=datetime(2026, 8, 12, 15, 4, 5, tzinfo=UTC),
        rst_sent="59",
        rst_received="57",
        grid="FN31pr",
        my_grid="EM79xm",
        pota_reference="US-0732",
        notes="POTA US-0732",
    )


def station_response(*locations: dict[str, object]) -> UrllibHttpResponse:
    return UrllibHttpResponse(200, dumps({"data": list(locations)}).encode())


def test_contact_to_adif_preserves_required_qso_fields() -> None:
    adif = contact_to_adif(contact())

    for expected in (
        "<CALL:4>W1AW",
        "<BAND:3>20m",
        "<MODE:3>SSB",
        "<SUBMODE:3>USB",
        "<FREQ:9>14.250125",
        "<QSO_DATE:8>20260812",
        "<TIME_ON:6>150405",
        "<RST_SENT:2>59",
        "<RST_RCVD:2>57",
        "<GRIDSQUARE:6>FN31pr",
        "<MY_GRIDSQUARE:6>EM79xm",
        "<POTA_REF:7>US-0732",
        "<NOTES:12>POTA US-0732",
        "<EOR>",
    ):
        assert expected in adif


def test_mobile_station_location_is_resolved_by_name_not_assumed_id() -> None:
    transport = ScriptedTransport(
        [
            station_response(
                {"id": 17, "uuid": "home", "name": "Home"},
                {"id": 42, "uuid": "mobile", "name": "Mobile"},
            )
        ]
    )
    client = WavelogClient(
        "http://wavelog:8086",
        SecretStr("secret"),
        station_location_name="Mobile",
        transport=transport,
    )

    location = client.resolve_station_location()

    assert location.station_id == 42
    assert location.name == "Mobile"
    _, url, headers, _, _ = transport.requests[0]
    assert url.endswith("/index.php/api/v2/station")
    assert headers["Authorization"] == "Bearer secret"


def test_missing_or_ambiguous_mobile_station_location_is_rejected() -> None:
    for locations in (
        ({"id": 1, "name": "Home"},),
        ({"id": 2, "name": "Mobile"}, {"id": 3, "name": "Mobile"}),
    ):
        client = WavelogClient(
            "http://wavelog:8086",
            SecretStr("secret"),
            station_location_name="Mobile",
            transport=ScriptedTransport([station_response(*locations)]),
        )
        with pytest.raises(WavelogStationLocationError):
            client.resolve_station_location()


def test_qso_import_targets_resolved_mobile_profile_and_accepts_import() -> None:
    transport = ScriptedTransport(
        [
            station_response({"id": 42, "name": "Mobile"}),
            UrllibHttpResponse(
                200,
                dumps({"data": {"parsed": 1, "imported": 1, "skipped": 0}}).encode(),
            ),
        ]
    )
    client = WavelogClient(
        "http://wavelog:8086",
        SecretStr("secret"),
        station_location_name="Mobile",
        transport=transport,
    )

    result = client.upload_contact(contact())

    assert result is WavelogUploadDisposition.IMPORTED
    method, url, _, body, _ = transport.requests[1]
    assert method == "POST"
    assert url.endswith("/index.php/api/v2/qso")
    assert body is not None
    payload = loads(body)
    assert payload["station_profile_id"] == 42
    assert payload["import_type"] == "adif"
    assert "W1AW" in payload["adif"]


def test_wavelog_duplicate_is_a_successful_idempotent_outcome() -> None:
    transport = ScriptedTransport(
        [
            station_response({"id": 42, "name": "Mobile"}),
            UrllibHttpResponse(
                200,
                dumps({"data": {"parsed": 1, "imported": 0, "skipped": 1}}).encode(),
            ),
        ]
    )
    client = WavelogClient(
        "http://wavelog:8086",
        SecretStr("secret"),
        station_location_name="Mobile",
        transport=transport,
    )

    assert client.upload_contact(contact()) is WavelogUploadDisposition.DUPLICATE


def test_bad_authentication_is_distinguished_without_exposing_token() -> None:
    transport = ScriptedTransport([UrllibHttpResponse(401, b'{"message":"denied"}')])
    client = WavelogClient(
        "http://wavelog:8086",
        SecretStr("do-not-leak"),
        station_location_name="Mobile",
        transport=transport,
    )

    with pytest.raises(WavelogAuthenticationError) as raised:
        client.resolve_station_location()
    assert "do-not-leak" not in str(raised.value)
