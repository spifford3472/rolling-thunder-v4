"""Tests for DMR runtime composition, lifecycle, and UI-thread commit synchronization."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from time import monotonic, sleep

from rolling_thunder.dmr_activity import DmrActivitySource
from rolling_thunder.dmr_monitor import DmrMonitorHealth
from rolling_thunder.dmr_panel_runtime import (
    DmrCommitEventKind,
    DmrPanelRuntime,
)
from rolling_thunder.dmr_wpsd import (
    WpsdDmrHistoryIdentity,
    WpsdDmrHistoryRecord,
    WpsdRadioInfo,
)
from rolling_thunder.domain import Contact, RadioMode
from rolling_thunder.storage import StorageError


class QuietLiveSource:
    """Fake restricted SSH feed that becomes ready and blocks until stopped."""

    def __init__(self) -> None:
        self.closed = False

    def stream(self, stop_event: Event) -> Iterator[str]:
        yield "RTDMR READY"
        while not stop_event.wait(0.01):
            continue

    def close(self) -> None:
        self.closed = True


class FixedWpsdSource:
    def __init__(self) -> None:
        self.record = _history_record()
        self.operator_record = _operator_history_record()
        self.radio = _radio_info()

    def fetch_history(self) -> tuple[WpsdDmrHistoryRecord, ...]:
        return (self.record, self.operator_record)

    def fetch_radio_info(self) -> WpsdRadioInfo:
        return self.radio


class RecordingWriter:
    def __init__(self) -> None:
        self.contacts: list[Contact] = []

    def add(self, contact: Contact) -> None:
        self.contacts.append(contact)


class FailOnceWriter(RecordingWriter):
    def __init__(self) -> None:
        super().__init__()
        self.attempts = 0

    def add(self, contact: Contact) -> None:
        self.attempts += 1
        if self.attempts == 1:
            raise StorageError("simulated storage failure")
        super().add(contact)


def _radio_info() -> WpsdRadioInfo:
    return WpsdRadioInfo(
        status="IDLE",
        mode="Duplex",
        hotspot_tx_hz=434_537_500,
        hotspot_rx_hz=439_537_500,
    )


def _history_record() -> WpsdDmrHistoryRecord:
    occurred_at = datetime(2026, 8, 16, 0, 7, 22, tzinfo=UTC)
    return WpsdDmrHistoryRecord(
        identity=WpsdDmrHistoryIdentity(
            occurred_at=occurred_at,
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


def _operator_history_record() -> WpsdDmrHistoryRecord:
    occurred_at = datetime(2026, 8, 16, 0, 7, 20, tzinfo=UTC)
    return WpsdDmrHistoryRecord(
        identity=WpsdDmrHistoryIdentity(
            occurred_at=occurred_at,
            callsign="KI5VNB",
            slot=1,
            talkgroup=3100,
            source=DmrActivitySource.RF,
        ),
        name="Geoff",
        country="USA",
        callsign_suffix=None,
        target="TG 3100",
        duration_s=1.0,
        packet_loss_percent=0.0,
    )


def _runtime(tmp_path: Path, writer: RecordingWriter) -> DmrPanelRuntime:
    runtime = DmrPanelRuntime.build(
        database_path=tmp_path / "contacts.db",
        hotspot_host="192.168.8.235",
        ssh_user="pi-star",
        private_key=tmp_path / "dmr-key",
        my_grid_provider=lambda: "EM79xm",
        history_refresh_interval_s=0.05,
        reconnect_delay_s=0.05,
        live_source=QuietLiveSource(),
        wpsd_source=FixedWpsdSource(),
        writer=writer,
        operator_callsign="KI5VNB",
    )
    runtime.start()
    _wait_until(lambda: runtime.latest_monitor_state.monitored_talkgroup == 3100)
    return runtime


def _wait_until(predicate: Callable[[], bool], *, timeout_s: float = 1.0) -> None:
    deadline = monotonic() + timeout_s
    while monotonic() < deadline:
        if predicate():
            return
        sleep(0.01)
    raise AssertionError("condition did not become true before timeout")


def _stage_history(runtime: DmrPanelRuntime) -> None:
    record = _history_record()
    runtime.selection.replace_history((record,))
    runtime.selection.select_identity(record.identity)
    state = runtime.selection.stage_selected(
        _radio_info(),
        my_grid="EM79xm",
    )
    assert state.staged_qso is not None


def test_runtime_start_and_stop_own_monitor_lifecycle(tmp_path: Path) -> None:
    live = QuietLiveSource()
    runtime = DmrPanelRuntime.build(
        database_path=tmp_path / "contacts.db",
        hotspot_host="192.168.8.235",
        ssh_user="pi-star",
        private_key=tmp_path / "dmr-key",
        my_grid_provider=lambda: "EM79xm",
        history_refresh_interval_s=0.05,
        reconnect_delay_s=0.05,
        live_source=live,
        wpsd_source=FixedWpsdSource(),
        writer=RecordingWriter(),
    )

    runtime.set_polling_enabled(False)
    assert not runtime.polling_enabled
    runtime.start()
    sleep(0.05)
    assert runtime.latest_monitor_state.live_available
    assert not runtime.latest_monitor_state.history_available
    assert not runtime.latest_monitor_state.radio_available

    runtime.set_polling_enabled(True)
    assert runtime.polling_enabled
    _wait_until(
        lambda: runtime.latest_monitor_state.health is DmrMonitorHealth.HEALTHY
    )

    assert runtime.is_running
    assert runtime.latest_monitor_state.live_available
    assert runtime.latest_monitor_state.history_available
    assert runtime.latest_monitor_state.radio_available

    runtime.stop()

    assert not runtime.is_running
    assert live.closed


def test_success_event_clears_stage_only_when_caller_synchronizes(tmp_path: Path) -> None:
    writer = RecordingWriter()
    runtime = _runtime(tmp_path, writer)
    _stage_history(runtime)
    staged = runtime.selection.state.staged_qso
    assert staged is not None

    assert runtime.commands.secondary()
    _wait_until(lambda: runtime.commit.status.committed_stage_id == staged.stage_id)

    assert runtime.selection.state.staged_qso == staged

    events = runtime.synchronize_commit_events()

    assert len(events) == 1
    assert events[0].kind is DmrCommitEventKind.SUCCEEDED
    assert events[0].stage_id == staged.stage_id
    assert events[0].contact is not None
    assert events[0].contact.mode is RadioMode.DMR
    assert events[0].contact.frequency_hz == 439_537_500
    assert events[0].contact.my_grid == "EM79xm"
    assert runtime.selection.state.staged_qso is None
    assert writer.contacts == [events[0].contact]
    assert runtime.synchronize_commit_events() == ()
    runtime.stop()


def test_failure_event_preserves_stage_and_releases_retry_guard(tmp_path: Path) -> None:
    writer = FailOnceWriter()
    runtime = _runtime(tmp_path, writer)
    _stage_history(runtime)
    staged = runtime.selection.state.staged_qso
    assert staged is not None

    assert runtime.commands.secondary()
    _wait_until(lambda: runtime.commit.status.last_error is not None)

    assert not runtime.commands.secondary()
    events = runtime.synchronize_commit_events()

    assert len(events) == 1
    assert events[0].kind is DmrCommitEventKind.FAILED
    assert events[0].stage_id == staged.stage_id
    assert events[0].error == "simulated storage failure"
    assert runtime.selection.state.staged_qso == staged

    assert runtime.commands.secondary()
    _wait_until(lambda: runtime.commit.status.committed_stage_id == staged.stage_id)
    success_events = runtime.synchronize_commit_events()

    assert len(success_events) == 1
    assert success_events[0].kind is DmrCommitEventKind.SUCCEEDED
    assert writer.attempts == 2
    assert runtime.selection.state.staged_qso is None
    runtime.stop()


def test_build_with_production_adapters_performs_no_network_io(tmp_path: Path) -> None:
    runtime = DmrPanelRuntime.build(
        database_path=tmp_path / "contacts.db",
        hotspot_host="192.0.2.1",
        ssh_user="pi-star",
        private_key=tmp_path / "missing-key",
        my_grid_provider=lambda: None,
    )

    assert not runtime.is_running
    assert runtime.latest_monitor_state.history == ()
    assert runtime.latest_monitor_state.active_calls == ()
