"""Provider-free tests for authenticated completed-QSO ingestion."""

from collections.abc import Mapping
from datetime import UTC, datetime
from json import dumps, loads
from pathlib import Path
from uuid import UUID

from rolling_thunder.completed_qso_ingestion_client import HttpCompletedQsoIngestionClient
from rolling_thunder.domain import Contact, ContactSource, RadioMode
from rolling_thunder.forge_propagation_qso_api import (
    CompletedQsoHttpResponse,
    CompletedQsoIngestionApiApplication,
)
from rolling_thunder.forge_propagation_qso_ingestion import CompletedQsoIngestionRepository

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
TOKEN = "test-token-that-is-at-least-32-characters-long"
CONTACT_ID = UUID("11111111-2222-4333-8444-555555555555")


def test_health_is_provider_free_and_reports_queue(tmp_path: Path) -> None:
    repository = CompletedQsoIngestionRepository(tmp_path / "inbox.sqlite3")
    application = _application(repository, voacap_enabled=False)

    response = application.handle("GET", "/health")
    payload = loads(response.body)

    assert response.status_code == 200
    assert payload["service"] == "rolling-thunder-forge-propagation-qso"
    assert payload["ingestion_enabled"] is True
    assert payload["voacap_enabled"] is False
    assert payload["queue"]["pending_count"] == 0


def test_ingestion_requires_authentication_before_payload_processing(tmp_path: Path) -> None:
    application = _application(CompletedQsoIngestionRepository(tmp_path / "inbox.sqlite3"))

    missing = application.handle("POST", "/api/v1/completed-qsos", body=b"not-json")
    wrong = application.handle(
        "POST",
        "/api/v1/completed-qsos",
        headers={"Authorization": "Bearer wrong-token"},
        body=b"not-json",
    )

    assert missing.status_code == 401
    assert wrong.status_code == 401


def test_authenticated_ingestion_is_durable_and_uuid_idempotent(tmp_path: Path) -> None:
    repository = CompletedQsoIngestionRepository(tmp_path / "inbox.sqlite3")
    application = _application(repository)
    contact = _contact()
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
        "Idempotency-Key": str(contact.contact_id),
    }
    body = dumps(contact.model_dump(mode="json")).encode()

    accepted = application.handle(
        "POST", "/api/v1/completed-qsos", headers=headers, body=body
    )
    replayed = application.handle(
        "POST", "/api/v1/completed-qsos", headers=headers, body=body
    )

    assert accepted.status_code == 202
    assert loads(accepted.body)["disposition"] == "accepted"
    assert replayed.status_code == 200
    assert loads(replayed.body)["disposition"] == "replayed"
    assert repository.read(contact.contact_id).contact == contact  # type: ignore[union-attr]


def test_ingestion_rejects_mismatched_key_and_changed_replay(tmp_path: Path) -> None:
    repository = CompletedQsoIngestionRepository(tmp_path / "inbox.sqlite3")
    application = _application(repository)
    contact = _contact()
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
        "Idempotency-Key": str(contact.contact_id),
    }
    body = dumps(contact.model_dump(mode="json")).encode()
    application.handle("POST", "/api/v1/completed-qsos", headers=headers, body=body)

    mismatch_headers = headers | {
        "Idempotency-Key": "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
    }
    mismatch = application.handle(
        "POST", "/api/v1/completed-qsos", headers=mismatch_headers, body=body
    )
    changed = contact.model_copy(update={"tx_power_watts": 60})
    conflict = application.handle(
        "POST",
        "/api/v1/completed-qsos",
        headers=headers,
        body=dumps(changed.model_dump(mode="json")).encode(),
    )

    assert mismatch.status_code == 409
    assert conflict.status_code == 409


def test_disabled_ingestion_fails_before_authentication(tmp_path: Path) -> None:
    application = CompletedQsoIngestionApiApplication(
        CompletedQsoIngestionRepository(tmp_path / "inbox.sqlite3"),
        bearer_token=TOKEN,
        ingestion_enabled=False,
        voacap_enabled=False,
        clock=lambda: NOW,
    )

    response = application.handle("POST", "/api/v1/completed-qsos")

    assert response.status_code == 503
    assert loads(response.body)["error"]["code"] == "ingestion_disabled"


def test_transport_contract_smoke_ingests_without_provider(tmp_path: Path) -> None:
    repository = CompletedQsoIngestionRepository(tmp_path / "inbox.sqlite3")
    application = _application(repository, voacap_enabled=False)
    result = HttpCompletedQsoIngestionClient(
        "http://forge.test:8790",
        bearer_token=TOKEN,
        timeout_s=2,
        transport=ApplicationTransport(application),
    ).enqueue(_contact())
    health = loads(application.handle("GET", "/health").body)

    assert result.disposition == "accepted"
    assert health["voacap_enabled"] is False
    assert health["queue"]["pending_count"] == 1


class ApplicationTransport:
    """In-memory producer/consumer smoke transport; it cannot reach a provider."""

    def __init__(self, application: CompletedQsoIngestionApiApplication) -> None:
        self._application = application

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout_s: float,
    ) -> CompletedQsoHttpResponse:
        del url, timeout_s
        return self._application.handle(method, "/api/v1/completed-qsos", headers=headers, body=body)


def _application(
    repository: CompletedQsoIngestionRepository,
    *,
    voacap_enabled: bool = True,
) -> CompletedQsoIngestionApiApplication:
    return CompletedQsoIngestionApiApplication(
        repository,
        bearer_token=TOKEN,
        ingestion_enabled=True,
        voacap_enabled=voacap_enabled,
        clock=lambda: NOW,
    )


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
