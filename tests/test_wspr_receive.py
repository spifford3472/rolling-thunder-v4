"""Exercise WSPR through the physical dispatcher and a controlled receive lifecycle."""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from threading import Event
from time import monotonic, sleep

import pytest

from rolling_thunder.context_navigation import ContextId, ContextNavigationController
from rolling_thunder.control_dispatcher import ControlDispatcher
from rolling_thunder.domain import GPSFixState, GPSPosition
from rolling_thunder.ft8.diagnostics import NTPClockStatus
from rolling_thunder.gps import GPSConnectionState, GPSState, GPSUTCObservation, GPSUTCSource
from rolling_thunder.physical_controls import (
    ControlAction,
    ControlActionMapper,
    ControlEventGate,
    ControlInputEvent,
    MockControlSource,
)
from rolling_thunder.wspr_controls import WsprControlInterceptor
from rolling_thunder.wspr_decoder import WSPR_PCM_BYTES, WsprDecode
from rolling_thunder.wspr_receive import WSPR_BANDS, WsprReceive, next_wspr_slot
from rolling_thunder.wspr_reporting import WsprSpot, WsprUploadStatus


class FakeClock:
    def __init__(self) -> None:
        self.wall = datetime(2026, 11, 22, 14, 0, 0, tzinfo=UTC)
        self.elapsed = 1.0

    def advance(self, seconds: float) -> None:
        self.wall += timedelta(seconds=seconds)
        self.elapsed += seconds

    def gps(
        self, *, speed: float = 0.0, clock_offset: float = 0.0, latitude: float = 39.5,
    ) -> GPSState:
        return GPSState(
            GPSConnectionState.CONNECTED,
            GPSPosition(
                fix_state=GPSFixState.THREE_DIMENSIONAL,
                latitude=latitude, longitude=-84.1, speed_m_s=speed, updated_at=self.wall,
            ),
            self.wall,
            utc=GPSUTCObservation(
                value=self.wall + timedelta(seconds=clock_offset),
                source=GPSUTCSource.RMC,
                valid=True, fix_valid=True, advancing=True, fresh=True,
                age_s=0, received_monotonic_s=self.elapsed,
            ),
        )


class FakeReceiver:
    def __init__(self) -> None:
        self.acquired = Event()
        self.released = Event()
        self.dials: list[int] = []

    @contextmanager
    def reserve(self) -> Iterator["FakeReceiver"]:
        self.acquired.set()
        try:
            yield self
        finally:
            self.released.set()

    def tune(self, dial_hz: int) -> None:
        self.dials.append(dial_hz)

    def verify(self, dial_hz: int) -> None:
        assert self.dials[-1] == dial_hz


class NeverCapture:
    def capture(self, *args: object) -> bytes:
        raise AssertionError("This test never advances to an audio slot")


class Decoder:
    available = True

    def decode(self, pcm_s16le: bytes, dial_frequency_hz: int, cancel: Event) -> tuple[WsprDecode, ...]:
        assert len(pcm_s16le) == WSPR_PCM_BYTES
        return (
            WsprDecode("K1JT", "FN20", dial_frequency_hz + 1500, -12, 0.0, 0, 30),
            WsprDecode("W1AW", "FN31", dial_frequency_hz + 1510, -12, 0.0, 0, 30),
        )


class Reporter:
    def __init__(self) -> None:
        self.status = WsprUploadStatus.ACCEPTED
        self.calls: list[WsprSpot] = []

    def report(self, spot: WsprSpot, *, cancel: Event) -> WsprUploadStatus:
        assert not cancel.is_set()
        self.calls.append(spot)
        return self.status


class NoCommands:
    def execute(self, action: ControlAction) -> bool:
        return False


def _wait_for(predicate) -> None:
    end = monotonic() + 2
    while not predicate() and monotonic() < end:
        sleep(0.005)
    assert predicate()


def _controller(clock, radio, audio, reporter, *, ntp_status=None) -> WsprReceive:
    return WsprReceive(
        callsign="KI5VNB", lease=radio.reserve, audio=audio, decoder=Decoder(),
        reporter=reporter, ntp_status=ntp_status, now_utc=lambda: clock.wall, elapsed_clock=lambda: clock.elapsed,
    )


def _stationary(receive: WsprReceive, clock: FakeClock) -> None:
    for _ in range(6):
        receive.observe_gps(clock.gps())
        clock.advance(1)


