"""Tests for the HTTP Home Station Platform client."""

from collections.abc import Mapping
from datetime import UTC, datetime
from json import loads
from uuid import UUID

import pytest

from rolling_thunder.domain import Contact, RadioMode
from rolling_thunder.home_platform import (
    ContactUploadDisposition,
    ContactUploadRequest,
    HomePlatformAvailability,
    HomePlatformConnectionError,
    HomePlatformUploadError,
)
from rolling_thunder.http_home_platform import HttpHomePlatformClient

_CONTACT_ID = UUID("11111111-2222-3333-4444-555555555555")


class FakeResponse:
    def __init__(self, status_code: int, body: bytes) -> None:
        self._status_code = status_code
        self._body = body

    @property
    def status_code(self) -> int:
        return self._status_code

    @property
    def body(self) -> bytes:
        return self._body


class RecordingTransport:
    def __init__(self, response: FakeResponse | None = None) -> None:
        self.response = response or FakeResponse(200, b"{}")
        self.error: Exception | None = None
        self.calls: list[tuple[str, str, Mapping[str, str], bytes | None, float]] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout_s: float,
    ) -> FakeResponse:
        self.calls.append((method, url, headers, body, timeout_s))
        if self.error is not None:
            raise self.error
        return self.response


def timestamp() -> datetime:
    return datetime(2026, 7, 26, 20, 0, tzinfo=UTC)


def contact() -> Contact:
    return Contact(
        contact_id=_CONTACT_ID,
        callsign="W8O",
        frequency_hz=14_250_000,
        mode=RadioMode.USB,
        started_at=timestamp(),
        rst_sent="59",
        rst_received="59",
        grid="EN80ma",
        my_grid="EM79wm",
        pota_reference="US-1234",
        grid_source="pota_park",
        notes="POTA US-1234",
    )


def health_body(availability: str = "available") -> bytes:
    return (f'{{"availability":"{availability}","checked_at":"2026-07-26T20:00:00Z"}}').encode()


def upload_body(
    *,
    contact_id: UUID = _CONTACT_ID,
    disposition: str = "accepted",
) -> bytes:
    return (
        f'{{"contact_id":"{contact_id}",'
        f'"disposition":"{disposition}",'
        '"received_at":"2026-07-26T20:00:00Z"}'
    ).encode()


def test_client_starts_unknown_without_io() -> None:
    transport = RecordingTransport()

    client = HttpHomePlatformClient(
        " https://forge.example.test/api/ ",
        transport=transport,
    )

    assert client.get_state().availability is HomePlatformAvailability.UNKNOWN
    assert transport.calls == []


def test_health_check_uses_configured_url_timeout_and_validates_state() -> None:
    transport = RecordingTransport(FakeResponse(200, health_body()))
    client = HttpHomePlatformClient(
        "https://forge.example.test/api/",
        timeout_s=2.5,
        transport=transport,
    )

    state = client.check_health()

    assert state.availability is HomePlatformAvailability.AVAILABLE
    assert state.checked_at == timestamp()
    assert client.get_state() is state
    assert transport.calls == [
        (
            "GET",
            "https://forge.example.test/api/health",
            {"Accept": "application/json"},
            None,
            2.5,
        )
    ]


def test_health_endpoint_can_report_unavailable_with_error() -> None:
    body = (
        b'{"availability":"unavailable",'
        b'"checked_at":"2026-07-26T20:00:00Z",'
        b'"last_error":"maintenance"}'
    )
    client = HttpHomePlatformClient(
        "http://forge.test",
        transport=RecordingTransport(FakeResponse(200, body)),
    )

    state = client.check_health()

    assert state.availability is HomePlatformAvailability.UNAVAILABLE
    assert state.last_error == "maintenance"


def test_contact_upload_sends_idempotency_header_and_typed_body() -> None:
    transport = RecordingTransport(FakeResponse(201, upload_body()))
    client = HttpHomePlatformClient(
        "https://forge.example.test/api",
        timeout_s=4.0,
        transport=transport,
    )

    result = client.upload_contact(ContactUploadRequest(contact=contact()))

    assert result.contact_id == _CONTACT_ID
    assert result.disposition is ContactUploadDisposition.ACCEPTED
    method, url, headers, body, timeout_s = transport.calls[0]
    assert method == "POST"
    assert url == "https://forge.example.test/api/contacts"
    assert headers == {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Idempotency-Key": str(_CONTACT_ID),
    }
    assert timeout_s == 4.0
    assert body is not None
    payload = loads(body)
    assert payload["contact_id"] == str(_CONTACT_ID)
    assert payload["callsign"] == "W8O"
    assert payload["frequency_hz"] == 14_250_000
    assert payload["mode"] == "USB"
    assert payload["started_at"] == "2026-07-26T20:00:00Z"
    assert payload["grid"] == "EN80ma"
    assert payload["my_grid"] == "EM79wm"
    assert payload["pota_reference"] == "US-1234"
    assert payload["grid_source"] == "pota_park"
    assert payload["enrichment_state"] == "ready"
    assert payload["notes"] == "POTA US-1234"
    assert payload["synchronization_state"] == "pending"


