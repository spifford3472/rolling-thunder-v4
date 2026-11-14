"""STAB-05 hardware-free CAT/PTT uncertainty and retry tests.

These tests never open physical CAT devices or transmit RF. They do not assert
physical de-keying from any software-only observation.
"""

from threading import Event, Thread

import pytest

from rolling_thunder.ft891_radio import Ft891Radio
from rolling_thunder.radio import RadioConnectionError


class UncertainCat:
    """Fake serial transport with failure injection at TX0."""

    def __init__(self) -> None:
        self.opened = False
        self.fail_tx0 = False
        self.commands: list[bytes] = []

    def open(self) -> None:
        self.opened = True

    def close(self) -> None:
        self.opened = False

    def query(self, command: bytes) -> bytes:
        return {b"FA;": b"FA014250000;", b"MD0;": b"MD02;"}[command]

    def command(self, command: bytes) -> None:
        self.commands.append(command)
        if command == b"TX0;" and self.fail_tx0:
            raise RadioConnectionError("injected CAT TX0 uncertainty")


def test_failed_close_keeps_ptt_release_retryable_without_rekeying(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Failed TX0 does not produce a false close or a duplicate TX1."""
    serial = UncertainCat()
    radio = Ft891Radio(serial)
    radio.connect()
    ptt = radio.create_cp6_cat_ptt_capability()
    ptt.key()
    serial.fail_tx0 = True

    with caplog.at_level("INFO", logger="rolling_thunder.ft891_radio"):
        with pytest.raises(RadioConnectionError, match="TX0 uncertainty"):
            ptt.close()
        assert "result=error" in caplog.text
        assert "result=ok" not in caplog.text

        # Unverified TX0 must reject every new key, never silently succeed.
        with pytest.raises(RadioConnectionError, match="release is unverified"):
            ptt.key()
        assert serial.commands == [b"TX1;", b"TX0;"]

        serial.fail_tx0 = False
        ptt.close()
        assert "result=ok" in caplog.text

    assert serial.commands == [b"TX1;", b"TX0;", b"TX0;"]
    assert serial.opened
    with pytest.raises(RadioConnectionError, match="closed"):
        ptt.key()
    radio.disconnect()
    assert not serial.opened


def test_stuck_cat_lock_never_logs_ptt_success_before_release(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A lock stall cannot be disguised as a completed transmit-off."""
    serial = UncertainCat()
    radio = Ft891Radio(serial)
    radio.connect()
    ptt = radio.create_cp6_cat_ptt_capability()
    ptt.key()
    entered = Event()
    unlock = Event()
    finished = Event()
    release_errors: list[Exception] = []

    def stalled_cat_owner() -> None:
        with radio._operation_lock:
            entered.set()
            assert unlock.wait(timeout=3.0)

    def release_ptt() -> None:
        try:
            ptt.close()
        except RadioConnectionError as error:
            release_errors.append(error)
        finally:
            finished.set()

    holder = Thread(target=stalled_cat_owner, daemon=True)
    closer = Thread(target=release_ptt, daemon=True)
    holder.start()
    try:
        assert entered.wait(timeout=1.0)
        with caplog.at_level("INFO", logger="rolling_thunder.ft891_radio"):
            closer.start()
            assert not finished.wait(timeout=0.05)
            assert serial.commands == [b"TX1;"]
            assert "result=ok" not in caplog.text
    finally:
        unlock.set()
        holder.join(timeout=3.0)
        if closer.ident is not None:
            closer.join(timeout=3.0)

    assert not holder.is_alive()
    assert not closer.is_alive()
    assert finished.is_set()
    assert release_errors == []
    assert serial.commands == [b"TX1;", b"TX0;"]



def test_uncertain_release_recovers_only_after_successful_existing_owner_tx0() -> None:
    """A failed TX0 prohibits another TX1 until an explicit retry succeeds."""
    serial = UncertainCat()
    radio = Ft891Radio(serial)
    radio.connect()
    ptt = radio.create_cp6_cat_ptt_capability()
    ptt.key()
    serial.fail_tx0 = True

    with pytest.raises(RadioConnectionError, match="TX0 uncertainty"):
        ptt.release()
    for _ in range(3):
        with pytest.raises(RadioConnectionError, match="release is unverified"):
            ptt.key()
    assert serial.commands == [b"TX1;", b"TX0;"]

    serial.fail_tx0 = False
    ptt.release()
    assert serial.commands == [b"TX1;", b"TX0;", b"TX0;"]
    # The original capability remains available for a separately authorized
    # operation after the CAT release retry, not because of a timeout.
    ptt.key()
    assert serial.commands[-1] == b"TX1;"
    ptt.close()
    radio.disconnect()


def test_failed_radio_disconnect_preserves_ptt_inhibit_and_retry() -> None:
    """A failed disconnect is neither a successful PTT release nor a close."""
    serial = UncertainCat()
    radio = Ft891Radio(serial)
    radio.connect()
    ptt = radio.create_cp6_cat_ptt_capability()
    ptt.key()
    serial.fail_tx0 = True

    with pytest.raises(RadioConnectionError, match="TX0 uncertainty"):
        radio.disconnect()
    assert serial.opened
    with pytest.raises(RadioConnectionError, match="release is unverified"):
        ptt.key()

    serial.fail_tx0 = False
    radio.disconnect()
    assert serial.commands == [b"TX1;", b"TX0;", b"TX0;"]
    assert not serial.opened


def test_uncertain_tx1_and_failed_compensating_tx0_inhibit_later_keys() -> None:
    """A partial TX1 write may have keyed; compensation failure stays unsafe."""
    class PartialKeyCat(UncertainCat):
        def command(self, command: bytes) -> None:
            self.commands.append(command)
            if command in (b"TX1;", b"TX0;") and self.fail_tx0:
                raise RadioConnectionError("uncertain CAT write")

    serial = PartialKeyCat()
    radio = Ft891Radio(serial)
    radio.connect()
    ptt = radio.create_cp6_cat_ptt_capability()
    serial.fail_tx0 = True

    with pytest.raises(RadioConnectionError, match="uncertain CAT write"):
        ptt.key()
    assert serial.commands == [b"TX1;", b"TX0;"]
    with pytest.raises(RadioConnectionError, match="release is unverified"):
        ptt.key()
    assert serial.commands == [b"TX1;", b"TX0;"]

    serial.fail_tx0 = False
    ptt.release()
    assert serial.commands[-1] == b"TX0;"
    ptt.close()
    radio.disconnect()
