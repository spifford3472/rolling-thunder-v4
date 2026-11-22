"""Exercise reporting failures and acknowledgments without contacting WSPRnet."""

from dataclasses import replace
from datetime import UTC, datetime
from subprocess import PIPE, TimeoutExpired
from threading import Event
from urllib.parse import parse_qs

import pytest

from rolling_thunder import wspr_reporting
from rolling_thunder.wspr_reporting import WsprnetReporter, WsprSpot, WsprUploadStatus

SPOT = WsprSpot(
    receiver_callsign="N0CALL",
    receiver_grid="EM79",
    slot_utc=datetime(2026, 11, 22, 23, 58, tzinfo=UTC),
    dial_hz=14_095_600,
    callsign="K1ABC/P",
    grid="FN31",
    frequency_hz=14_097_138,
    snr_db=-20,
    dt_s=0.2,
    drift_hz=-1,
    power_dbm=30,
)


class FakeCurl:
    def __init__(self, output=b"", returncode=0) -> None:
        self.output = output
        self.returncode = returncode
        self.inputs = []
        self.killed = False
        self.cancel_on_input = None
        self.timeout_once = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def communicate(self, payload, *, timeout):
        assert 0 < timeout < 1
        self.inputs.append(payload)
        if self.cancel_on_input is not None:
            self.cancel_on_input.set()
            raise TimeoutExpired("curl", timeout)
        if self.timeout_once:
            self.timeout_once = False
            raise TimeoutExpired("curl", timeout)
        return self.output, None

    def kill(self) -> None:
        self.killed = True


def test_public_form_and_private_pipe(monkeypatch, caplog):
    child = FakeCurl(b"<html>1 out of 1 spot(s) added</html>\n200")

    def launch(command, **kwargs):
        assert command[0:2] == ("curl", "--disable")
        assert command[-1] == "https://wsprnet.org/post/"
        assert "--location" not in command and "--retry" not in command
        assert "--noproxy" in command and "*" in command
        assert "--http1.1" in command
        assert "--max-filesize" in command and "--max-time" in command
        assert SPOT.receiver_callsign not in repr(command)
        assert SPOT.callsign not in repr(command)
        assert kwargs["stdin"] == kwargs["stdout"] == PIPE
        assert "SSLKEYLOGFILE" not in kwargs["env"]
        return child

    monkeypatch.setenv("SSLKEYLOGFILE", "unused")
    monkeypatch.setattr(wspr_reporting.subprocess, "Popen", launch)
    assert WsprnetReporter().report(SPOT, cancel=Event()) is WsprUploadStatus.ACCEPTED
    assert parse_qs(child.inputs[0].decode()) == {
        "function": ["wspr"],
        "date": ["261122"],
        "time": ["2358"],
        "sig": ["-20"],
        "dt": ["0.2"],
        "drift": ["-1"],
        "tqrg": ["14.097138"],
        "tcall": ["K1ABC/P"],
        "tgrid": ["FN31"],
        "dbm": ["30"],
        "version": ["Rolling Thunder v4"],
        "rcall": ["N0CALL"],
        "rgrid": ["EM79"],
        "rqrg": ["14.097100"],
        "mode": ["2"],
    }
    assert not caplog.records


@pytest.mark.parametrize(
    ("output", "returncode", "expected"),
    [
        (b"Nothing to do.\n200", 0, WsprUploadStatus.REJECTED),
        (b"0 out of 1 spot(s) added\n200", 0, WsprUploadStatus.REJECTED),
        (b"1 spot(s) added\n302", 0, WsprUploadStatus.REJECTED),
        (b"1 spot(s) added" + b"!" * 2048 + b"\n200", 0, WsprUploadStatus.IN_FLIGHT_UNKNOWN),
        (b"\n000", 6, WsprUploadStatus.UNAVAILABLE),
        (b"\n000", 28, WsprUploadStatus.IN_FLIGHT_UNKNOWN),
    ],
)
def test_only_acknowledged_results_are_accepted(monkeypatch, output, returncode, expected):
    child = FakeCurl(output, returncode)
    monkeypatch.setattr(wspr_reporting.subprocess, "Popen", lambda *_args, **_kw: child)
    assert WsprnetReporter().report(SPOT, cancel=Event()) is expected
    assert len(child.inputs) == 1


