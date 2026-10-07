"""Tests for Forge-local Wavelog target resolution and contact mapping."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from json import dumps, loads
from pathlib import Path
from typing import Final

import pytest
from pydantic import SecretStr

from rolling_thunder.domain import Contact, ContactWeatherObservation, RadioMode
from rolling_thunder.forge_contact_sync import (
    ForgeContactSyncRepository,
    ForgeContactSyncService,
)
from rolling_thunder.http_home_platform import UrllibHttpResponse
from rolling_thunder.wavelog import (
    WavelogAuthenticationError,
    WavelogClient,
    WavelogLogbookError,
    WavelogResponseError,
    WavelogStationBinding,
    WavelogStationLocation,
    WavelogStationLocationError,
    WavelogStationTarget,
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


class MemoryStationBindings:
    def __init__(self) -> None:
        self.bindings: dict[str, WavelogStationBinding] = {}
        self.write_count = 0

    def get_station_binding(self, name: str) -> WavelogStationBinding | None:
        return self.bindings.get(name)

    def bind_station(self, binding: WavelogStationBinding) -> None:
        existing = self.bindings.get(binding.name)
        if existing is not None and existing != binding:
            raise AssertionError("test binding changed identity")
        self.bindings[binding.name] = binding
        self.write_count += 1


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
    normalized = [
        {
            "uuid": f"station-{location.get('id', 'invalid')}",
            "callsign": "KI5VNB",
            "dxcc": 291,
            "cq": 4,
            "itu": 8,
            "state": "OH",
            **location,
        }
        for location in locations
    ]
    return UrllibHttpResponse(200, dumps({"data": normalized}).encode())


def station(
    station_id: int,
    name: str,
    gridsquare: str,
    *,
    state: str = "OH",
    cq: int = 4,
    itu: int = 8,
    callsign: str = "KI5VNB",
    dxcc: int = 291,
    uuid: str | None = None,
) -> dict[str, object]:
    return {
        "id": station_id,
        "uuid": uuid or f"station-{station_id}",
        "name": name,
        "callsign": callsign,
        "gridsquare": gridsquare,
        "dxcc": dxcc,
        "cq": cq,
        "itu": itu,
        "state": state,
    }


def logbook_response(*station_ids: int, status: int = 200) -> UrllibHttpResponse:
    return UrllibHttpResponse(
        status,
        dumps(
            {
                "data": [
                    {
                        "id": 5,
                        "name": "KI5VNB Main",
                        "active": True,
                        "station_ids": list(station_ids),
                    }
                ]
            }
        ).encode(),
    )


def logbook_update_response(*station_ids: int) -> UrllibHttpResponse:
    return UrllibHttpResponse(
        200,
        dumps(
            {
                "data": {
                    "id": 5,
                    "name": "KI5VNB Main",
                    "active": True,
                    "station_ids": list(station_ids),
                }
            }
        ).encode(),
    )


def dynamic_contact(*, grid: str = "EM79xm", state: str = "OH") -> Contact:
    return contact().model_copy(
        update={
            "my_grid": grid,
            "my_latitude": 39.5309,
            "my_longitude": -84.0866,
            "my_state": state,
            "my_cq_zone": 4,
            "my_itu_zone": 8,
        }
    )


def managed_client(
    transport: ScriptedTransport,
    *,
    bindings: MemoryStationBindings | ForgeContactSyncRepository | None = None,
) -> WavelogClient:
    return WavelogClient(
        "http://wavelog:8086",
        SecretStr("secret"),
        station_location_name="Mobile",
        station_logbook_name="KI5VNB Main",
        transport=transport,
        station_binding_store=bindings or MemoryStationBindings(),
    )


def station_update_response(
    *,
    station_id: int = 42,
    name: str = "Mobile",
    gridsquare: str,
) -> UrllibHttpResponse:
    return UrllibHttpResponse(
        200,
        dumps(
            {
                "data": {
                    "id": station_id,
                    "uuid": "mobile",
                    "name": name,
                    "gridsquare": gridsquare,
                }
            }
        ).encode(),
    )


def qso_import_response(*, imported: int, skipped: int) -> UrllibHttpResponse:
    return UrllibHttpResponse(
        200,
        dumps(
            {
                "data": {
                    "parsed": 1,
                    "imported": imported,
                    "skipped": skipped,
                }
            }
        ).encode(),
    )


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


@pytest.mark.parametrize("notes", [None, "", "   "])
def test_contact_to_adif_uses_mobile_qso_only_for_blank_notes(notes: str | None) -> None:
    qso = contact().model_copy(update={"notes": notes})

    adif = contact_to_adif(qso)

    assert "<NOTES:10>Mobile QSO" in adif
    assert adif.count("Mobile QSO") == 1


def test_contact_to_adif_preserves_existing_notes_exactly() -> None:
    qso = contact().model_copy(update={"notes": "  Exact operator text  "})

    adif = contact_to_adif(qso)

    assert "<NOTES:23>  Exact operator text  " in adif
    assert "Mobile QSO" not in adif


def test_contact_to_adif_adds_power_and_structured_weather_notes() -> None:
    qso = contact().model_copy(
        update={
            "tx_power_watts": 60,
            "weather_notes_enabled": True,
            "contact_weather": ContactWeatherObservation(summary="Clear, 61 F"),
            "local_weather": None,
        }
    )

    adif = contact_to_adif(qso)

    assert "<TX_PWR:2>60" in adif
    notes = "POTA US-0732\nContact Wx: Clear, 61 F\nLocal Wx: N/A"
    assert f"<NOTES:{len(notes)}>{notes}" in adif


def test_mobile_station_location_is_resolved_by_name_not_assumed_id() -> None:
    transport = ScriptedTransport(
        [
            station_response(
                {"id": 17, "uuid": "home", "name": "Home", "gridsquare": "EM79XM"},
                {
                    "id": 42,
                    "uuid": "mobile",
                    "name": "Mobile",
                    "gridsquare": "EM89LX",
                },
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
    assert location.gridsquare == "EM89LX"
    _, url, headers, _, _ = transport.requests[0]
    assert url.endswith("/index.php/api/v2/station")
    assert headers["Authorization"] == "Bearer secret"


def test_missing_or_ambiguous_mobile_station_location_is_rejected() -> None:
    for locations in (
        ({"id": 1, "name": "Home", "gridsquare": "EM79XM"},),
        (
            {"id": 2, "name": "Mobile", "gridsquare": "EM79XM"},
            {"id": 3, "name": "Mobile", "gridsquare": "EM89LX"},
        ),
    ):
        client = WavelogClient(
            "http://wavelog:8086",
            SecretStr("secret"),
            station_location_name="Mobile",
            transport=ScriptedTransport([station_response(*locations)]),
        )
        with pytest.raises(WavelogStationLocationError):
            client.resolve_station_location()


def test_existing_exact_dynamic_station_is_reused() -> None:
    legacy = station(42, "Mobile", "EM79XM")
    dynamic = station(99, "Mobile - EM79 - OH", "EM79")
    transport = ScriptedTransport(
        [station_response(legacy, dynamic), logbook_response(1, 42, 99)]
    )

    target = managed_client(transport).resolve_station_target(dynamic_contact())

    assert target.location.station_id == 99
    assert target.location.name == "Mobile - EM79 - OH"
    assert target.dynamic
    assert [request[0] for request in transport.requests] == ["GET", "GET"]


def test_same_frozen_grid_and_state_reuses_one_dynamic_station() -> None:
    locations = (
        station(42, "Mobile", "EM79XM"),
        station(99, "Mobile - EM79 - OH", "EM79"),
    )
    transport = ScriptedTransport(
        [
            station_response(*locations),
            logbook_response(42, 99),
            station_response(*locations),
            logbook_response(42, 99),
        ]
    )
    client = managed_client(transport)

    first = client.resolve_station_target(dynamic_contact())
    second = client.resolve_station_target(dynamic_contact(grid="EM79aa"))

    assert first.location.station_id == second.location.station_id == 99
    assert all(request[0] == "GET" for request in transport.requests)


def test_different_frozen_grid_or_state_selects_different_dynamic_station() -> None:
    locations = (
        station(42, "Mobile", "EM79XM"),
        station(98, "Mobile - EM79 - OH", "EM79"),
        station(99, "Mobile - EM89 - IN", "EM89", state="IN"),
    )
    transport = ScriptedTransport(
        [
            station_response(*locations),
            logbook_response(42, 98, 99),
            station_response(*locations),
            logbook_response(42, 98, 99),
        ]
    )
    client = managed_client(transport)

    ohio = client.resolve_station_target(dynamic_contact())
    indiana = client.resolve_station_target(dynamic_contact(grid="EM89aa", state="IN"))

    assert ohio.location.station_id == 98
    assert indiana.location.station_id == 99


def test_active_log_only_hidden_created_station_is_bound_and_linked() -> None:
    legacy = station(42, "Mobile", "EM79XM")
    dynamic = station(99, "Mobile - EM79 - OH", "EM79")
    transport = ScriptedTransport(
        [
            station_response(legacy),
            logbook_response(1, 42),
            UrllibHttpResponse(201, dumps({"data": dynamic}).encode()),
            logbook_update_response(1, 42, 99),
            logbook_response(1, 42, 99),
        ]
    )

    target = managed_client(transport).resolve_station_target(dynamic_contact())

    assert target.location.station_id == 99
    assert target.dynamic
    methods = [request[0] for request in transport.requests]
    assert methods == ["GET", "GET", "POST", "PATCH", "GET"]
    create_payload = loads(transport.requests[2][3] or b"{}")
    assert create_payload == {
        "name": "Mobile - EM79 - OH",
        "callsign": "KI5VNB",
        "dxcc": 291,
        "cq": 4,
        "itu": 8,
        "gridsquare": "EM79",
        "state": "OH",
    }
    link_payload = loads(transport.requests[3][3] or b"{}")
    assert link_payload == {"station_ids": [1, 42, 99]}


def test_dynamic_station_create_race_is_reread_and_reused() -> None:
    legacy = station(42, "Mobile", "EM79XM")
    dynamic = station(99, "Mobile - EM79 - OH", "EM79")
    transport = ScriptedTransport(
        [
            station_response(legacy),
            logbook_response(42, 99),
            UrllibHttpResponse(409, b'{"error":"conflict"}'),
            station_response(legacy, dynamic),
        ]
    )

    target = managed_client(transport).resolve_station_target(dynamic_contact())

    assert target.location.station_id == 99
    assert [request[0] for request in transport.requests] == ["GET", "GET", "POST", "GET"]


def test_hidden_created_station_is_recovered_after_restart_and_linked(
    tmp_path: Path,
) -> None:
    legacy = station(42, "Mobile", "EM79XM")
    dynamic = station(99, "Mobile - EM79 - OH", "EM79")
    database = tmp_path / "forge.db"
    first_transport = ScriptedTransport(
        [
            station_response(legacy),
            logbook_response(42),
            UrllibHttpResponse(201, dumps({"data": dynamic}).encode()),
            UrllibHttpResponse(500, b'{"error":"failed"}'),
        ]
    )
    first_repository = ForgeContactSyncRepository(database)
    first_client = managed_client(
        first_transport,
        bindings=first_repository,
    )
    first_service = ForgeContactSyncService(first_repository, first_client)

    with pytest.raises(WavelogResponseError, match="HTTP 500"):
        first_service.synchronize(dynamic_contact())

    restarted_transport = ScriptedTransport(
        [
            station_response(legacy),
            logbook_response(42),
            UrllibHttpResponse(200, dumps({"data": dynamic}).encode()),
            logbook_update_response(42, 99),
            logbook_response(42, 99),
            qso_import_response(imported=1, skipped=0),
        ]
    )
    restarted_repository = ForgeContactSyncRepository(database)
    restarted_client = managed_client(
        restarted_transport,
        bindings=restarted_repository,
    )
    restarted_service = ForgeContactSyncService(
        restarted_repository,
        restarted_client,
    )
    result = restarted_service.synchronize(dynamic_contact())

    assert result.contact_id == dynamic_contact().contact_id
    assert [request[0] for request in first_transport.requests] == [
        "GET",
        "GET",
        "POST",
        "PATCH",
    ]
    assert [request[0] for request in restarted_transport.requests] == [
        "GET",
        "GET",
        "GET",
        "PATCH",
        "GET",
        "POST",
    ]


def test_hidden_durable_binding_with_changed_uuid_fails_closed() -> None:
    legacy = station(42, "Mobile", "EM79XM")
    changed = station(99, "Mobile - EM79 - OH", "EM79", uuid="changed-uuid")
    bindings = MemoryStationBindings()
    bindings.bindings[changed["name"]] = WavelogStationBinding(
        str(changed["name"]), 99, "original-uuid"
    )
    transport = ScriptedTransport(
        [
            station_response(legacy),
            logbook_response(42),
            UrllibHttpResponse(200, dumps({"data": changed}).encode()),
        ]
    )

    with pytest.raises(WavelogStationLocationError, match="no longer matches"):
        managed_client(transport, bindings=bindings).resolve_station_target(
            dynamic_contact()
        )


def test_hidden_durable_binding_with_incompatible_metadata_fails_closed() -> None:
    legacy = station(42, "Mobile", "EM79XM")
    incompatible = station(99, "Mobile - EM79 - OH", "EM89")
    bindings = MemoryStationBindings()
    bindings.bindings[str(incompatible["name"])] = WavelogStationBinding(
        str(incompatible["name"]), 99, str(incompatible["uuid"])
    )
    transport = ScriptedTransport(
        [
            station_response(legacy),
            logbook_response(42),
            UrllibHttpResponse(200, dumps({"data": incompatible}).encode()),
        ]
    )

    with pytest.raises(WavelogStationLocationError, match="incompatible"):
        managed_client(transport, bindings=bindings).resolve_station_target(
            dynamic_contact()
        )


def test_hidden_409_without_binding_fails_closed_without_id_guessing() -> None:
    legacy = station(42, "Mobile", "EM79XM")
    transport = ScriptedTransport(
        [
            station_response(legacy),
            logbook_response(42),
            UrllibHttpResponse(409, b'{"error":"conflict"}'),
            station_response(legacy),
        ]
    )

    with pytest.raises(WavelogStationLocationError, match="refusing to guess an ID"):
        managed_client(transport).resolve_station_target(dynamic_contact())

    assert [request[0] for request in transport.requests] == ["GET", "GET", "POST", "GET"]
    assert not any(url.endswith("/station/99") for _, url, _, _, _ in transport.requests)


def test_hidden_409_can_recover_with_preexisting_valid_binding() -> None:
    legacy = station(42, "Mobile", "EM79XM")
    dynamic = station(99, "Mobile - EM79 - OH", "EM79")
    binding = WavelogStationBinding("Mobile - EM79 - OH", 99, "station-99")
    bindings = MemoryStationBindings()
    bindings.bindings[binding.name] = binding
    transport = ScriptedTransport(
        [
            UrllibHttpResponse(409, b'{"error":"conflict"}'),
            station_response(legacy),
            UrllibHttpResponse(200, dumps({"data": dynamic}).encode()),
        ]
    )
    client = managed_client(transport, bindings=bindings)
    template = WavelogStationLocation(
        42,
        "Mobile",
        "EM79XM",
        "station-42",
        "KI5VNB",
        291,
        4,
        8,
        "OH",
    )

    recovered = client._create_dynamic_station(
        name=binding.name,
        grid="EM79",
        state="OH",
        cq=4,
        itu=8,
        template=template,
        prior_binding=binding,
    )

    assert recovered.station_id == 99
    assert [request[0] for request in transport.requests] == ["POST", "GET", "GET"]


def test_visible_exact_station_establishes_and_refreshes_binding() -> None:
    legacy = station(42, "Mobile", "EM79XM")
    dynamic = station(99, "Mobile - EM79 - OH", "EM79")
    bindings = MemoryStationBindings()
    transport = ScriptedTransport(
        [
            station_response(legacy, dynamic),
            logbook_response(42, 99),
            station_response(legacy, dynamic),
            logbook_response(42, 99),
        ]
    )
    client = managed_client(transport, bindings=bindings)

    target = client.resolve_station_target(dynamic_contact())
    repeated = client.resolve_station_target(dynamic_contact())

    assert target.location.station_id == repeated.location.station_id == 99
    assert bindings.bindings["Mobile - EM79 - OH"] == WavelogStationBinding(
        "Mobile - EM79 - OH", 99, "station-99"
    )
    assert bindings.write_count == 2


def test_ambiguous_dynamic_station_name_fails_closed() -> None:
    name = "Mobile - EM79 - OH"
    transport = ScriptedTransport(
        [
            station_response(
                station(42, "Mobile", "EM79XM"),
                station(98, name, "EM79"),
                station(99, name, "EM79"),
            ),
            logbook_response(42, 98, 99),
        ]
    )

    with pytest.raises(WavelogStationLocationError, match="ambiguous"):
        managed_client(transport).resolve_station_target(dynamic_contact())


def test_malformed_station_or_ambiguous_logbook_fails_closed() -> None:
    malformed = ScriptedTransport(
        [UrllibHttpResponse(200, b'{"data":[{"id":42,"name":"Mobile"}]}')]
    )
    with pytest.raises(WavelogResponseError, match="incomplete station"):
        managed_client(malformed).resolve_station_target(dynamic_contact())

    ambiguous_logbook = ScriptedTransport(
        [
            station_response(station(42, "Mobile", "EM79XM")),
            UrllibHttpResponse(
                200,
                dumps(
                    {
                        "data": [
                            {"id": 5, "name": "KI5VNB Main", "station_ids": [42]},
                            {"id": 6, "name": "KI5VNB Main", "station_ids": [42]},
                        ]
                    }
                ).encode(),
            ),
        ]
    )
    with pytest.raises(WavelogLogbookError, match="exactly one"):
        managed_client(ambiguous_logbook).resolve_station_target(dynamic_contact())


@pytest.mark.parametrize(
    "override",
    [
        {"gridsquare": "EM89"},
        {"state": "IN"},
        {"cq": 5},
        {"itu": 9},
        {"callsign": "W1AW"},
        {"dxcc": 110},
    ],
)
def test_incompatible_exact_dynamic_station_fails_closed(
    override: dict[str, object],
) -> None:
    dynamic = {**station(99, "Mobile - EM79 - OH", "EM79"), **override}
    transport = ScriptedTransport(
        [
            station_response(station(42, "Mobile", "EM79XM"), dynamic),
            logbook_response(42, 99),
        ]
    )

    with pytest.raises(WavelogStationLocationError, match="incompatible"):
        managed_client(transport).resolve_station_target(dynamic_contact())


def test_insufficient_frozen_context_routes_to_unknown_mobile_station() -> None:
    unknown = {
        "id": 99,
        "uuid": "station-99",
        "name": "Mobile - Unknown Location",
        "callsign": "KI5VNB",
        "gridsquare": "",
        "dxcc": 291,
        "cq": None,
        "itu": None,
        "state": "",
    }
    transport = ScriptedTransport(
        [
            station_response(station(42, "Mobile", "EM79XM")),
            logbook_response(1, 42),
            UrllibHttpResponse(201, dumps({"data": unknown}).encode()),
            logbook_update_response(1, 42, 99),
            logbook_response(1, 42, 99),
        ]
    )
    qso = dynamic_contact().model_copy(
        update={
            "my_grid": None,
            "my_latitude": None,
            "my_longitude": None,
            "my_state": None,
            "my_cq_zone": None,
            "my_itu_zone": None,
        }
    )

    target = managed_client(transport).resolve_station_target(qso)

    assert target.location.station_id == 99
    assert target.location.name == "Mobile - Unknown Location"
    assert target.location.gridsquare == ""
    assert target.location.state == ""
    assert target.location.cq is None and target.location.itu is None
    assert target.dynamic
    assert [request[0] for request in transport.requests] == ["GET", "GET", "POST", "PATCH", "GET"]
    create_payload = loads(transport.requests[2][3] or b"{}")
    assert create_payload == {
        "name": "Mobile - Unknown Location",
        "callsign": "KI5VNB",
        "dxcc": 291,
    }


def test_dynamic_target_is_not_patched_to_six_character_qso_grid() -> None:
    transport = ScriptedTransport([qso_import_response(imported=1, skipped=0)])
    client = managed_client(transport)
    location = WavelogStationLocation(
        99,
        "Mobile - EM79 - OH",
        "EM79",
        "station-99",
        "KI5VNB",
        291,
        4,
        8,
        "OH",
    )

    result = client.upload_contact(
        dynamic_contact(),
        target=WavelogStationTarget(location, dynamic=True),
    )

    assert result is WavelogUploadDisposition.IMPORTED
    assert [request[0] for request in transport.requests] == ["POST"]
    payload = loads(transport.requests[0][3] or b"{}")
    assert payload["station_profile_id"] == 99
    assert "<MY_GRIDSQUARE:6>EM79xm" in payload["adif"]


def test_health_validation_is_read_only_and_never_creates_or_links() -> None:
    transport = ScriptedTransport(
        [station_response(station(42, "Mobile", "EM79XM")), logbook_response(42)]
    )

    bindings = MemoryStationBindings()
    managed_client(transport, bindings=bindings).verify_health_target()

    assert [request[0] for request in transport.requests] == ["GET", "GET"]
    assert bindings.write_count == 0


def test_qso_import_aligns_mobile_grid_then_targets_resolved_profile() -> None:
    transport = ScriptedTransport(
        [
            station_response(
                {"id": 42, "uuid": "mobile", "name": "Mobile", "gridsquare": "EM79XM"}
            ),
            station_update_response(gridsquare="EM79XM"),
            qso_import_response(imported=1, skipped=0),
        ]
    )
    client = WavelogClient(
        "http://wavelog:8086",
        SecretStr("secret"),
        station_location_name="Mobile",
        transport=transport,
    )

    moving_contact = contact().model_copy(update={"my_grid": "EM89lx"})
    transport.responses[1] = station_update_response(gridsquare="EM89LX")

    target = WavelogStationTarget(client.resolve_station_location(), dynamic=False)
    result = client.upload_contact(moving_contact, target=target)

    assert result is WavelogUploadDisposition.IMPORTED

    method, url, _, body, _ = transport.requests[1]
    assert method == "PATCH"
    assert url.endswith("/index.php/api/v2/station/42")
    assert body is not None
    assert loads(body) == {"gridsquare": "EM89LX"}

    method, url, _, body, _ = transport.requests[2]
    assert method == "POST"
    assert url.endswith("/index.php/api/v2/qso")
    assert body is not None
    payload = loads(body)
    assert payload["station_profile_id"] == 42
    assert payload["import_type"] == "adif"
    assert "W1AW" in payload["adif"]
    assert "<MY_GRIDSQUARE:6>EM89lx" in payload["adif"]


def test_matching_mobile_grid_does_not_patch_station_profile() -> None:
    transport = ScriptedTransport(
        [
            station_response(
                {"id": 42, "uuid": "mobile", "name": "Mobile", "gridsquare": "EM79XM"}
            ),
            qso_import_response(imported=1, skipped=0),
        ]
    )
    client = WavelogClient(
        "http://wavelog:8086",
        SecretStr("secret"),
        station_location_name="Mobile",
        transport=transport,
    )

    target = WavelogStationTarget(client.resolve_station_location(), dynamic=False)
    assert (
        client.upload_contact(contact(), target=target)
        is WavelogUploadDisposition.IMPORTED
    )
    assert [request[0] for request in transport.requests] == ["GET", "POST"]


def test_unknown_mobile_grid_clears_stale_profile_grid_before_import() -> None:
    transport = ScriptedTransport(
        [
            station_response(
                {"id": 42, "uuid": "mobile", "name": "Mobile", "gridsquare": "EM79XM"}
            ),
            station_update_response(gridsquare=""),
            qso_import_response(imported=1, skipped=0),
        ]
    )
    client = WavelogClient(
        "http://wavelog:8086",
        SecretStr("secret"),
        station_location_name="Mobile",
        transport=transport,
    )

    unknown_grid_contact = contact().model_copy(update={"my_grid": None})

    target = WavelogStationTarget(client.resolve_station_location(), dynamic=False)
    assert (
        client.upload_contact(unknown_grid_contact, target=target)
        is WavelogUploadDisposition.IMPORTED
    )
    assert loads(transport.requests[1][3] or b"{}") == {"gridsquare": ""}


def test_wavelog_duplicate_is_a_successful_idempotent_outcome() -> None:
    transport = ScriptedTransport(
        [
            station_response(
                {"id": 42, "uuid": "mobile", "name": "Mobile", "gridsquare": "EM79XM"}
            ),
            qso_import_response(imported=0, skipped=1),
        ]
    )
    client = WavelogClient(
        "http://wavelog:8086",
        SecretStr("secret"),
        station_location_name="Mobile",
        transport=transport,
    )

    target = WavelogStationTarget(client.resolve_station_location(), dynamic=False)
    assert (
        client.upload_contact(contact(), target=target)
        is WavelogUploadDisposition.DUPLICATE
    )


def test_station_grid_update_requires_wavelog_write_authorization() -> None:
    transport = ScriptedTransport(
        [
            station_response(
                {"id": 42, "uuid": "mobile", "name": "Mobile", "gridsquare": "EM79XM"}
            ),
            UrllibHttpResponse(403, b'{"message":"denied"}'),
        ]
    )
    client = WavelogClient(
        "http://wavelog:8086",
        SecretStr("do-not-leak"),
        station_location_name="Mobile",
        transport=transport,
    )

    moving_contact = contact().model_copy(update={"my_grid": "EM89lx"})

    with pytest.raises(WavelogAuthenticationError) as raised:
        target = WavelogStationTarget(client.resolve_station_location(), dynamic=False)
        client.upload_contact(moving_contact, target=target)

    assert "403" in str(raised.value)
    assert "do-not-leak" not in str(raised.value)


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
