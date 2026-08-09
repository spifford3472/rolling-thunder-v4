"""Contract tests for the Pi-side Forge mobile-location HTTP client."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from json import dumps, loads
from typing import Any

import pytest

from rolling_thunder.forge_location_client import (
    ForgeLocationConnectionError,
    ForgeLocationResponseError,
    ForgeLocationStaleError,
    HttpForgeLocationClient,
)
from rolling_thunder.forge_mobile_location import MobileLocationRecord


@dataclass(frozen=True)
class Response:
    status_code: int
    body: bytes


class RecordingTransport:
    def __init__(self, response: Response | BaseException) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        body: bytes | None,
        timeout_s: float,
    ) -> Response:
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": headers,
                "body": body,
                "timeout_s": timeout_s,
            }
        )
        if isinstance(self.response, BaseException):
            raise self.response
        return self.response


def location() -> MobileLocationRecord:
    return MobileLocationRecord(
        latitude=39.529,
        longitude=-84.064,
        fix_at=datetime(2026, 8, 9, 0, 10, 0, tzinfo=UTC),
        received_at=datetime(2026, 8, 9, 0, 10, 1, tzinfo=UTC),
        speed_m_s=12.5,
        heading_degrees=42.0,
    )


def response_body(value: MobileLocationRecord, *, revision: int = 3) -> bytes:
    return dumps(
        {
            "api_schema_version": "1",
            "revision": revision,
            "location": value.model_dump(mode="json"),
        },
        separators=(",", ":"),
    ).encode("utf-8")


def test_publish_uses_exact_versioned_put_contract_and_timeout() -> None:
    value = location()
    transport = RecordingTransport(Response(200, response_body(value)))
    client = HttpForgeLocationClient(
        "http://forge.example.invalid:8766/",
        timeout_s=4.5,
        transport=transport,
    )

    receipt = client.publish(value)

    assert receipt.revision == 3
    assert receipt.location == value
    assert len(transport.calls) == 1
    call = transport.calls[0]
    assert call["method"] == "PUT"
    assert call["url"] == "http://forge.example.invalid:8766/api/v1/mobile-location"
    assert call["timeout_s"] == 4.5
    assert call["headers"]["Content-Type"] == "application/json"
    assert call["headers"]["Accept"] == "application/json"
    payload = loads(call["body"])
    assert payload["api_schema_version"] == "1"
    assert payload["location"] == value.model_dump(mode="json")


def test_timeout_is_wrapped_as_connection_failure() -> None:
    transport = RecordingTransport(TimeoutError("offline"))
    client = HttpForgeLocationClient(
        "http://forge.example.invalid:8766",
        transport=transport,
    )

    with pytest.raises(ForgeLocationConnectionError):
        client.publish(location())


def test_http_409_is_a_typed_stale_rejection() -> None:
    transport = RecordingTransport(
        Response(
            409,
            b'{"error":"stale_location","message":"location already retained"}',
        )
    )
    client = HttpForgeLocationClient(
        "http://forge.example.invalid:8766",
        transport=transport,
    )

    with pytest.raises(ForgeLocationStaleError, match="already retained"):
        client.publish(location())


def test_other_http_error_text_is_bounded() -> None:
    message = "x" * 900
    body = dumps({"message": message}).encode("utf-8")
    transport = RecordingTransport(Response(503, body))
    client = HttpForgeLocationClient(
        "http://forge.example.invalid:8766",
        transport=transport,
    )

    with pytest.raises(ForgeLocationResponseError) as caught:
        client.publish(location())

    assert len(str(caught.value)) == 500


def test_success_acknowledgement_must_match_submitted_location() -> None:
    value = location()
    other = value.model_copy(update={"latitude": 40.0})
    transport = RecordingTransport(Response(200, response_body(other)))
    client = HttpForgeLocationClient(
        "http://forge.example.invalid:8766",
        transport=transport,
    )

    with pytest.raises(ForgeLocationResponseError, match="did not match"):
        client.publish(value)
