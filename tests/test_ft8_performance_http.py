"""Tests for Pi HTTP upload of FT8 performance telemetry."""

from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from json import loads
from uuid import UUID

import pytest

from rolling_thunder.ft8.performance import (
    FT8AttemptOutcome,
    FT8PerformanceAttempt,
    FT8PerformanceUploadDisposition,
)
from rolling_thunder.home_platform import HomePlatformUploadError
from rolling_thunder.http_home_platform import HttpHomePlatformClient


class Response:
    def __init__(self, status_code: int, body: bytes) -> None:
        self.status_code = status_code
        self.body = body


class Transport:
    def __init__(self, response: Response) -> None:
        self.response = response
        self.calls: list[tuple[str, str, Mapping[str, str], bytes | None, float]] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout_s: float,
    ) -> Response:
        self.calls.append((method, url, headers, body, timeout_s))
        return self.response


_ATTEMPT_ID = UUID("00000000-0000-0000-0000-000000000501")


def _attempt() -> FT8PerformanceAttempt:
    started = datetime(2026, 10, 2, 20, 0, tzinfo=UTC)
    return FT8PerformanceAttempt(
        attempt_id=_ATTEMPT_ID,
        callsign="K1ABC",
        outcome=FT8AttemptOutcome.ABORTED,
        success=False,
        terminal_state="aborted",
        terminal_reason="operator abort",
        started_at_utc=started,
        ended_at_utc=started + timedelta(seconds=30),
        utc_date=date(2026, 10, 2),
        band="20m",
        dial_frequency_hz=14_074_000,
        local_grid="EM79xm",
        remote_grid="FN31pr",
        distance_km=1000.0,
        audio_frequency_hz=1500,
    )


def _response(*, attempt_id: UUID = _ATTEMPT_ID) -> bytes:
    return (
        "{"
        f'"attempt_id":"{attempt_id}",'
        '"disposition":"accepted",'
        '"received_at_utc":"2026-10-02T20:01:00Z"'
        "}"
    ).encode()


def test_http_client_posts_structured_attempt_with_idempotency_header() -> None:
    transport = Transport(Response(200, _response()))
    client = HttpHomePlatformClient(
        "https://forge.example.test/api",
        timeout_s=4.0,
        transport=transport,
    )

    result = client.upload_ft8_performance(_attempt())

    assert result.attempt_id == _ATTEMPT_ID
    assert result.disposition is FT8PerformanceUploadDisposition.ACCEPTED
    method, url, headers, body, timeout = transport.calls[0]
    assert method == "POST"
    assert url == "https://forge.example.test/api/ft8-performance"
    assert headers["Idempotency-Key"] == str(_ATTEMPT_ID)
    assert timeout == 4.0
    assert body is not None
    payload = loads(body)
    assert payload["attempt_id"] == str(_ATTEMPT_ID)
    assert payload["outcome"] == "aborted"
    assert payload["mode"] == "FT8"
    assert payload["tx_power_target_watts"] == 20


@pytest.mark.parametrize("status_code", [400, 409, 422, 500, 503])
def test_http_client_rejects_failed_performance_upload(status_code: int) -> None:
    client = HttpHomePlatformClient(
        "https://forge.test",
        transport=Transport(Response(status_code, b"{}")),
    )

    with pytest.raises(HomePlatformUploadError, match=f"HTTP {status_code}"):
        client.upload_ft8_performance(_attempt())


def test_http_client_rejects_mismatched_attempt_acknowledgement() -> None:
    client = HttpHomePlatformClient(
        "https://forge.test",
        transport=Transport(
            Response(
                200,
                _response(
                    attempt_id=UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
                ),
            )
        ),
    )

    with pytest.raises(HomePlatformUploadError, match="different attempt ID"):
        client.upload_ft8_performance(_attempt())
