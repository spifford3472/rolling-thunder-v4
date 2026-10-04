"""Explicit non-overlapping lifecycle for Forge spot refreshes."""

from rolling_thunder.forge_spot_aggregation import (
    ForgeAggregationState,
    ForgeSpotAggregationService,
)
from rolling_thunder.radio_polling import PollScheduler, ScheduledPoll
from rolling_thunder.spot_domain import SpotProvider


class ForgeSpotPollingService:
    """Schedule complete Forge provider refreshes with explicit lifecycle control."""

    def __init__(
        self,
        service: ForgeSpotAggregationService,
        scheduler: PollScheduler,
        *,
        interval_s: float = 60.0,
        dx_cache_publish_interval_s: float | None = None,
        refresh_on_start: bool = True,
    ) -> None:
        if interval_s <= 0:
            raise ValueError("Forge spot polling interval must be positive.")
        if (
            dx_cache_publish_interval_s is not None
            and dx_cache_publish_interval_s <= 0
        ):
            raise ValueError("Forge DX cache publication interval must be positive.")

        self._service = service
        self._scheduler = scheduler
        self._interval_s = interval_s
        self._dx_cache_publish_interval_s = dx_cache_publish_interval_s
        self._refresh_on_start = refresh_on_start
        self._scheduled_poll: ScheduledPoll | None = None
        self._dx_scheduled_poll: ScheduledPoll | None = None
        self._refreshing = False
        self._refresh_count = 0
        self._latest_state = service.get_state()

    @property
    def is_running(self) -> bool:
        """Return whether future refresh callbacks are scheduled."""
        return self._scheduled_poll is not None

    @property
    def is_refreshing(self) -> bool:
        """Return whether one complete provider refresh is executing."""
        return self._refreshing

    @property
    def refresh_count(self) -> int:
        """Return the number of completed refresh-all attempts."""
        return self._refresh_count

    @property
    def latest_state(self) -> ForgeAggregationState:
        """Return the latest immutable aggregation state observed by polling."""
        return self._latest_state

    def start(self) -> ForgeAggregationState:
        """Start scheduled refreshes and optionally refresh immediately."""
        if self.is_running:
            raise RuntimeError("Forge spot polling service is already running.")

        if self._refresh_on_start:
            self._refresh_once()
        else:
            self._latest_state = self._service.get_state()

        self._scheduled_poll = self._scheduler.schedule_repeating(
            self._interval_s,
            self._poll_once,
        )
        if self._dx_cache_publish_interval_s is not None:
            self._dx_scheduled_poll = self._scheduler.schedule_repeating(
                self._dx_cache_publish_interval_s,
                self._poll_dx_once,
            )
        return self._latest_state

    def stop(self) -> ForgeAggregationState:
        """Cancel future callbacks and return the latest observed state."""
        scheduled_poll = self._scheduled_poll
        dx_scheduled_poll = self._dx_scheduled_poll
        self._scheduled_poll = None
        self._dx_scheduled_poll = None
        if scheduled_poll is not None:
            scheduled_poll.cancel()
        if dx_scheduled_poll is not None:
            dx_scheduled_poll.cancel()
        return self._latest_state

    def _poll_dx_once(self) -> None:
        if not self.is_running or self._refreshing:
            return

        self._refreshing = True
        try:
            self._latest_state = self._service.refresh_provider(SpotProvider.DX)
        finally:
            self._refreshing = False

    def _poll_once(self) -> None:
        if not self.is_running or self._refreshing:
            return
        self._refresh_once()

    def _refresh_once(self) -> None:
        if self._refreshing:
            return

        self._refreshing = True
        try:
            self._latest_state = self._service.refresh_all()
            self._refresh_count += 1
        finally:
            self._refreshing = False