def test_only_selected_physical_button_starts_and_every_exit_revokes() -> None:
    clock = FakeClock()
    radio = FakeReceiver()
    receive = _controller(clock, radio, NeverCapture(), Reporter())
    navigation = ContextNavigationController(
        on_selected=lambda context: receive.select(context is ContextId.WSPR),
    )
    source = MockControlSource()
    dispatcher = ControlDispatcher(
        source, ControlActionMapper({
            "run": ControlAction.PANEL_TERTIARY,
            "stop": ControlAction.PANEL_SECONDARY,
        }),
        ControlEventGate(0), NoCommands(), event_interceptor=WsprControlInterceptor(
            receive, selected=lambda: navigation.state.selected is ContextId.WSPR,
            radio_idle=lambda: True, allowed=lambda: True,
        ),
    )
    _stationary(receive, clock)

    source.emit(ControlInputEvent("run", "outside", 1))
    assert dispatcher.dispatch_available().accepted == 0
    assert navigation.select_shortcut("w")
    assert not receive.busy
    assert receive.snapshot().grid == "EM79"

    def press(input_id: str, event_id: str) -> int:
        source.emit(ControlInputEvent(input_id, event_id, 1))
        return dispatcher.dispatch_available().accepted

    for i, leave_screen in enumerate((
        navigation.select_home,
        navigation.select_next,
        lambda: navigation.select_shortcut("b"),
        lambda: navigation.select(ContextId.FT8),
    )):
        radio.acquired.clear()
        radio.released.clear()
        assert press("run", f"run-{i}") == 1
        assert radio.acquired.wait(1)
        leave_screen()
        assert radio.released.wait(1)
        _wait_for(lambda: not receive.busy)
        navigation.select(ContextId.WSPR)
        assert not receive.busy
    assert press("run", "fresh") == 1
    assert press("run", "repeat") == 0
    assert press("stop", "operator-stop") == 1
    _wait_for(lambda: not receive.busy)
    assert "Operator stopped" in receive.snapshot().detail
    receive.close()
    assert press("run", "after-shutdown") == 0


def test_parked_wspr_ignores_speed_and_position_spikes_then_stops_on_sustained_move() -> None:
    clock = FakeClock()
    radio = FakeReceiver()
    receive = _controller(clock, radio, NeverCapture(), Reporter())
    receive.select(True)
    _stationary(receive, clock)
    assert receive.start()
    assert radio.acquired.wait(1)
    try:
        receive.observe_gps(clock.gps(speed=1.0, latitude=39.501))
        assert receive.snapshot().active
        clock.advance(1)
        receive.observe_gps(clock.gps(speed=1.0, latitude=39.5001))
        assert receive.snapshot().active
        # Roughly 73 feet away, starting a new confirmation window.
        for _ in range(5):
            clock.advance(1)
            fix = clock.gps(latitude=39.5002)
            receive.observe_gps(fix)
            receive.observe_gps(fix)
            assert receive.snapshot().active
        clock.advance(1)
        receive.observe_gps(clock.gps(latitude=39.5002))
        _wait_for(lambda: not receive.busy)
        assert receive.snapshot().detail == "Stopped: Vehicle moved at least 50 ft for five seconds"
        assert radio.released.is_set()
    finally:
        receive.close()


@pytest.mark.parametrize("failure", ["stale", "clock"])
def test_motion_and_timing_fail_closed_without_restart(failure: str) -> None:
    clock = FakeClock()
    radio = FakeReceiver()
    receive = _controller(clock, radio, NeverCapture(), Reporter())
    receive.select(True)
    assert not receive.start()
    _stationary(receive, clock)
    assert receive.start()
    assert radio.acquired.wait(1)
    if failure == "stale":
        clock.advance(5)
    else:
        receive.observe_gps(clock.gps(clock_offset=3.0))
    _wait_for(lambda: not receive.busy)
    detail = receive.snapshot().detail
    assert any(word in detail for word in ("motion", "Motion", "UTC"))
    _stationary(receive, clock)
    assert not receive.busy
    assert receive.start()
    receive.close()


@pytest.mark.parametrize(("chrony_offset", "gps_offset", "reason"), [
    (0.002, -1.35, None),
    (None, -1.35, "System UTC disagrees with GPS"),
    (None, -0.6, None),
    (0.002, -2.5, "System UTC disagrees with GPS"),
    (0.5, -0.1, "NTP clock offset exceeds WSPR limit"),
])
def test_chrony_independently_verifies_clock_with_delayed_serial_gps(
    chrony_offset, gps_offset, reason,
) -> None:
    clock = FakeClock()
    radio = FakeReceiver()
    receive = _controller(
        clock, radio, NeverCapture(), Reporter(),
        ntp_status=lambda: NTPClockStatus(chrony_offset is not None, offset_seconds=chrony_offset),
    )
    receive.select(True)
    _stationary(receive, clock)
    receive.observe_gps(clock.gps(clock_offset=gps_offset))
    try:
        assert receive.start()
        if reason is None:
            assert radio.acquired.wait(1)
            assert receive.busy
            # Even healthy chrony cannot carry a session through a wall-clock step.
            clock.wall += timedelta(seconds=0.5)
            receive.observe_gps(clock.gps(clock_offset=gps_offset))
            _wait_for(lambda: not receive.busy)
            assert "System UTC shifted during WSPR" in receive.snapshot().detail
        else:
            _wait_for(lambda: not receive.busy)
            assert not radio.acquired.is_set()
            assert reason in receive.snapshot().detail
    finally:
        receive.close()


