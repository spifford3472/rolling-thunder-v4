"""STAB-02 hardware-free characterizations of shutdown failure boundaries.

These tests deliberately do not operate serial devices, radios, or systemd.
The partial-startup case is now an ordinary regression asserting the corrected
safety contract; no radio or systemd hardware is used.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from threading import Event, Thread

import pytest

from rolling_thunder.application_runtime import ApplicationRuntime
from rolling_thunder.config import ApplicationConfig
from rolling_thunder.domain import RadioConnectionState, RadioState
from rolling_thunder.ft891_radio import Ft891Radio
from rolling_thunder.gps import GPSState
from rolling_thunder.gps_polling import GPSPollingService
from rolling_thunder.mock_gps import MockGPSReceiver
from rolling_thunder.radio import RadioConnectionError
from rolling_thunder.ui_main import _run_cleanup_steps


class BlockingReleaseTransport:
    """Fake CAT connection that stalls only the command that releases PTT."""

    def __init__(self) -> None:
        self.opened = False
        self.release_entered = Event()
        self.allow_release = Event()
        self.commands: list[bytes] = []
        self.fail_release = False

    def open(self) -> None:
        self.opened = True

    def close(self) -> None:
        self.opened = False

    def query(self, command: bytes) -> bytes:
        return {b"FA;": b"FA014250000;", b"MD0;": b"MD02;"}[command]

    def command(self, command: bytes) -> None:
        self.commands.append(command)
        if command == b"TX0;":
            self.release_entered.set()
            # The test always releases the fake to avoid leaking a test thread.
            assert self.allow_release.wait(timeout=3.0)
            if self.fail_release:
                raise RadioConnectionError("simulated unavailable CAT TX0")


def test_blocked_cat_tx0_cannot_be_reported_as_success(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An in-flight release is not a completed PTT release."""
    transport = BlockingReleaseTransport()
    radio = Ft891Radio(transport, clock=lambda: datetime(2026, 11, 13, tzinfo=UTC))
    radio.connect()
    ptt = radio.create_cp6_cat_ptt_capability()
    ptt.key()
    finished = Event()
    errors: list[Exception] = []

    def release_ptt() -> None:
        try:
            ptt.close()
        except RadioConnectionError as error:  # pragma: no cover - reported by assertion
            errors.append(error)
        finally:
            finished.set()

    worker = Thread(target=release_ptt, daemon=True)
    with caplog.at_level("INFO", logger="rolling_thunder.ft891_radio"):
        worker.start()
        try:
            assert transport.release_entered.wait(timeout=1.0)
            assert not finished.wait(timeout=0.05)
            assert "result=ok" not in caplog.text
        finally:
            transport.allow_release.set()
            worker.join(timeout=3.0)

    assert not worker.is_alive()
    assert finished.is_set()
    assert errors == []
    assert transport.commands == [b"TX1;", b"TX0;"]
    assert "result=ok" in caplog.text


def test_blocked_ui_cleanup_prevents_later_radio_step_until_released() -> None:
    """Characterize the sequential UI shutdown dependency without hanging."""
    entered = Event()
    unblock = Event()
    radio_reached = Event()
    finished = Event()
    errors: list[str] = []

    def blocked() -> None:
        entered.set()
        assert unblock.wait(timeout=3.0)

    def run_close() -> None:
        try:
            _run_cleanup_steps(
                (("unrelated worker", blocked), ("radio", radio_reached.set)),
                errors,
            )
        finally:
            finished.set()

    worker = Thread(target=run_close, daemon=True)
    worker.start()
    try:
        assert entered.wait(timeout=1.0)
        assert not radio_reached.is_set()
        assert not finished.wait(timeout=0.05)
    finally:
        unblock.set()
        worker.join(timeout=3.0)

    assert not worker.is_alive()
    assert finished.is_set()
    assert radio_reached.is_set()
    assert errors == []


def test_partial_startup_cleanup_disconnects_connected_radio() -> None:
    """Desired fail-safe contract for a pre-start hardware connection."""
    config = ApplicationConfig.model_validate(
        {"operator": {"callsign": "KI5VNB", "home_grid": "EM79xm"},
         "hardware": {"mock": True}}
    )
    runtime = ApplicationRuntime.from_config(config)
    runtime.radio.connect()
    assert runtime.radio.get_state().connection_state is RadioConnectionState.CONNECTED

    # Regression: an already-connected radio must be released even before start().
    runtime.stop()
    assert runtime.radio.get_state().connection_state is RadioConnectionState.DISCONNECTED



