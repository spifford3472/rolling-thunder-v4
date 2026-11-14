"""Regression tests for structured CAT PTT release timing diagnostics."""

import logging
from datetime import UTC, datetime

import pytest

from rolling_thunder.ft891_radio import Ft891Radio
from rolling_thunder.radio import RadioConnectionError


class Transport:
    """Hardware-free CAT transport with deterministic replies and failures."""

    def __init__(self) -> None:
        self.is_open = False
        self.fail_release = False
        self.commands: list[bytes] = []

    def open(self) -> None:
        self.is_open = True

    def close(self) -> None:
        self.is_open = False

    def query(self, command: bytes) -> bytes:
        return {
            b"FA;": b"FA014250000;", b"MD0;": b"MD02;",
        }[command]

    def command(self, command: bytes) -> None:
        self.commands.append(command)
        if command == b"TX0;" and self.fail_release:
            raise RadioConnectionError("simulated CAT release failure")


def test_ptt_release_reports_separate_lock_and_cat_timings(caplog: pytest.LogCaptureFixture) -> None:
    transport = Transport()
    radio = Ft891Radio(transport, clock=lambda: datetime(2026, 11, 13, tzinfo=UTC))
    radio.connect()
    ptt = radio.create_cp6_cat_ptt_capability()
    ptt.key()

    with caplog.at_level(logging.INFO, logger="rolling_thunder.ft891_radio"):
        ptt.close()

    assert transport.commands[-1] == b"TX0;"
    assert "RT_PTT_RELEASE phase=end lock_wait_ms=" in caplog.text
    assert " cat_ms=" in caplog.text
    assert " result=ok" in caplog.text


def test_ptt_release_failure_remains_retryable_and_logged(caplog: pytest.LogCaptureFixture) -> None:
    transport = Transport()
    radio = Ft891Radio(transport)
    radio.connect()
    ptt = radio.create_cp6_cat_ptt_capability()
    ptt.key()
    transport.fail_release = True

    with caplog.at_level(logging.INFO, logger="rolling_thunder.ft891_radio"):
        with pytest.raises(RadioConnectionError, match="simulated CAT release failure"):
            ptt.close()
        assert " result=error" in caplog.text
        transport.fail_release = False
        ptt.close()

    assert transport.commands[-2:] == [b"TX0;", b"TX0;"]
    assert " result=ok" in caplog.text
