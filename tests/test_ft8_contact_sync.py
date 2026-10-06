"""Completed FT8 contacts use the composed shared Forge/Mobile sync path."""

from collections.abc import Mapping
from concurrent.futures import Executor, Future
from datetime import UTC, datetime, timedelta
from json import dumps, loads
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import pytest
from pydantic import SecretStr

from rolling_thunder import application_runtime, ui_main
from rolling_thunder.application_runtime import ApplicationRuntime
from rolling_thunder.application_secrets import ApplicationSecrets, QrzCredentials
from rolling_thunder.config import ApplicationConfig
from rolling_thunder.contact_repository import ContactRepository
from rolling_thunder.domain import ContactEnrichmentState, RadioMode, SynchronizationState
from rolling_thunder.forge_contact_sync import ForgeContactSyncRepository, ForgeContactSyncService
from rolling_thunder.forge_contact_sync_api import ForgeContactSyncApiApplication
from rolling_thunder.ft8.coordinator import FT8QsoResult
from rolling_thunder.ft8.domain import FT8Period, FT8PeriodParity, FT8QsoContext, FT8QsoState
from rolling_thunder.ft8.worked_today import FT8WorkedTodayService
from rolling_thunder.home_platform import ContactUploadDisposition, ContactUploadRequest
from rolling_thunder.http_home_platform import UrllibHttpResponse
from rolling_thunder.log_panel import ContactLogRepository, LogPanelController
from rolling_thunder.radio import RadioBand
from rolling_thunder.wavelog import WavelogClient


class QueuedExecutor(Executor):
    """Keep background work deterministic and distinct from contact completion."""

    def __init__(self) -> None:
        self.jobs: list[tuple[Future[Any], Any, tuple[Any, ...], dict[str, Any]]] = []

    def submit(self, fn: Any, /, *args: Any, **kwargs: Any) -> Future[Any]:
        future: Future[Any] = Future()
        self.jobs.append((future, fn, args, kwargs))
        return future

    def run(self) -> None:
        future, fn, args, kwargs = self.jobs.pop(0)
        future.set_result(fn(*args, **kwargs))


class WavelogTransport:
    def __init__(self) -> None:
        self.imports: list[dict[str, Any]] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout_s: float,
    ) -> UrllibHttpResponse:
        if method == "GET" and url.endswith("/api/v2/station"):
            payload = {
                "data": [
                    {
                        "id": 7,
                        "uuid": "home",
                        "name": "Home",
                        "callsign": "KI5VNB",
                        "gridsquare": "EM00aa",
                        "dxcc": 291,
                        "cq": 4,
                        "itu": 8,
                        "state": "OH",
                    },
                    {
                        "id": 93,
                        "uuid": "mobile",
                        "name": "Mobile",
                        "callsign": "KI5VNB",
                        "gridsquare": "EM79xm",
                        "dxcc": 291,
                        "cq": 4,
                        "itu": 8,
                        "state": "OH",
                    },
                ]
            }
        elif method == "GET" and url.endswith("/api/v2/logbook"):
            payload = {
                "data": [
                    {
                        "id": 5,
                        "name": "KI5VNB Main",
                        "active": True,
                        "station_ids": [7, 93],
                    }
                ]
            }
        else:
            assert method == "POST" and url.endswith("/api/v2/qso")
            assert body is not None
            self.imports.append(loads(body))
            payload = {"data": {"parsed": 1, "imported": 1, "skipped": 0}}
        return UrllibHttpResponse(200, dumps(payload).encode())


class ForgeTransport:
    def __init__(self, app: ForgeContactSyncApiApplication) -> None:
        self.app = app
        self.keys: list[str] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout_s: float,
    ) -> UrllibHttpResponse:
        self.keys.append(headers["Idempotency-Key"])
        response = self.app.handle(method, urlsplit(url).path, headers=headers, body=body)
        return UrllibHttpResponse(response.status_code, response.body)


class QrzTransport:
    def __init__(self, *, available: bool) -> None:
        self.available = available

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout_s: float,
    ) -> UrllibHttpResponse:
        if not self.available:
            return UrllibHttpResponse(503, b"unavailable")
        return UrllibHttpResponse(
            200,
            b"""
            <QRZDatabase><Session><Key>test-session</Key></Session>
            <Callsign><call>K1ABC</call><grid>FN42</grid></Callsign></QRZDatabase>
        """,
        )