def test_failed_cat_tx0_during_disconnect_keeps_ptt_uncertain(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A failed radio disconnect must not claim the radio was safely released."""
    transport = BlockingReleaseTransport()
    transport.allow_release.set()
    radio = Ft891Radio(transport)
    radio.connect()
    ptt = radio.create_cp6_cat_ptt_capability()
    ptt.key()
    transport.fail_release = True

    with caplog.at_level("INFO", logger="rolling_thunder.ft891_radio"):
        with pytest.raises(RadioConnectionError, match="unavailable CAT TX0"):
            radio.disconnect()
        assert "result=error" in caplog.text
        assert "result=ok" not in caplog.text

        # A failed release keeps the transport open and permits an explicit retry.
        assert transport.opened
        transport.fail_release = False
        radio.disconnect()

    assert transport.commands == [b"TX1;", b"TX0;", b"TX0;"]
    assert not transport.opened
    assert "result=ok" in caplog.text


def test_held_cat_operation_lock_defers_release_without_parallel_cat_commands() -> None:
    """Characterize a lock holder that has not yielded: no competing TX0 path."""
    transport = BlockingReleaseTransport()
    transport.allow_release.set()
    radio = Ft891Radio(transport)
    radio.connect()
    ptt = radio.create_cp6_cat_ptt_capability()
    ptt.key()

    lock_held = Event()
    release_lock = Event()
    release_done = Event()
    ptt_errors: list[RadioConnectionError] = []

    def hold_unrelated_cat_lock() -> None:
        # Test-only simulated stuck operation; no real CAT or timer dependency.
        with radio._operation_lock:
            lock_held.set()
            assert release_lock.wait(timeout=3.0)

    def close_ptt() -> None:
        try:
            ptt.close()
        except RadioConnectionError as error:
            ptt_errors.append(error)
        finally:
            release_done.set()

    holder = Thread(target=hold_unrelated_cat_lock, daemon=True)
    closer = Thread(target=close_ptt, daemon=True)
    holder.start()
    try:
        assert lock_held.wait(timeout=1.0)
        closer.start()
        assert not release_done.wait(timeout=0.05)
        assert transport.commands == [b"TX1;"]
    finally:
        release_lock.set()
        holder.join(timeout=3.0)
        if closer.ident is not None:
            closer.join(timeout=3.0)

    assert not holder.is_alive()
    assert not closer.is_alive()
    assert release_done.is_set()
    assert ptt_errors == []
    assert transport.commands == [b"TX1;", b"TX0;"]


def test_startup_failure_after_radio_polling_rolls_back_hardware(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed service startup after radio connect must invoke normal cleanup."""
    config = ApplicationConfig.model_validate(
        {"operator": {"callsign": "KI5VNB", "home_grid": "EM79xm"},
         "hardware": {"mock": True}}
    )
    runtime = ApplicationRuntime.from_config(config)

    def fail_remaining_services() -> None:
        raise RuntimeError("simulated partial service startup")

    monkeypatch.setattr(runtime, "_start_remaining_services", fail_remaining_services)
    with pytest.raises(RuntimeError, match="simulated partial service startup"):
        runtime.start()

    assert runtime.radio.get_state().connection_state is RadioConnectionState.DISCONNECTED
    assert not runtime._started



class ManualCancellation:
    """Minimal scheduled callback with an observable cancel boundary."""

    def __init__(self) -> None:
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


class ManualGPSPollScheduler:
    """Allow a GPS poll callback to run on a controlled test thread."""

    def __init__(self) -> None:
        self.callback: Callable[[], None] | None = None
        self.handle = ManualCancellation()

    def schedule_repeating(
        self, interval_s: float, callback: Callable[[], None]
    ) -> ManualCancellation:
        assert interval_s == 1.0
        self.callback = callback
        return self.handle


def test_gps_stop_cancels_future_polls_but_not_a_blocked_inflight_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Document cancellation's boundary without starting new GPS readers."""
    receiver = MockGPSReceiver()
    scheduler = ManualGPSPollScheduler()
    gps_polling = GPSPollingService(receiver, scheduler)
    gps_polling.start()
    entered = Event()
    unblock = Event()
    finished = Event()

    def blocked_refresh() -> GPSState:
        entered.set()
        assert unblock.wait(timeout=3.0)
        return receiver.get_state()

    monkeypatch.setattr(receiver, "refresh_state", blocked_refresh)
    assert scheduler.callback is not None

    def run_poll() -> None:
        try:
            assert scheduler.callback is not None
            scheduler.callback()
        finally:
            finished.set()

    worker = Thread(target=run_poll, daemon=True)
    worker.start()
    try:
        assert entered.wait(timeout=1.0)
        gps_polling.stop()
        assert scheduler.handle.cancelled
        assert not gps_polling.is_running
        assert not finished.is_set()
    finally:
        unblock.set()
        worker.join(timeout=3.0)

    assert not worker.is_alive()
    assert finished.is_set()


def test_runtime_unrelated_blocking_stop_cannot_delay_radio_disconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The radio owner closes before an unrelated runtime worker blocks."""
    config = ApplicationConfig.model_validate(
        {"operator": {"callsign": "KI5VNB", "home_grid": "EM79xm"},
         "hardware": {"mock": True}}
    )
    runtime = ApplicationRuntime.from_config(config)
    runtime.start()
    blocked_entered = Event()
    unblock = Event()
    radio_disconnect_entered = Event()
    shutdown_finished = Event()
    stop_errors: list[Exception] = []
    original_disconnect = runtime.radio.disconnect

    def stuck_enrichment_stop() -> None:
        blocked_entered.set()
        assert unblock.wait(timeout=3.0)

    def observe_disconnect() -> RadioState:
        radio_disconnect_entered.set()
        return original_disconnect()

    monkeypatch.setattr(runtime.pota_enrichment, "stop", stuck_enrichment_stop)
    monkeypatch.setattr(runtime.radio, "disconnect", observe_disconnect)

    def stop_runtime() -> None:
        try:
            runtime.stop()
        except Exception as error:  # noqa: BLE001 - record worker failures
            stop_errors.append(error)
        finally:
            shutdown_finished.set()

    worker = Thread(target=stop_runtime, daemon=True)
    worker.start()
    try:
        assert blocked_entered.wait(timeout=2.0)
        assert radio_disconnect_entered.wait(timeout=1.0)
        assert not shutdown_finished.wait(timeout=0.05)
    finally:
        unblock.set()
        worker.join(timeout=5.0)

    assert not worker.is_alive()
    assert shutdown_finished.is_set()
    assert radio_disconnect_entered.is_set()
    assert stop_errors == []



def test_repeated_runtime_shutdown_keeps_radio_disconnected() -> None:
    """Repeated sequential requests must not reconnect or re-key the radio."""
    config = ApplicationConfig.model_validate(
        {"operator": {"callsign": "KI5VNB", "home_grid": "EM79xm"},
         "hardware": {"mock": True}}
    )
    runtime = ApplicationRuntime.from_config(config)
    runtime.start()

    first = runtime.stop()
    second = runtime.stop()

    assert first.connection_state is RadioConnectionState.DISCONNECTED
    assert second.connection_state is RadioConnectionState.DISCONNECTED
    assert runtime.radio.get_state().connection_state is RadioConnectionState.DISCONNECTED



def test_prestart_radio_disconnect_error_is_reported_and_remains_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Do not silently return a connected state after failed pre-start cleanup."""
    config = ApplicationConfig.model_validate(
        {"operator": {"callsign": "KI5VNB", "home_grid": "EM79xm"},
         "hardware": {"mock": True}}
    )
    runtime = ApplicationRuntime.from_config(config)
    runtime.radio.connect()
    original_disconnect = runtime.radio.disconnect
    attempts = 0

    def fail_disconnection() -> RadioState:
        nonlocal attempts
        attempts += 1
        raise RadioConnectionError("simulated pre-start disconnect error")

    monkeypatch.setattr(runtime.radio, "disconnect", fail_disconnection)
    with pytest.raises(ExceptionGroup, match="Rolling Thunder shutdown errors") as caught:
        runtime.stop()

    assert attempts == 1
    assert any(
        "radio disconnect: simulated pre-start disconnect error" in str(error)
        for error in caught.value.exceptions
    )
    assert runtime.radio.get_state().connection_state is RadioConnectionState.CONNECTED

    monkeypatch.setattr(runtime.radio, "disconnect", original_disconnect)
    state = runtime.stop()
    assert state.connection_state is RadioConnectionState.DISCONNECTED


def test_prestart_stop_does_not_disconnect_radio_that_was_never_connected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Avoid unnecessary hardware access during shutdown before a real connect."""
    config = ApplicationConfig.model_validate(
        {"operator": {"callsign": "KI5VNB", "home_grid": "EM79xm"},
         "hardware": {"mock": True}}
    )
    runtime = ApplicationRuntime.from_config(config)

    def unexpected_disconnect() -> RadioState:
        raise AssertionError("unused radio must not be accessed")

    monkeypatch.setattr(runtime.radio, "disconnect", unexpected_disconnect)
    assert runtime.stop().connection_state is RadioConnectionState.DISCONNECTED
