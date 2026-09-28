"""Tests for QRZ contact enrichment runtime composition."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pydantic import SecretStr

from rolling_thunder.application_runtime import ApplicationRuntime
from rolling_thunder.application_secrets import (
    ApplicationSecrets,
    QrzCredentials,
)
from rolling_thunder.config import ApplicationConfig
from rolling_thunder.contact_repository import ContactRepository
from rolling_thunder.domain import (
    ContactEnrichmentState,
    ContactGridSource,
    Frequency,
    RadioConnectionState,
    RadioMode,
    RadioState,
)
from rolling_thunder.radio_polling import PollCallback


@dataclass(frozen=True)
class FakeResponse:
    status_code: int
    body: bytes


class SequenceTransport:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.requests: list[str] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout_s: float,
    ) -> FakeResponse:
        del method, headers, body, timeout_s
        self.requests.append(url)
        return self.responses.pop(0)


class ManualScheduledPoll:
    def __init__(self, callback: PollCallback) -> None:
        self.callback = callback
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True

    def fire(self) -> None:
        if not self.cancelled:
            self.callback()


class ManualScheduler:
    def __init__(self) -> None:
        self.interval_s: float | None = None
        self.poll: ManualScheduledPoll | None = None

    def schedule_repeating(
        self,
        interval_s: float,
        callback: PollCallback,
    ) -> ManualScheduledPoll:
        self.interval_s = interval_s
        self.poll = ManualScheduledPoll(callback)
        return self.poll

    def fire(self) -> None:
        assert self.poll is not None
        self.poll.fire()


def xml(body: str) -> FakeResponse:
    return FakeResponse(
        status_code=200,
        body=body.encode("utf-8"),
    )


def config(database_path: Path) -> ApplicationConfig:
    return ApplicationConfig.model_validate(
        {
            "operator": {
                "callsign": "KI5VNB",
                "home_grid": "EM79xm",
            },
            "hardware": {"mock": True},
            "storage": {
                "database_path": str(database_path),
            },
            "pota_spots": {
                "enabled": False,
            },
        }
    )


def qrz_secrets() -> ApplicationSecrets:
    return ApplicationSecrets(
        qrz=QrzCredentials(
            username="KI5VNB",
            password=SecretStr("private-value"),
        )
    )


def connected_radio_state() -> RadioState:
    return RadioState(
        connection_state=RadioConnectionState.CONNECTED,
        frequency=Frequency(hz=14_250_000),
        mode=RadioMode.USB,
        transmitting=False,
        updated_at=datetime(2026, 8, 2, 23, 0, tzinfo=UTC),
    )


def test_runtime_enriches_contact_when_pota_is_disabled(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "contacts.db"
    qrz_scheduler = ManualScheduler()
    transport = SequenceTransport(
        [
            xml(
                """
                <QRZDatabase>
                  <Session><Key>SESSION-1</Key></Session>
                </QRZDatabase>
                """
            ),
            xml(
                """
                <QRZDatabase>
                  <Callsign>
                    <call>KI5VNB</call>
                    <grid>em79XM</grid>
                  </Callsign>
                  <Session><Key>SESSION-1</Key></Session>
                </QRZDatabase>
                """
            ),
        ]
    )
    runtime = ApplicationRuntime.from_config(
        config(database_path),
        secrets=qrz_secrets(),
        scheduler=ManualScheduler(),
        gps_scheduler=ManualScheduler(),
        contact_qrz_enrichment_scheduler=qrz_scheduler,
        qrz_transport=transport,
    )

    assert runtime.pota_spot_polling is None
    assert runtime.contact_qrz_enrichment is not None

    contact = runtime.contact_logging.commit(
        pending_callsign="KI5VNB",
        radio_state=connected_radio_state(),
    )

    assert contact.grid is None
    assert contact.enrichment_state is ContactEnrichmentState.PENDING_QRZ

    runtime.start()
    assert runtime.contact_qrz_enrichment.is_running is True
    assert transport.requests == []

    qrz_scheduler.fire()

    persisted = ContactRepository(database_path).get(contact.contact_id)
    assert persisted is not None
    assert persisted.grid == "EM79xm"
    assert persisted.grid_source is ContactGridSource.QRZ
    assert persisted.enrichment_state is ContactEnrichmentState.READY
    assert len(transport.requests) == 2

    runtime.stop()
    assert runtime.contact_qrz_enrichment.is_running is False
    assert qrz_scheduler.poll is not None
    assert qrz_scheduler.poll.cancelled is True


def test_runtime_without_qrz_credentials_logs_ready_contact(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "contacts.db"
    runtime = ApplicationRuntime.from_config(
        config(database_path),
        scheduler=ManualScheduler(),
        gps_scheduler=ManualScheduler(),
        contact_qrz_enrichment_scheduler=ManualScheduler(),
    )

    assert runtime.contact_qrz_enrichment is None

    contact = runtime.contact_logging.commit(
        pending_callsign="W8O",
        radio_state=connected_radio_state(),
    )

    assert contact.grid is None
    assert contact.grid_source is None
    assert contact.enrichment_state is ContactEnrichmentState.READY
