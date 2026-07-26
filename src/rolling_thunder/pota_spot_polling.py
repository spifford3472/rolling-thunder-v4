"""Controlled polling lifecycle for refreshing POTA spot service state."""

from rolling_thunder.pota_spot_service import PotaSpotService, PotaSpotServiceState
from rolling_thunder.radio_polling import PollScheduler, ScheduledPoll


class PotaSpotPollingService:
    """Schedule non-overlapping POTA spot refreshes with explicit lifecycle control."""

    def __init__(
        self,
        service: PotaSpotService,
        scheduler: PollScheduler,
        *,
        interval_s: float = 60.0,
        refresh_on_start: bool = True,
    ) -> None:
        if interval_s <= 0:
            raise ValueError("POTA spot polling interval must be positive.")

        self._service = service
        self._scheduler = scheduler
        self._interval_s = interval_s
        self._refresh_on_start = refresh_on_start
        self._scheduled_poll: ScheduledPoll | None = None
        self._refreshing = False
        self._refresh_count = 0
        self._latest_state = service.get_state()

    @property
    def is_running(self) -> bool:
        """Return whether future refresh callbacks are scheduled."""
        return self._scheduled_poll is not None

    @property
    def is_refreshing(self) -> bool:
        """Return whether a refresh callback is currently executing."""
        return self._refreshing

    @property
    def refresh_count(self) -> int:
        """Return the number of completed refresh attempts."""
        return self._refresh_count

    @property
    def latest_state(self) -> PotaSpotServiceState:
        """Return the latest immutable state observed by the polling service."""
        return self._latest_state

    def start(self) -> PotaSpotServiceState:
        """Start scheduled polling and optionally refresh immediately."""
        if self.is_running:
            raise RuntimeError("POTA spot polling service is already running.")

        if self._refresh_on_start:
            self._refresh_once()
        else:
            self._latest_state = self._service.get_state()

        self._scheduled_poll = self._scheduler.schedule_repeating(
            self._interval_s,
            self._poll_once,
        )
        return self._latest_state

    def stop(self) -> PotaSpotServiceState:
        """Cancel future callbacks and return the latest observed state."""
        scheduled_poll = self._scheduled_poll
        self._scheduled_poll = None
        if scheduled_poll is not None:
            scheduled_poll.cancel()
        return self._latest_state

    def _poll_once(self) -> None:
        if not self.is_running or self._refreshing:
            return
        self._refresh_once()

    def _refresh_once(self) -> None:
        if self._refreshing:
            return

        self._refreshing = True
        try:
            self._latest_state = self._service.refresh()
            self._refresh_count += 1
        finally:
            self._refreshing = False
