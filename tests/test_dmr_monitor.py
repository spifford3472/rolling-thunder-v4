"""Tests for the background DMR hotspot monitor service."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from threading import Event, Lock

from rolling_thunder.dmr_activity import DmrActivitySource
from rolling_thunder.dmr_monitor import (
    DmrLiveLineSource,
    DmrMonitorHealth,
    DmrMonitorService,
    DmrSourceError,
    DmrWpsdSource,
)
from rolling_thunder.dmr_wpsd import (
    WpsdDmrHistoryIdentity,
    WpsdDmrHistoryRecord,
    WpsdRadioInfo,
)

_START_LINE = (
    "M: 2026-08-16 00:07:08.120 DMR Slot 1, "
    "received network voice header from KC9KPJ to TG 3100"
)
_ALIAS_LINE = (
    'M: 2026-08-16 00:07:10.807 DMR Slot 1, Talker Alias "KC9KPJ Michael"'
)
_END_LINE = (
    "M: 2026-08-16 00:07:22.084 DMR Slot 1, received network end of voice "
    "transmission from KC9KPJ to TG 3100, 14.2 seconds, 0% packet loss, BER: 0.0%"
)


def _history_record() -> WpsdDmrHistoryRecord:
    return WpsdDmrHistoryRecord(
        identity=WpsdDmrHistoryIdentity(
            occurred_at=datetime(2026, 8, 16, 0, 7, 22, tzinfo=UTC),
            callsign="KC9KPJ",
            slot=1,
            talkgroup=3100,
            source=DmrActivitySource.NETWORK,
        ),
        name="Michael",
        country="USA",
        callsign_suffix=None,
        target="TG 3100",
        duration_s=14.2,
        packet_loss_percent=0.0,
    )


class ControlledLiveSource(DmrLiveLineSource):
    def __init__(self) -> None:
        self.started = Event()
        self.closed = Event()
        self._lines: list[str] = []
        self._line_available = Event()
        self._lock = Lock()
        self.failure: DmrSourceError | None = None

    def push(self, line: str) -> None:
        with self._lock:
            self._lines.append(line)
        self._line_available.set()

    def fail(self, message: str) -> None:
        self.failure = DmrSourceError(message)
        self._line_available.set()

    def stream(self, stop_event: Event) -> Iterator[str]:
        self.started.set()
        yield "RTDMR READY"
        while not stop_event.is_set():
            self._line_available.wait(timeout=0.05)
            if stop_event.is_set():
                return
            failure = self.failure
            if failure is not None:
                self.failure = None
                raise failure
            with self._lock:
                lines = tuple(self._lines)
                self._lines.clear()
                self._line_available.clear()
            yield from lines

    def close(self) -> None:
        self.closed.set()
        self._line_available.set()


class FakeWpsdSource(DmrWpsdSource):
    def __init__(self) -> None:
        self.history_calls = 0
        self.radio_calls = 0
        self.fail_history = False
        self.fail_radio = False

    def fetch_history(self) -> tuple[WpsdDmrHistoryRecord, ...]:
        self.history_calls += 1
        if self.fail_history:
            raise DmrSourceError("history offline")
        return (_history_record(),)

    def fetch_radio_info(self) -> WpsdRadioInfo:
        self.radio_calls += 1
        if self.fail_radio:
            raise DmrSourceError("radio info offline")
        return WpsdRadioInfo(
            status="IDLE",
            mode="Duplex",
            hotspot_tx_hz=434_537_500,
            hotspot_rx_hz=439_537_500,
        )


def _wait_until(predicate: Callable[[], bool], *, timeout_s: float = 1.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("condition was not reached before timeout")


def test_service_combines_live_history_and_radio_snapshots() -> None:
    live = ControlledLiveSource()
    wpsd = FakeWpsdSource()
    service = DmrMonitorService(
        live,
        wpsd,
        history_refresh_interval_s=60.0,
        reconnect_delay_s=0.05,
    )

    service.start()
    assert live.started.wait(timeout=1)
    _wait_until(lambda: service.latest_state.health is DmrMonitorHealth.HEALTHY)

    state = service.latest_state
    assert state.live_available
    assert state.history_available
    assert state.radio_available
    assert state.history == (_history_record(),)
    assert state.radio_info is not None
    assert state.radio_info.radio_rx_hz == 434_537_500
    assert state.radio_info.radio_tx_hz == 439_537_500

    service.stop()
    assert live.closed.is_set()


def test_live_events_drive_current_audio_and_clear_on_end() -> None:
    live = ControlledLiveSource()
    service = DmrMonitorService(
        live,
        FakeWpsdSource(),
        history_refresh_interval_s=60.0,
        reconnect_delay_s=0.05,
    )
    service.start()
    assert live.started.wait(timeout=1)

    live.push(_START_LINE)
    _wait_until(lambda: len(service.latest_state.active_calls) == 1)
    active = service.latest_state.active_calls[0]
    assert active.identity.callsign == "KC9KPJ"
    assert active.identity.slot == 1
    assert active.identity.target == "TG 3100"

    live.push(_ALIAS_LINE)
    _wait_until(
        lambda: service.latest_state.active_calls[0].talker_alias == "KC9KPJ Michael"
    )

    live.push(_END_LINE)
    _wait_until(lambda: service.latest_state.active_calls == ())
    service.stop()


def test_live_disconnect_never_leaves_stale_current_audio() -> None:
    live = ControlledLiveSource()
    service = DmrMonitorService(
        live,
        FakeWpsdSource(),
        history_refresh_interval_s=60.0,
        reconnect_delay_s=1.0,
    )
    service.start()
    assert live.started.wait(timeout=1)

    live.push(_START_LINE)
    _wait_until(lambda: len(service.latest_state.active_calls) == 1)

    live.fail("ssh feed lost")
    _wait_until(lambda: not service.latest_state.live_available)

    state = service.latest_state
    assert state.active_calls == ()
    assert state.live_error == "ssh feed lost"
    assert state.health is DmrMonitorHealth.DEGRADED
    service.stop()


def test_http_failure_preserves_cached_data_but_marks_source_unavailable() -> None:
    live = ControlledLiveSource()
    wpsd = FakeWpsdSource()
    service = DmrMonitorService(
        live,
        wpsd,
        history_refresh_interval_s=0.05,
        reconnect_delay_s=0.05,
    )
    service.start()
    assert live.started.wait(timeout=1)
    _wait_until(lambda: service.latest_state.health is DmrMonitorHealth.HEALTHY)

    wpsd.fail_history = True
    _wait_until(lambda: not service.latest_state.history_available)

    state = service.latest_state
    assert state.history == (_history_record(),)
    assert state.history_error == "history offline"
    assert state.live_available
    assert state.radio_available
    assert state.health is DmrMonitorHealth.DEGRADED
    service.stop()


def test_start_rejects_duplicate_workers_and_stop_is_safe() -> None:
    live = ControlledLiveSource()
    service = DmrMonitorService(
        live,
        FakeWpsdSource(),
        history_refresh_interval_s=60.0,
        reconnect_delay_s=0.05,
    )
    service.start()
    assert live.started.wait(timeout=1)

    try:
        service.start()
    except RuntimeError as error:
        assert "already running" in str(error)
    else:
        raise AssertionError("duplicate start unexpectedly succeeded")

    service.stop()
    assert not service.is_running
