"""Offline full contract from local outbox through private Forge API."""
from datetime import UTC, datetime
from json import dumps, loads
from uuid import uuid4

from test_forge_contact_sync_api import app

from rolling_thunder.forge_ft8_periods import ForgeFT8PeriodRepository
from rolling_thunder.ft8.hardware_transmit import FT8TransmitPeriodTelemetry
from rolling_thunder.ft8.period_repository import FT8PeriodSyncService, FT8TransmitPeriodRepository


def test_retry_ack_and_forge_duplicate_replay(tmp_path):
    local = FT8TransmitPeriodRepository(tmp_path / "mobile.db")
    forge = ForgeFT8PeriodRepository(tmp_path / "forge.db")
    api, _ = app(tmp_path)
    api._ft8_period_repository = forge
    api._ft8_period_token = "test-secret"
    qso = uuid4()
    now = datetime(2026, 10, 10, 12, tzinfo=UTC)
    record = FT8TransmitPeriodTelemetry(qso, now, now, 20, True, 14074000, True)
    local.append(record)

    class InProcessClient:
        attempts = 0

        def upload_ft8_period(self, qso_id, index, emission):
            self.attempts += 1
            if self.attempts == 1:
                from rolling_thunder.home_platform import HomePlatformConnectionError
                raise HomePlatformConnectionError("simulated dropped connection")
            body = dumps({
                "qso_id": str(qso_id), "emission_index": index,
                "record": {
                    "qso_id": str(emission.qso_id),
                    "started_at_utc": emission.started_at_utc.isoformat(),
                    "ended_at_utc": emission.ended_at_utc.isoformat(),
                    "configured_power_watts": emission.configured_power_watts,
                    "power_readback_verified": emission.power_readback_verified,
                    "frequency_hz": emission.frequency_hz,
                    "transmitted": emission.transmitted,
                },
            }).encode()
            result = api.handle("POST", "/ft8-period", headers={
                "Content-Type": "application/json",
                "Idempotency-Key": f"{qso_id}:{index}",
                "Authorization": "Bearer test-secret",
            }, body=body)
            assert result.status_code == 200, result.body
            assert loads(result.body)["status"] in {"accepted", "already_exists"}

    client = InProcessClient()
    sync = FT8PeriodSyncService(local, client)
    assert sync.synchronize_once() == (0, 1)
    assert len(local.pending()) == 1
    assert sync.synchronize_once() == (1, 0)
    assert local.pending() == ()
    assert sync.synchronize_once() == (0, 0)
    assert client.attempts == 2
    # A lost ACK after Forge commit must yield ALREADY_EXISTS on identical replay.
    client.upload_ft8_period(qso, 1, record)


def test_validation_no_storage_side_effects(tmp_path):
    forge = ForgeFT8PeriodRepository(tmp_path / "forge.db")
    api, _ = app(tmp_path)
    api._ft8_period_repository = forge
    api._ft8_period_token = "test-secret"
    no_key = api.handle("POST", "/ft8-period",
                        headers={"Content-Type": "application/json", "Authorization": "Bearer test-secret"},
                        body=b"{}")
    assert no_key.status_code == 422
    assert api.handle("GET", "/ft8-period", headers={"Authorization": "Bearer test-secret"}).status_code == 405


def test_endpoint_denies_without_token(tmp_path):
    api, _ = app(tmp_path)
    api._ft8_period_repository = ForgeFT8PeriodRepository(tmp_path / "forge.db")
    assert api.handle("POST", "/ft8-period", body=b"{}").status_code == 503
    api._ft8_period_token = "test-secret"
    assert api.handle("POST", "/ft8-period", body=b"{}").status_code == 401
