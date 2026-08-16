"""Runtime composition for the read-only DMR monitor and local commit path."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from queue import Empty, SimpleQueue
from uuid import UUID

from rolling_thunder.contact_repository import ContactRepository
from rolling_thunder.dmr_commit import DmrContactCommitController, DmrContactWriter
from rolling_thunder.dmr_monitor import (
    DmrLiveLineSource,
    DmrMonitorService,
    DmrMonitorSnapshot,
    DmrWpsdSource,
    SshDmrLiveLineSource,
    WpsdDmrHttpSource,
)
from rolling_thunder.dmr_panel_commands import DmrPanelCommandController
from rolling_thunder.dmr_selection import DmrSelectionController
from rolling_thunder.domain import Contact
from rolling_thunder.value_types import MaidenheadGrid


class DmrCommitEventKind(StrEnum):
    """Terminal background commit outcome waiting for UI-thread synchronization."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class DmrCommitEvent:
    """Thread-safe terminal commit event drained by the dashboard refresh loop."""

    kind: DmrCommitEventKind
    stage_id: UUID
    contact: Contact | None = None
    error: str | None = None


@dataclass(slots=True)
class DmrPanelRuntime:
    """Own DMR monitoring, selection, commands, and durable local commit lifecycle."""

    monitor: DmrMonitorService
    selection: DmrSelectionController
    commit: DmrContactCommitController
    commands: DmrPanelCommandController
    _commit_events: SimpleQueue[DmrCommitEvent] = field(repr=False)

    @classmethod
    def build(
        cls,
        *,
        database_path: Path,
        hotspot_host: str,
        ssh_user: str,
        private_key: Path,
        my_grid_provider: Callable[[], MaidenheadGrid | None],
        http_timeout_s: float = 5.0,
        connect_timeout_s: int = 5,
        history_limit: int = 20,
        history_refresh_interval_s: float = 30.0,
        reconnect_delay_s: float = 2.0,
        live_source: DmrLiveLineSource | None = None,
        wpsd_source: DmrWpsdSource | None = None,
        writer: DmrContactWriter | None = None,
    ) -> DmrPanelRuntime:
        """Compose production adapters by default while allowing offline test doubles."""
        host = hotspot_host.strip()
        if not host:
            raise ValueError("DMR hotspot host must not be blank.")

        resolved_live_source = live_source or SshDmrLiveLineSource(
            host=host,
            user=ssh_user,
            private_key=private_key,
            connect_timeout_s=connect_timeout_s,
        )
        resolved_wpsd_source = wpsd_source or WpsdDmrHttpSource(
            base_url=f"http://{host}",
            timeout_s=http_timeout_s,
            history_limit=history_limit,
        )
        monitor = DmrMonitorService(
            resolved_live_source,
            resolved_wpsd_source,
            history_refresh_interval_s=history_refresh_interval_s,
            reconnect_delay_s=reconnect_delay_s,
        )
        selection = DmrSelectionController()
        commit_events: SimpleQueue[DmrCommitEvent] = SimpleQueue()

        def commit_succeeded(stage_id: UUID, contact: Contact) -> None:
            commit_events.put(
                DmrCommitEvent(
                    kind=DmrCommitEventKind.SUCCEEDED,
                    stage_id=stage_id,
                    contact=contact,
                )
            )

        def commit_failed(stage_id: UUID, message: str) -> None:
            commit_events.put(
                DmrCommitEvent(
                    kind=DmrCommitEventKind.FAILED,
                    stage_id=stage_id,
                    error=message,
                )
            )

        commit = DmrContactCommitController(
            writer or ContactRepository(database_path),
            on_succeeded=commit_succeeded,
            on_failed=commit_failed,
        )
        commands = DmrPanelCommandController(
            monitor,
            selection,
            commit,
            my_grid_provider=my_grid_provider,
        )
        return cls(
            monitor=monitor,
            selection=selection,
            commit=commit,
            commands=commands,
            _commit_events=commit_events,
        )

    @property
    def latest_monitor_state(self) -> DmrMonitorSnapshot:
        """Return the latest background-produced DMR snapshot without I/O."""
        return self.monitor.latest_state

    @property
    def is_running(self) -> bool:
        """Return whether the DMR monitor workers are currently owned."""
        return self.monitor.is_running

    @property
    def polling_enabled(self) -> bool:
        """Return whether WPSD HTTP polling is currently enabled."""
        return self.monitor.polling_enabled

    def set_polling_enabled(self, enabled: bool) -> None:
        """Enable WPSD polling only when the DMR panel needs fresh HTTP data."""
        self.monitor.set_polling_enabled(enabled)

    def start(self) -> DmrMonitorSnapshot:
        """Start background SSH/WPSD monitoring without doing network I/O here."""
        return self.monitor.start()

    def stop(self) -> None:
        """Stop background DMR monitoring and interrupt any blocked SSH read."""
        self.monitor.stop()

    def synchronize_commit_events(self) -> tuple[DmrCommitEvent, ...]:
        """Apply worker outcomes on the caller thread and return newly observed events."""
        observed: list[DmrCommitEvent] = []
        while True:
            try:
                event = self._commit_events.get_nowait()
            except Empty:
                break

            if event.kind is DmrCommitEventKind.SUCCEEDED:
                self.commands.complete_commit(event.stage_id)
            else:
                self.commands.fail_commit(event.stage_id)
            observed.append(event)

        return tuple(observed)