def config(tmp_path: Path) -> ApplicationConfig:
    return ApplicationConfig.model_validate(
        {
            "operator": {"callsign": "KI5VNB", "home_grid": "EM79xm"},
            "hardware": {"mock": True},
            "map": {"enabled": False},
            "ft8": {"enabled": True, "receive": {"decoder_executable": "/unused/decode_ft8"}},
            "home_platform": {"enabled": True, "base_url": "https://forge.invalid"},
            "storage": {"database_path": tmp_path / "contacts.db"},
        }
    )


def result(
    *, remote_grid: str | None = "FN31pr", status: FT8QsoState = FT8QsoState.COMPLETED
) -> FT8QsoResult:
    period = FT8Period(100)
    started = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)
    return FT8QsoResult(
        status=status,
        context=FT8QsoContext(
            local_callsign="KI5VNB",
            remote_callsign="K1ABC",
            target_audio_frequency_hz=1500,
            radio_frequency_hz=14_074_000,
            radio_band="20m",
            radio_mode="USB",
            local_grid="EM79xm",
            latitude=39.5309,
            longitude=-84.0866,
            remote_grid=remote_grid,
            tx_parity=FT8PeriodParity.ODD,
            authorized_period=period,
            authorized_utc=period.start_utc,
            signal_report_db=14,
            qso_id=UUID("00000000-0000-0000-0000-000000000901"),
        ),
        sent_report_db=14,
        received_report_db=-10,
        started_utc=started,
        ended_utc=started + timedelta(seconds=75),
        terminal_reason=None,
    )


@pytest.mark.parametrize(
    ("remote_grid", "qrz_available", "qrz_enabled"),
    [
        ("FN31pr", False, True),
        (None, False, True),
        (None, True, True),
        (None, False, False),
    ],
)
def test_completed_ft8_uses_shared_sync_and_configured_mobile(
    tmp_path: Path,
    remote_grid: str | None,
    qrz_available: bool,
    qrz_enabled: bool,
) -> None:
    wavelog_transport = WavelogTransport()
    forge_repository = ForgeContactSyncRepository(tmp_path / "forge.db")
    forge = ForgeContactSyncApiApplication(
        ForgeContactSyncService(
            forge_repository,
            WavelogClient(
                "https://wavelog.invalid",
                SecretStr("test-only"),
                station_location_name="Mobile",
                station_logbook_name="KI5VNB Main",
                transport=wavelog_transport,
                station_binding_store=forge_repository,
            ),
        )
    )
    transport = ForgeTransport(forge)
    runtime = ApplicationRuntime.from_config(
        config(tmp_path),
        home_platform_transport=transport,
        qrz_transport=QrzTransport(available=qrz_available),
        secrets=ApplicationSecrets(
            qrz=QrzCredentials(
                username="test-only",
                password=SecretStr("test-only"),
            )
            if qrz_enabled
            else None
        ),
    )
    assert runtime.ft8_logging is not None
    assert runtime.contact_sync is not None
    repository = ContactRepository(config(tmp_path).storage.database_path)
    completed = result(remote_grid=remote_grid)
    try:
        contact = runtime.ft8_logging.handle_terminal_result(completed)
        assert contact is not None
        assert contact.contact_id == completed.context.qso_id
        assert contact.synchronization_state is SynchronizationState.PENDING
        assert contact.mode is RadioMode.FT8
        assert contact.started_at == completed.started_utc
        assert contact.my_grid == "EM79xm"
        assert contact.grid == remote_grid
        assert contact.rst_sent == "+14" and contact.rst_received == "-10"
        if remote_grid is None and qrz_enabled:
            assert contact.enrichment_state is ContactEnrichmentState.PENDING_QRZ
            assert runtime.contact_sync.synchronize_due_now().attempted == 0
            assert runtime.contact_qrz_enrichment is not None
            assert runtime.contact_qrz_enrichment.enrich_now().completed == 1
        assert runtime.contact_sync.synchronize_due_now().synchronized == 1
        persisted = repository.get(contact.contact_id)
        assert persisted is not None
        assert persisted.enrichment_state is ContactEnrichmentState.READY
        assert persisted.synchronization_state is SynchronizationState.SYNCHRONIZED
        expected_grid = remote_grid or ("FN42" if qrz_enabled and qrz_available else None)
        assert persisted.grid == expected_grid
        assert persisted.my_grid == contact.my_grid
        assert transport.keys == [str(contact.contact_id)]
        assert len(wavelog_transport.imports) == 1
        imported = wavelog_transport.imports[0]
        assert imported["station_profile_id"] == 93
        assert "<MODE:3>FT8" in imported["adif"]
        assert "<MY_GRIDSQUARE:6>EM79xm" in imported["adif"]
        assert "<RST_SENT:3>+14" in imported["adif"]
        assert "<RST_RCVD:3>-10" in imported["adif"]
        assert "<QSO_DATE:8>20261004" in imported["adif"]
        assert "<TIME_ON:6>120000" in imported["adif"]
        assert "<FREQ:6>14.074" in imported["adif"]
        if expected_grid is not None:
            assert f"<GRIDSQUARE:{len(expected_grid)}>{expected_grid}" in imported["adif"]
        else:
            assert "<GRIDSQUARE:" not in imported["adif"]
        replay = runtime.ft8_logging.handle_terminal_result(completed)
        assert persisted.my_latitude == 39.5309
        assert persisted.my_longitude == -84.0866
        assert replay == persisted
        assert runtime.contact_sync.synchronize_now().attempted == 0
        assert len(repository.list_all()) == len(wavelog_transport.imports) == 1
        # The Forge ledger also recognizes explicit retries without another Wavelog write.
        assert runtime.home_platform_client is not None
        duplicate = runtime.home_platform_client.upload_contact(
            ContactUploadRequest(contact=persisted)
        )
        assert duplicate.disposition is ContactUploadDisposition.ALREADY_EXISTS
        assert len(wavelog_transport.imports) == 1
    finally:
        runtime.stop()


