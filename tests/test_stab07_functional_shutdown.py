"""STAB-07 deterministic runtime safety tests with disposable mock devices."""

from __future__ import annotations

from pathlib import Path
from threading import Event, Thread

import pytest

from rolling_thunder.application_runtime import ApplicationRuntime
from rolling_thunder.config import ApplicationConfig
from rolling_thunder.domain import RadioConnectionState
from rolling_thunder.gps import GPSConnectionState


def _runtime(tmp_path: Path) -> ApplicationRuntime:
    """Create an isolated runtime with no physical adapters or network clients."""
    cfg = ApplicationConfig.model_validate({
        "operator": {"callsign": "KI5VNB", "home_grid": "EM79xm"},
        "hardware": {"mock": True, "radio_mode": "mock", "gps_mode": "mock"},
        "speech": {"enabled": False}, "tron": {"enabled": False},
        "forge": {"enabled": False}, "ft8": {"enabled": False},
        "pota_map": {"enabled": False},
        "storage": {"database_path": str(tmp_path / "runtime.sqlite3")},
    })
    return ApplicationRuntime.from_config(cfg)


def test_duplicate_start_rejected_without_disconnecting_live_mock(tmp_path: Path) -> None:
    """A rejected second start cannot undo resources owned by the first."""
    runtime = _runtime(tmp_path)
    runtime.start()
    try:
        with pytest.raises(RuntimeError, match="already started"):
            runtime.start()
        assert runtime._started
        assert runtime.radio.get_state().connection_state is RadioConnectionState.CONNECTED
        assert runtime.polling.is_running
    finally:
        runtime.stop()


def test_blocked_nonradio_worker_does_not_delay_radio_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """While a fake unrelated worker blocks, the radio has already released."""
    runtime = _runtime(tmp_path)
    runtime.start()
    reached = Event()
    release = Event()
    finished = Event()
    errors: list[Exception] = []

    def blocked_enrichment() -> None:
        reached.set()
        assert release.wait(timeout=3.0)

    monkeypatch.setattr(runtime.pota_enrichment, "stop", blocked_enrichment)

    def shutdown() -> None:
        try:
            runtime.stop()
        except Exception as exc:  # noqa: BLE001 - report fake shutdown failures
            errors.append(exc)
        finally:
            finished.set()

    worker = Thread(target=shutdown, daemon=True)
    worker.start()
    try:
        assert reached.wait(timeout=2.0)
        assert runtime.radio.get_state().connection_state is RadioConnectionState.DISCONNECTED
        assert not finished.is_set()
    finally:
        release.set()
        worker.join(timeout=3.0)
    assert finished.is_set()
    assert not worker.is_alive()
    assert errors == []
    assert runtime._started is False
    assert runtime.gps is not None
    assert runtime.gps.get_state().connection_state is GPSConnectionState.DISCONNECTED


def test_failed_mock_radio_disconnect_is_reported_and_retryable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Failed disconnect must not be mislabeled as a successful shutdown."""
    runtime = _runtime(tmp_path)
    runtime.start()
    original_disconnect = runtime.radio.disconnect
    failures = 0

    def fail_once() -> object:
        nonlocal failures
        failures += 1
        if failures == 1:
            raise RuntimeError("synthetic radio disconnect failure")
        return original_disconnect()

    monkeypatch.setattr(runtime.radio, "disconnect", fail_once)
    with pytest.raises(ExceptionGroup, match="Rolling Thunder shutdown errors") as caught:
        runtime.stop()
    assert any("radio disconnect" in str(e) for e in caught.value.exceptions)
    assert runtime._started is True
    assert runtime.radio.get_state().connection_state is RadioConnectionState.CONNECTED
    assert runtime.gps is not None
    assert runtime.gps.get_state().connection_state is GPSConnectionState.DISCONNECTED
    runtime.stop()
    assert runtime._started is False
    assert runtime.radio.get_state().connection_state is RadioConnectionState.DISCONNECTED


def test_failed_mock_gps_disconnect_does_not_prevent_radio_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A GPS disconnect failure cannot undo the earlier radio release."""
    runtime = _runtime(tmp_path)
    runtime.start()
    gps = runtime.gps
    assert gps is not None

    def broken_gps() -> None:
        raise RuntimeError("synthetic GPS unplug disconnect failure")

    monkeypatch.setattr(gps, "disconnect", broken_gps)
    with pytest.raises(ExceptionGroup, match="Rolling Thunder shutdown errors") as caught:
        runtime.stop()
    assert any("GPS: synthetic GPS unplug" in str(e) for e in caught.value.exceptions)
    assert runtime.radio.get_state().connection_state is RadioConnectionState.DISCONNECTED
    assert runtime._started is False
