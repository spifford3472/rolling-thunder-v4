from datetime import UTC, datetime, timedelta
from json import loads
from pathlib import Path
from uuid import UUID

from rolling_thunder.forge_ft8_attempt_api import FT8AttemptApiApplication
from rolling_thunder.forge_ft8_attempt_correlation import (
    AttemptInboxRepository,
    VoacapAttemptHistoryRepository,
)
from rolling_thunder.forge_propagation_qso_api import (
    CompletedQsoIngestionApiApplication,
)
from rolling_thunder.forge_propagation_qso_ingestion import (
    CompletedQsoIngestionRepository,
)
from rolling_thunder.ft8.attempt_ledger import (
    FT8AttemptClassification,
    FT8AttemptEvent,
)
from rolling_thunder.ft8.performance import FT8AttemptOutcome
from rolling_thunder.ft8_attempt_ingestion_client import HttpFT8AttemptIngestionClient

NOW = datetime(2026, 10, 11, 23, 59, 50, tzinfo=UTC)
ATTEMPT = UUID("11111111-2222-4333-8444-555555555555")

TOKEN = "attempt-test-token-that-is-long-enough"


def _event() -> FT8AttemptEvent:
    return FT8AttemptEvent(
        attempt_uuid=ATTEMPT,
        source_event_created_utc=NOW,
        started_at_utc=NOW,
        ended_at_utc=NOW + timedelta(seconds=30),
        classification=FT8AttemptClassification.NO_ANSWER,
        source_outcome=FT8AttemptOutcome.RETRY_EXHAUSTED,
        terminal_phase="retry_exhausted",
        terminal_reason="no answer",
        remote_callsign="KC1OXG",
        band="20m",
        dial_frequency_hz=14_074_000,
        local_grid="EM79xp",
        remote_grid="FN31",
        remote_grid_source="decoded_ft8",
        transmit_attempt_count=1,
        busy_extension_attempts=0,
    )


def test_api_authenticates_before_ingestion_and_serves_read_only_diagnostics(
    tmp_path: Path,
) -> None:
    inbox = AttemptInboxRepository(tmp_path / "inbox.sqlite")
    history = VoacapAttemptHistoryRepository(tmp_path / "history.sqlite")
    api = FT8AttemptApiApplication(
        inbox,
        history,
        bearer_token=TOKEN,
        ingestion_enabled=True,
        clock=lambda: NOW,
    )
    event = _event()
    assert api.handle("POST", "/api/v1/ft8-attempts", body=b"not-json").status_code == 401
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
        "Idempotency-Key": str(ATTEMPT),
    }
    accepted = api.handle(
        "POST", "/api/v1/ft8-attempts", headers=headers, body=event.model_dump_json().encode()
    )
    replay = api.handle(
        "POST", "/api/v1/ft8-attempts", headers=headers, body=event.model_dump_json().encode()
    )
    diagnostics = api.handle("GET", f"/api/v1/ft8-attempts/{ATTEMPT}", headers=headers)
    assert accepted.status_code == 202
    assert replay.status_code == 200
    assert loads(diagnostics.body)["attempt"]["event"]["attempt_uuid"] == str(ATTEMPT)


def test_disabled_api_rejects_ingestion_but_keeps_existing_diagnostics_readable(
    tmp_path: Path,
) -> None:
    inbox = AttemptInboxRepository(tmp_path / "inbox.sqlite")
    history = VoacapAttemptHistoryRepository(tmp_path / "history.sqlite")
    inbox.enqueue(_event(), received_at_utc=datetime.now(UTC))
    api = FT8AttemptApiApplication(
        inbox,
        history,
        bearer_token=TOKEN,
        ingestion_enabled=False,
    )
    headers = {"Authorization": f"Bearer {TOKEN}"}
    assert api.handle("POST", "/api/v1/ft8-attempts", headers=headers).status_code == 503
    assert api.handle("GET", f"/api/v1/ft8-attempts/{ATTEMPT}", headers=headers).status_code == 200


def test_typed_client_and_api_round_trip_without_provider_work(tmp_path: Path) -> None:
    inbox = AttemptInboxRepository(tmp_path / "inbox.sqlite")
    api = FT8AttemptApiApplication(
        inbox,
        VoacapAttemptHistoryRepository(tmp_path / "history.sqlite"),
        bearer_token=TOKEN,
        ingestion_enabled=True,
        clock=lambda: NOW,
    )

    class Transport:
        def request(self, method, _url, *, headers, body, timeout_s):
            assert timeout_s == 2
            return api.handle(method, "/api/v1/ft8-attempts", headers=headers, body=body)

    acknowledged = HttpFT8AttemptIngestionClient(
        "http://forge.test:8790",
        bearer_token=TOKEN,
        timeout_s=2,
        transport=Transport(),
    ).deliver(_event())

    assert acknowledged == ATTEMPT
    assert inbox.snapshot(ATTEMPT) is not None


