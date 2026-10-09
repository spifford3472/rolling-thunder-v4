"""Transport-only tests for the completed-QSO producer client."""

from collections.abc import Mapping
from datetime import UTC, datetime
from json import dumps, loads
from uuid import UUID

import pytest

from rolling_thunder.completed_qso_ingestion_client import (
    CompletedQsoProducerError,
    HttpCompletedQsoIngestionClient,
)
from rolling_thunder.domain import Contact, ContactSource, RadioMode

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
CONTACT_ID = UUID("11111111-2222-4333-8444-555555555555")
TOKEN = "test-token-that-is-at-least-32-characters-long"


class Response:
    def __init__(self, status_code: int, body: bytes) -> None:
        self.status_code = status_code
        self.body = body


class RecordingTransport:
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


def test_client_sends_authenticated_idempotent_complete_contact() -> None:
    transport = RecordingTransport(
        Response(
            202,
            dumps(
                {
                    "schema_version": "1",
                    "contact_id": str(CONTACT_ID),
                    "disposition": "accepted",
                    "received_at_utc": "2026-10-08T12:00:00Z",
                }
            ).encode(),
        )
    )
    client = HttpCompletedQsoIngestionClient(
        "http://forge.test:8790", bearer_token=TOKEN, transport=transport
    )

    result = client.enqueue(_contact())

    method, url, headers, body, timeout = transport.calls[0]
    assert result.contact_id == CONTACT_ID
    assert result.disposition == "accepted"
    assert method == "POST"
    assert url == "http://forge.test:8790/api/v1/completed-qsos"
    assert headers["Authorization"] == f"Bearer {TOKEN}"
    assert headers["Idempotency-Key"] == str(CONTACT_ID)
    assert loads(body)["contact_id"] == str(CONTACT_ID)  # type: ignore[arg-type]
    assert timeout == 5.0


def test_client_rejects_failure_and_wrong_acknowledgement() -> None:
    failed = HttpCompletedQsoIngestionClient(
        "http://forge.test:8790",
        bearer_token=TOKEN,
        transport=RecordingTransport(Response(401, b"{}")),
    )
    wrong = HttpCompletedQsoIngestionClient(
        "http://forge.test:8790",
        bearer_token=TOKEN,
        transport=RecordingTransport(
            Response(
                200,
                dumps(
                    {
                        "schema_version": "1",
                        "contact_id": "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
                        "disposition": "replayed",
                        "received_at_utc": "2026-10-08T12:00:00Z",
                    }
                ).encode(),
            )
        ),
    )

    with pytest.raises(CompletedQsoProducerError, match="HTTP 401"):
        failed.enqueue(_contact())
    with pytest.raises(CompletedQsoProducerError, match="different contact ID"):
        wrong.enqueue(_contact())


def _contact() -> Contact:
    return Contact(
        contact_id=CONTACT_ID,
        callsign="KC1OXG",
        frequency_hz=14_074_000,
        mode=RadioMode.FT8,
        started_at=NOW,
        rst_sent="-10",
        rst_received="-12",
        grid="FN31pr",
        my_grid="EM79xp",
        source=ContactSource.FT8,
        tx_power_watts=55,
    )