def test_rotation_with_online_and_offline_windows_and_midnight(monkeypatch, caplog) -> None:
    caplog.set_level(logging.INFO, logger="rolling_thunder.wspr_receive")
    monkeypatch.setenv("TZ", "UTC")
    import time
    time.tzset()
    try:
        _rotation_test(monkeypatch)
        messages = "\n".join(
            record.getMessage() for record in caplog.records
            if record.name == "rolling_thunder.wspr_receive"
        )
        assert "session_start" in messages
        assert "slot_start band=40 m" in messages
        assert "capture_complete band=40 m" in messages
        assert "decode_complete band=40 m" in messages
        assert "decode_count=2" in messages
        assert "report_summary band=40 m" in messages and "accepted=2" in messages
        assert "report_summary band=30 m" in messages and "unavailable=2" in messages
        assert "session_end" in messages
        station_data = ("K1JT", "W1AW", "EM79", "FN20", "FN31")
        assert not any(station in messages for station in station_data)
    finally:
        monkeypatch.undo()
        time.tzset()


def _rotation_test(monkeypatch) -> None:
    clock = FakeClock()
    clock.wall = clock.wall.replace(hour=23, minute=54, second=42)
    radio = FakeReceiver()
    reporter = Reporter()
    captured = []
    observed = []
    finished: list[datetime] = []
    original_decode = WsprReceive._decode

    class SimulatedAudio:
        def capture(self, start_utc, byte_count, now_utc, check):
            if captured:
                _wait_for(lambda: len(finished) == len(captured))
                observed.append(receive.snapshot())
            if len(captured) == 9:
                receive.stop()
                check()
            if len(captured) == 1:
                reporter.status = WsprUploadStatus.UNAVAILABLE
            elif len(captured) == 2:
                reporter.status = WsprUploadStatus.ACCEPTED
            assert byte_count == WSPR_PCM_BYTES
            captured.append(start_utc)
            clock.advance((start_utc - clock.wall).total_seconds() + 114)
            receive.observe_gps(clock.gps())
            check()
            return bytes(byte_count)

    def wait_until(self, deadline, cancel):
        self._check(cancel)
        clock.advance(max(0.0, (deadline - clock.wall).total_seconds()))
        self.observe_gps(clock.gps())

    def decode(self, pcm, index, slot, origin, cancel):
        original_decode(self, pcm, index, slot, origin, cancel)
        finished.append(slot)

    monkeypatch.setattr(WsprReceive, "_wait_until", wait_until)
    monkeypatch.setattr(WsprReceive, "_decode", decode)
    receive = _controller(clock, radio, SimulatedAudio(), reporter)
    _stationary(receive, clock)
    receive.select(True)
    assert receive.start()
    _wait_for(lambda: not receive.busy)
    assert radio.dials[:9] == [hz for _, hz in WSPR_BANDS] + [WSPR_BANDS[0][1]]
    assert all(
        following - previous == timedelta(minutes=2)
        for previous, following in pairwise(captured)
    )
    assert next_wspr_slot(datetime(2026, 11, 22, 14, 0, 58, tzinfo=UTC)).minute == 2
    assert observed[0].closest is not None
    assert observed[0].closest.callsign == "K1JT"
    assert observed[0].farthest is not None
    assert observed[0].farthest.callsign == "W1AW"
    assert observed[0].decodes_per_hour == pytest.approx(2 * 3600 / 114)
    assert observed[1].upload == "Unavailable"
    assert observed[1].band_totals[1] == ("30 m", 2)
    assert observed[1].closest == observed[0].closest
    final = receive.snapshot()
    assert final.band_totals[1] == ("30 m", 0)
    assert final.elapsed_s > 18 * 60
    assert all(spot.receiver_grid == "EM79" for spot in reporter.calls)
    assert sum(spot.dial_hz == WSPR_BANDS[1][1] for spot in reporter.calls) == 1
