"""STAB-02 hardware-free characterizations of shutdown failure boundaries.

These tests deliberately do not operate serial devices, radios, or systemd.
The partial-startup case is an explicit strict xfail until its safety contract
has been resolved in a separately reviewed implementation change.
"""

from datetime import UTC, datetime
from threading import Event, Thread

import pytest

from rolling_thunder.application_runtime import ApplicationRuntime
from rolling_thunder.config import ApplicationConfig
from rolling_thunder.domain import RadioConnectionState
from rolling_thunder.ft891_radio import Ft891Radio
from rolling_thunder.ui_main import _run_cleanup_steps


class BlockingReleaseTransport:
    """Fake CAT connection that stalls only the command that releases PTT."""

    def __init__(self) -> None:
        self.opened = False
        self.release_entered = Event()
        self.allow_release = Event()
        self.commands: list[bytes] = []

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
        except Exception as error:  # pragma: no cover - reported by assertion
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


@pytest.mark.xfail(
    strict=True,
    reason=(
        "STAB-03: runtime.stop() skips radio disconnect when _started is false, "
        "even if the radio was independently connected during partial startup"
    ),
)
def test_partial_startup_cleanup_disconnects_connected_radio() -> None:
    """Desired fail-safe contract for a pre-start hardware connection."""
    config = ApplicationConfig.model_validate(
        {"operator": {"callsign": "KI5VNB", "home_grid": "EM79xm"},
         "hardware": {"mock": True}}
    )
    runtime = ApplicationRuntime.from_config(config)
    runtime.radio.connect()
    assert runtime.radio.get_state().connection_state is RadioConnectionState.CONNECTED

    # Characterizes the currently missing cleanup, without calling start().
    runtime.stop()
    assert runtime.radio.get_state().connection_state is RadioConnectionState.DISCONNECTED
