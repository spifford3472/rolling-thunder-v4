"""STAB-04 offline shutdown-deadline evidence, not a safety acceptance pass.

The 20-second systemd stop deadline cannot force Python callbacks to complete.
Events let tests observe the blocked phase without sleeping for 20 seconds or
opening hardware. The runtime internal blocked-worker risk remains a separate acceptance gate.
"""

from threading import Event, Thread

import pytest

from rolling_thunder.application_runtime import ApplicationRuntime
from rolling_thunder.config import ApplicationConfig
from rolling_thunder.ui_main import _run_cleanup_steps, _run_orderly_shutdown


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