def test_shared_listener_health_reports_attempt_queue_without_provider_work(
    tmp_path: Path,
) -> None:
    inbox = AttemptInboxRepository(tmp_path / "inbox.sqlite")
    attempt_api = FT8AttemptApiApplication(
        inbox,
        VoacapAttemptHistoryRepository(tmp_path / "history.sqlite"),
        bearer_token=TOKEN,
        ingestion_enabled=True,
        clock=lambda: NOW,
    )
    inbox.enqueue(_event(), received_at_utc=NOW)
    application = CompletedQsoIngestionApiApplication(
        CompletedQsoIngestionRepository(tmp_path / "qso.sqlite"),
        bearer_token=TOKEN,
        ingestion_enabled=True,
        voacap_enabled=False,
        clock=lambda: NOW,
        attempt_application=attempt_api,
    )

    health = loads(application.handle("GET", "/health").body)

    assert health["attempts"]["queue"]["pending_count"] == 1
    assert health["attempts"]["queue"]["due_count"] == 1


def test_real_http_framing_completes_without_waiting_for_connection_close(
    tmp_path: Path,
) -> None:
    """A persistent HTTP/1.1 peer must not hang on attempt API responses."""
    from http.client import HTTPConnection
    from threading import Thread

    from rolling_thunder.forge_propagation_qso_api import CompletedQsoHttpServer

    inbox = AttemptInboxRepository(tmp_path / "attempt-inbox.sqlite")
    history = VoacapAttemptHistoryRepository(tmp_path / "attempt-history.sqlite")
    app = CompletedQsoIngestionApiApplication(
        CompletedQsoIngestionRepository(tmp_path / "qso-inbox.sqlite"),
        bearer_token=TOKEN,
        ingestion_enabled=True,
        voacap_enabled=False,
        attempt_application=FT8AttemptApiApplication(
            inbox, history, bearer_token=TOKEN, ingestion_enabled=True
        ),
    )
    server = CompletedQsoHttpServer("127.0.0.1", 0, app, request_timeout_s=2, max_connections=4)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = HTTPConnection(*server.server_address, timeout=1)
    try:
        event = _event()
        payload = event.model_dump_json().encode()
        headers = {
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
            "Idempotency-Key": str(event.attempt_uuid),
        }
        for method, path, data, request_headers, expected in (
            ("GET", "/api/v1/ft8-attempts", None, {}, 401),
            ("POST", "/api/v1/ft8-attempts", payload, headers, 202),
            ("POST", "/api/v1/ft8-attempts", payload, headers, 200),
            (
                "POST",
                "/api/v1/ft8-attempts",
                event.model_copy(update={"terminal_reason": "changed"}).model_dump_json().encode(),
                headers,
                409,
            ),
            ("GET", f"/api/v1/ft8-attempts/{event.attempt_uuid}", None, headers, 200),
        ):
            connection.request(method, path, body=data, headers=request_headers)
            response = connection.getresponse()
            assert response.status == expected
            raw_length = response.getheader("Content-Length")
            assert raw_length is not None
            body = response.read()  # Would time out with the former missing length.
            assert len(body) == int(raw_length)
    finally:
        connection.close()
        server.shutdown()
        server.close()
        thread.join(timeout=3)


def test_v2_frozen_selection_prospective_event_ingests_without_rewriting_v1(
    tmp_path: Path,
) -> None:
    v1 = _event()
    assert "choice_at_utc" not in v1.model_dump(mode="json")
    v2 = v1.model_copy(
        update={
            "schema_version": 2,
            "choice_at_utc": NOW - timedelta(minutes=1),
        }
    )
    api = FT8AttemptApiApplication(
        AttemptInboxRepository(tmp_path / "inbox.sqlite"),
        VoacapAttemptHistoryRepository(tmp_path / "history.sqlite"),
        bearer_token=TOKEN,
        ingestion_enabled=True,
        clock=lambda: NOW,
    )
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
        "Idempotency-Key": str(ATTEMPT),
    }
    first = api.handle(
        "POST", "/api/v1/ft8-attempts", headers=headers, body=v2.model_dump_json().encode()
    )
    assert first.status_code == 202
    retained = loads(
        api.handle(
            "GET", f"/api/v1/ft8-attempts/{ATTEMPT}", headers=headers
        ).body
    )["attempt"]["event"]
    assert retained["schema_version"] == 2
    assert retained["choice_at_utc"] == v2.choice_at_utc.isoformat().replace("+00:00", "Z")
