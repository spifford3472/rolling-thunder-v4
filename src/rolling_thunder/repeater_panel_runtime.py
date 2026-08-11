"""Startup composition for the local repeater panel and background Active writes."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from rolling_thunder.gps import GPSState
from rolling_thunder.repeater_active_override_controller import (
    RepeaterActiveOverrideController,
    RepeaterActiveOverrideStatus,
    WorkerLauncher,
)
from rolling_thunder.repeater_csv import (
    DEFAULT_REPEATER_CSV_PATH,
    RepeaterCsvError,
    load_repeater_csv,
)
from rolling_thunder.repeater_domain import RepeaterCatalog
from rolling_thunder.repeater_nearby import RepeaterNearbyService
from rolling_thunder.repeater_panel import RepeaterPanelController
from rolling_thunder.repeater_repository import RepeaterActiveOverrideRepository
from rolling_thunder.storage import StorageError

GPSStateProvider = Callable[[], GPSState | None]
Clock = Callable[[], datetime]


class RepeaterPanelRuntime:
    """Own startup I/O and publish UI-safe repeater panel/persistence state."""

    def __init__(
        self,
        *,
        panel: RepeaterPanelController,
        persistence: RepeaterActiveOverrideController | None,
        persistence_error: str | None = None,
    ) -> None:
        self.panel = panel
        self.persistence = persistence
        self._persistence_error = persistence_error
        self._applied_completion_revision = 0

    @classmethod
    def build(
        cls,
        *,
        database_path: Path,
        gps_state: GPSStateProvider,
        source_path: Path = DEFAULT_REPEATER_CSV_PATH,
        clock: Clock | None = None,
        worker_launcher: WorkerLauncher | None = None,
    ) -> RepeaterPanelRuntime:
        """Load local source/overrides once and compose no-I/O panel refresh state."""
        source_error: str | None = None
        try:
            catalog = load_repeater_csv(source_path)
        except RepeaterCsvError as error:
            catalog = RepeaterCatalog(
                source_filename=source_path.name,
                source_sha256="0" * 64,
                repeaters=(),
            )
            source_error = f"REPEATER DATA UNAVAILABLE — {error}"

        persistence: RepeaterActiveOverrideController | None = None
        persistence_error: str | None = None
        overrides: dict[str, bool] = {}
        try:
            repository = RepeaterActiveOverrideRepository(database_path)
            overrides = repository.read_all()
            if worker_launcher is None:
                persistence = RepeaterActiveOverrideController(repository)
            else:
                persistence = RepeaterActiveOverrideController(
                    repository,
                    worker_launcher=worker_launcher,
                )
        except StorageError as error:
            persistence_error = f"ACTIVE OVERRIDES UNAVAILABLE — {error}"

        if clock is None:
            nearby = RepeaterNearbyService(catalog, overrides=overrides)
        else:
            nearby = RepeaterNearbyService(
                catalog,
                overrides=overrides,
                clock=clock,
            )
        panel = RepeaterPanelController(
            lambda: nearby.nearby(gps_state()),
            apply_override=nearby.set_override,
            source_error=source_error,
        )
        return cls(
            panel=panel,
            persistence=persistence,
            persistence_error=persistence_error,
        )

    @property
    def persistence_status(self) -> RepeaterActiveOverrideStatus:
        """Return immutable save status without performing storage I/O."""
        if self.persistence is None:
            return RepeaterActiveOverrideStatus(last_error=self._persistence_error)
        return self.persistence.status

    def synchronize_completed_persistence(self) -> RepeaterActiveOverrideStatus:
        """Apply each successful background result to in-memory state exactly once."""
        status = self.persistence_status
        action = status.last_completed_action
        if (
            action is not None
            and status.completion_revision > self._applied_completion_revision
        ):
            self.panel.apply_persisted_override(action)
            self._applied_completion_revision = status.completion_revision
        return status
