"""Transport-only tests for completed-FT8 PSK event delivery."""

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from json import dumps, loads
from uuid import UUID

import pytest

from rolling_thunder.completed_ft8_ingestion_client import (
    CompletedFt8IngestionError,
    HttpCompletedFt8IngestionClient,
)
from rolling_thunder.domain import Contact, ContactSource, RadioMode
from rolling_thunder.forge_pskreporter_orchestration import CompletedFt8QsoEvent
from rolling_thunder.ft8.performance import FT8AttemptOutcome, FT8PerformanceAttempt

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


def test_client_sends_authenticated_idempotent_complete_event() -> None:
    transport = RecordingTransport(
        Response(
            202,
            dumps(
                {
                    "schema_version": "1",
                    "contact_id": str(CONTACT_ID),
                    "disposition": "accepted",
                }
            ).encode(),
        )
    )
    client = HttpCompletedFt8IngestionClient(
        "http://forge.test:8789", bearer_token=TOKEN, transport=transport
    )

    result = client.enqueue(_event())

    method, url, headers, body, timeout = transport.calls[0]
    assert result.contact_id == CONTACT_ID
    assert method == "POST"
    assert url == "http://forge.test:8789/api/v1/completed-ft8-events"
    assert headers["Authorization"] == f"Bearer {TOKEN}"
    assert headers["Idempotency-Key"] == str(CONTACT_ID)
    assert loads(body)["terminal_attempt"]["attempt_id"] == str(CONTACT_ID)  # type: ignore[arg-type]
    assert timeout == 5.0


def test_client_rejects_failure_and_wrong_acknowledgement() -> None:
    failed = HttpCompletedFt8IngestionClient(
        "http://forge.test:8789",
        bearer_token=TOKEN,
        transport=RecordingTransport(Response(409, b"{}")),
    )
    wrong = HttpCompletedFt8IngestionClient(
        "http://forge.test:8789",
        bearer_token=TOKEN,
        transport=RecordingTransport(
            Response(
                202,
                dumps(
                    {
                        "schema_version": "1",
                        "contact_id": "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
                        "disposition": "replayed",
                    }
                ).encode(),
            )
        ),
    )

    with pytest.raises(CompletedFt8IngestionError, match="HTTP 409"):
        failed.enqueue(_event())
    with pytest.raises(CompletedFt8IngestionError, match="different contact ID"):
        wrong.enqueue(_event())


def _event() -> CompletedFt8QsoEvent:
    contact = Contact(
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
    attempt = FT8PerformanceAttempt(
        attempt_id=CONTACT_ID,
        callsign="KC1OXG",
        outcome=FT8AttemptOutcome.COMPLETED,
        success=True,
        terminal_state="completed",
        terminal_reason=None,
        started_at_utc=NOW,
        ended_at_utc=NOW + timedelta(seconds=75),
        utc_date=NOW.date(),
        band="20m",
        dial_frequency_hz=14_074_000,
        tx_power_target_watts=55,
        sent_report_db=-10,
        received_report_db=-12,
        local_grid="EM79xp",
        remote_grid="FN31pr",
        audio_frequency_hz=1500,
        attempt_count=3,
        last_qso_state="completed",
    )
    return CompletedFt8QsoEvent(contact=contact, terminal_attempt=attempt)