def test_already_existing_contact_is_a_valid_upload_result() -> None:
    client = HttpHomePlatformClient(
        "https://forge.test",
        transport=RecordingTransport(FakeResponse(200, upload_body(disposition="already_exists"))),
    )

    result = client.upload_contact(ContactUploadRequest(contact=contact()))

    assert result.disposition is ContactUploadDisposition.ALREADY_EXISTS


@pytest.mark.parametrize("status_code", [300, 400, 404, 500, 503])
def test_health_http_failures_raise_connection_error(status_code: int) -> None:
    client = HttpHomePlatformClient(
        "https://forge.test",
        transport=RecordingTransport(FakeResponse(status_code, b"{}")),
    )

    with pytest.raises(HomePlatformConnectionError, match=f"HTTP {status_code}"):
        client.check_health()


@pytest.mark.parametrize("status_code", [300, 400, 409, 422, 500, 503])
def test_upload_http_failures_raise_upload_error(status_code: int) -> None:
    client = HttpHomePlatformClient(
        "https://forge.test",
        transport=RecordingTransport(FakeResponse(status_code, b"{}")),
    )

    with pytest.raises(HomePlatformUploadError, match=f"HTTP {status_code}"):
        client.upload_contact(ContactUploadRequest(contact=contact()))


def test_transport_failure_maps_to_typed_connection_error() -> None:
    transport = RecordingTransport()
    transport.error = TimeoutError("timed out")
    client = HttpHomePlatformClient("https://forge.test", transport=transport)

    with pytest.raises(HomePlatformConnectionError, match="timed out"):
        client.check_health()

    with pytest.raises(HomePlatformConnectionError, match="timed out"):
        client.upload_contact(ContactUploadRequest(contact=contact()))


@pytest.mark.parametrize("body", [b"not-json", b"\xff"])
def test_invalid_health_json_raises_connection_error(body: bytes) -> None:
    client = HttpHomePlatformClient(
        "https://forge.test",
        transport=RecordingTransport(FakeResponse(200, body)),
    )

    with pytest.raises(HomePlatformConnectionError, match="invalid JSON"):
        client.check_health()


@pytest.mark.parametrize("body", [b"not-json", b"\xff"])
def test_invalid_upload_json_raises_upload_error(body: bytes) -> None:
    client = HttpHomePlatformClient(
        "https://forge.test",
        transport=RecordingTransport(FakeResponse(200, body)),
    )

    with pytest.raises(HomePlatformUploadError, match="invalid JSON"):
        client.upload_contact(ContactUploadRequest(contact=contact()))


def test_health_schema_failure_raises_connection_error() -> None:
    client = HttpHomePlatformClient(
        "https://forge.test",
        transport=RecordingTransport(FakeResponse(200, b'{"status":"ok"}')),
    )

    with pytest.raises(HomePlatformConnectionError, match="expected schema"):
        client.check_health()


def test_upload_schema_failure_raises_upload_error() -> None:
    client = HttpHomePlatformClient(
        "https://forge.test",
        transport=RecordingTransport(FakeResponse(200, b'{"status":"ok"}')),
    )

    with pytest.raises(HomePlatformUploadError, match="expected schema"):
        client.upload_contact(ContactUploadRequest(contact=contact()))


def test_upload_rejects_mismatched_contact_id() -> None:
    other_id = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    client = HttpHomePlatformClient(
        "https://forge.test",
        transport=RecordingTransport(FakeResponse(200, upload_body(contact_id=other_id))),
    )

    with pytest.raises(HomePlatformUploadError, match="different contact ID"):
        client.upload_contact(ContactUploadRequest(contact=contact()))


@pytest.mark.parametrize(
    "base_url",
    [
        "",
        "forge.test",
        "ftp://forge.test",
        "https://",
        "https://forge.test/api?debug=true",
        "https://forge.test/api#section",
    ],
)
def test_invalid_base_url_is_rejected(base_url: str) -> None:
    with pytest.raises(ValueError, match="base URL"):
        HttpHomePlatformClient(base_url)


@pytest.mark.parametrize("timeout_s", [0.0, -0.1])
def test_nonpositive_timeout_is_rejected(timeout_s: float) -> None:
    with pytest.raises(ValueError, match="timeout"):
        HttpHomePlatformClient("https://forge.test", timeout_s=timeout_s)
