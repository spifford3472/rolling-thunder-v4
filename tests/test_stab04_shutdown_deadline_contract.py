"""STAB-04 offline shutdown-deadline evidence, not a safety acceptance pass.

The 20-second systemd stop deadline cannot force Python callbacks to complete.
Events let tests observe the blocked phase without sleeping for 20 seconds or
opening hardware. The runtime internal blocked-worker risk remains a separate acceptance gate.
"""

from threading import Barrier, Event, Lock, Thread

import pytest

from rolling_thunder.application_runtime import ApplicationRuntime
from rolling_thunder.config import ApplicationConfig
from rolling_thunder.ui_main import (
    _request_close_once, _run_cleanup_steps, _run_orderly_shutdown,
)


def test_runtime_close_is_reachable_while_unrelated_ui_step_is_stuck() -> None:
    """The UI cleanup worker enters runtime before a blocked peripheral."""
    entered = Event()
    release = Event()
    reached_runtime = Event()
    finished = Event()
    errors: list[str] = []

    def blocked_peripheral() -> None:
        entered.set()
        assert release.wait(timeout=3.0)

    def shutdown() -> None:
        try:
            _run_orderly_shutdown(
                reached_runtime.set,
                (("unrelated UI", blocked_peripheral),),
                errors,
            )
        finally:
            finished.set()

    worker = Thread(target=shutdown, daemon=True)
    worker.start()
    try:
        assert entered.wait(timeout=1.0)
        # A bounded observation, NOT a claim that twenty seconds elapsed.
        assert reached_runtime.wait(timeout=0.05)
    finally:
        release.set()
        worker.join(timeout=3.0)

    assert not worker.is_alive()
    assert finished.is_set()
    assert errors == []


def test_stuck_ui_step_does_not_falsely_report_runtime_cleanup_complete(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Logging must distinguish a blocked step from a completed cleanup."""
    entered = Event()
    release = Event()
    reached_runtime = Event()
    finished = Event()
    errors: list[str] = []

    def blocked_peripheral() -> None:
        entered.set()
        assert release.wait(timeout=3.0)

    def shutdown() -> None:
        try:
            _run_cleanup_steps(
                (
                    ("unrelated UI", blocked_peripheral),
                    ("application runtime", reached_runtime.set),
                ),
                errors,
            )
        finally:
            finished.set()

    worker = Thread(target=shutdown, daemon=True)
    worker.start()
    try:
        assert entered.wait(timeout=1.0)
        output = capsys.readouterr().out
        assert "phase=step_start step='unrelated UI'" in output
        assert "phase=step_end step='unrelated UI'" not in output
        assert "phase=step_start step='application runtime'" not in output
        assert "phase=cleanup_end" not in output
        assert not reached_runtime.is_set()
        assert not finished.is_set()
    finally:
        release.set()
        worker.join(timeout=3.0)

    assert not worker.is_alive()
    assert reached_runtime.is_set()
    assert finished.is_set()
    assert errors == []



def test_runtime_error_is_reported_before_peripheral_cleanup(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A runtime exception does not prevent remaining UI resource cleanup."""
    calls: list[str] = []
    errors: list[str] = []

    def fail_runtime() -> None:
        calls.append("runtime")
        raise RuntimeError("simulated unsafe CAT release")

    _run_orderly_shutdown(
        fail_runtime,
        (("physical controls", lambda: calls.append("controls")),),
        errors,
    )
    output = capsys.readouterr().out
    assert calls == ["runtime", "controls"]
    assert errors == ["application runtime: simulated unsafe CAT release"]
    assert output.index("step='application runtime'") < output.index(
        "step='physical controls'"
    )
    assert "result=error" in output



def test_runtime_shutdown_preserves_ft8_release_before_radio_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No extra PTT path; the existing owner releases before slow workers."""
    config = ApplicationConfig.model_validate(
        {"operator": {"callsign": "KI5VNB", "home_grid": "EM79xm"},
         "hardware": {"mock": True}}
    )
    runtime = ApplicationRuntime.from_config(config)
    runtime.start()
    calls: list[str] = []

    class QsoClose:
        def close(self) -> None:
            calls.append("FT8 QSO")

    class TransmitClose:
        def close(self) -> None:
            calls.append("FT8 transmit")

    class BandRestore:
        def restore_normal_settings_for_shutdown(self) -> None:
            calls.append("band restore")

    runtime.ft8_qso = QsoClose()  # type: ignore[assignment]
    runtime.ft8_hardware_transmit = TransmitClose()  # type: ignore[assignment]
    runtime.ft8_band_control = BandRestore()  # type: ignore[assignment]
    original_stop_polling = runtime.polling.stop
    original_radio_disconnect = runtime.radio.disconnect
    original_pota_stop = runtime.pota_enrichment.stop

    def stop_polling() -> object:
        calls.append("radio polling")
        return original_stop_polling()

    def disconnect() -> object:
        calls.append("radio disconnect")
        return original_radio_disconnect()

    def stop_pota() -> None:
        calls.append("POTA")
        original_pota_stop()

    monkeypatch.setattr(runtime.polling, "stop", stop_polling)
    monkeypatch.setattr(runtime.radio, "disconnect", disconnect)
    monkeypatch.setattr(runtime.pota_enrichment, "stop", stop_pota)

    runtime.stop()
    assert calls == [
        "FT8 QSO", "FT8 transmit", "radio polling", "band restore",
        "radio disconnect", "POTA",
    ]



def test_overlapping_close_requests_launch_exactly_one_worker() -> None:
    """Simultaneous close requests share a single atomic launch decision."""
    started = Event()
    guard = Lock()
    gate = Barrier(3)
    launches: list[str] = []
    results: list[bool] = []

    def request() -> None:
        gate.wait(timeout=3.0)
        results.append(_request_close_once(
            started, guard, lambda: launches.append("worker"),
        ))

    workers = [Thread(target=request, daemon=True) for _ in range(2)]
    for worker in workers:
        worker.start()
    try:
        gate.wait(timeout=3.0)
    finally:
        for worker in workers:
            worker.join(timeout=3.0)
    assert all(not worker.is_alive() for worker in workers)
    assert sorted(results) == [False, True]
    assert launches == ["worker"]
    assert started.is_set()
    assert not _request_close_once(started, guard, lambda: launches.append("second"))
    assert launches == ["worker"]


def test_failed_ft8_release_reports_error_and_radio_owner_still_attempted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FT8 failure is reported; existing radio owner still tries de-key/close."""
    config = ApplicationConfig.model_validate(
        {"operator": {"callsign": "KI5VNB", "home_grid": "EM79xm"},
         "hardware": {"mock": True}}
    )
    runtime = ApplicationRuntime.from_config(config)
    runtime.start()
    reached_radio = Event()

    class FailingFt8:
        def close(self) -> None:
            raise RuntimeError("simulated uncertain TX0")

    runtime.ft8_hardware_transmit = FailingFt8()  # type: ignore[assignment]
    radio_disconnect = runtime.radio.disconnect

    def observed_disconnect() -> object:
        reached_radio.set()
        return radio_disconnect()

    monkeypatch.setattr(runtime.radio, "disconnect", observed_disconnect)
    with pytest.raises(ExceptionGroup, match="Rolling Thunder shutdown errors") as caught:
        runtime.stop()

    assert reached_radio.is_set()
    assert any("FT8 transmit: simulated uncertain TX0" in str(e)
               for e in caught.value.exceptions)