def test_dashboard_ft8_completion_requests_same_background_sync(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise dashboard/runtime wiring without starting Tk, timers, or hardware."""
    monkeypatch.setattr(
        application_runtime,
        "FT8WorkedTodayService",
        lambda repository: FT8WorkedTodayService(repository, clock=lambda: result().started_utc),
    )
    executor = QueuedExecutor()
    original_from_config = ApplicationRuntime.from_config
    runtimes: list[ApplicationRuntime] = []
    panels: list[LogPanelController] = []

    def build_runtime(app_config: ApplicationConfig, **kwargs: Any) -> ApplicationRuntime:
        runtime = original_from_config(app_config, **kwargs)
        runtimes.append(runtime)
        return runtime

    class StopBeforeTk(Exception):
        pass

    class TestLogPanel(LogPanelController):
        def __init__(self, repository: ContactLogRepository, sync: Any) -> None:
            super().__init__(repository, sync, executor=executor)
            panels.append(self)

        def start(self) -> Any:
            logging = runtimes[0].ft8_logging
            assert logging is not None
            for state in (
                FT8QsoState.ABORTED,
                FT8QsoState.RETRY_EXHAUSTED,
                FT8QsoState.ERROR,
                FT8QsoState.IDLE,
            ):
                assert logging.handle_terminal_result(result(status=state)) is None
            assert executor.jobs == []
            assert logging.handle_terminal_result(result()) is not None
            assert runtimes[0].ft8_worked_today is not None
            assert runtimes[0].ft8_worked_today.is_suppressed("K1ABC", RadioBand.BAND_20M)
            raise StopBeforeTk

    monkeypatch.setattr(ui_main, "load_config", lambda _path: config(tmp_path))
    monkeypatch.setattr(ui_main, "load_application_secrets", ApplicationSecrets)
    monkeypatch.setattr(ApplicationRuntime, "from_config", build_runtime)
    monkeypatch.setattr(ApplicationRuntime, "start", lambda _self: None)
    monkeypatch.setattr(ui_main, "LogPanelController", TestLogPanel)
    try:
        with pytest.raises(StopBeforeTk):
            ui_main.run_dashboard()
        assert len(executor.jobs) == 1, "completed FT8 must request background contact sync"
        assert panels[0].latest_state.syncing
    finally:
        for runtime in runtimes:
            runtime.stop()