def test_unresolved_calls_and_excess_receiver_precision_are_never_sent(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("invalid spots must never start a network request")

    monkeypatch.setattr(wspr_reporting.subprocess, "Popen", forbidden)
    reporter = WsprnetReporter()
    for invalid_spot in (
        replace(SPOT, receiver_grid="EM79xm"),
        replace(SPOT, callsign="<...>"),
        replace(SPOT, frequency_hz=10_140_295),
        replace(SPOT, slot_utc=SPOT.slot_utc.replace(minute=57)),
    ):
        assert reporter.report(invalid_spot, cancel=Event()) is WsprUploadStatus.REJECTED


def test_a_spot_without_a_grid_can_be_acknowledged(monkeypatch):
    child = FakeCurl(b"1 spot(s) added\n200")
    monkeypatch.setattr(wspr_reporting.subprocess, "Popen", lambda *_args, **_kwargs: child)
    status = WsprnetReporter().report(replace(SPOT, grid=None), cancel=Event())
    assert status is WsprUploadStatus.ACCEPTED
    assert parse_qs(child.inputs[0].decode(), keep_blank_values=True)["tgrid"] == [""]


def test_cancel_before_payload_and_during_request_have_distinct_outcomes(monkeypatch):
    cancel = Event()
    child = FakeCurl()

    def launch(*_args, **_kwargs):
        cancel.set()
        return child

    monkeypatch.setattr(wspr_reporting.subprocess, "Popen", launch)
    assert WsprnetReporter().report(SPOT, cancel=cancel) is WsprUploadStatus.CANCELLED
    assert child.killed and child.inputs == []

    cancel.clear()
    in_flight = FakeCurl()
    in_flight.cancel_on_input = cancel
    monkeypatch.setattr(wspr_reporting.subprocess, "Popen", lambda *_a, **_k: in_flight)
    assert WsprnetReporter().report(SPOT, cancel=cancel) is WsprUploadStatus.IN_FLIGHT_UNKNOWN
    assert in_flight.killed and len(in_flight.inputs) == 1


def test_communication_poll_never_resubmits_the_body(monkeypatch):
    child = FakeCurl(b"1 spot(s) added\n200")
    child.timeout_once = True
    monkeypatch.setattr(wspr_reporting.subprocess, "Popen", lambda *_args, **_kwargs: child)
    assert WsprnetReporter().report(SPOT, cancel=Event()) is WsprUploadStatus.ACCEPTED
    assert child.inputs == [wspr_reporting._encode_spot(SPOT), None]


def test_reconnection_sends_only_the_new_report(monkeypatch):
    offline = FakeCurl(b"\n000", returncode=7)
    online = FakeCurl(b"1 spot(s) added\n200")
    children = iter((offline, online))
    monkeypatch.setattr(wspr_reporting.subprocess, "Popen", lambda *_args, **_kwargs: next(children))
    monkeypatch.setattr(wspr_reporting, "_REPORT_INTERVAL_S", 0.0)

    reporter = WsprnetReporter()
    assert reporter.report(SPOT, cancel=Event()) is WsprUploadStatus.UNAVAILABLE
    fresh = replace(SPOT, slot_utc=datetime(2026, 11, 23, tzinfo=UTC), callsign="K2DEF")
    assert reporter.report(fresh, cancel=Event()) is WsprUploadStatus.ACCEPTED
    assert offline.inputs == [wspr_reporting._encode_spot(SPOT)]
    assert online.inputs == [wspr_reporting._encode_spot(fresh)]
