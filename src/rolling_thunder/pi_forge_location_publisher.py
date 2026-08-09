"""Background-only publication of fresh Pi GPS fixes to Forge."""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import Executor, ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from threading import RLock
from time import monotonic
from typing import Protocol

from rolling_thunder.domain import GPSFixState
from rolling_thunder.forge_location_client import (
    ForgeLocationClientError,
    ForgeLocationPublishReceipt,
    ForgeLocationStaleError,
)
from rolling_thunder.forge_mobile_location import MobileLocationRecord
from rolling_thunder.gps import GPSConnectionState, GPSState
from rolling_thunder.radio_polling import PollScheduler, ScheduledPoll

_LOGGER = logging.getLogger("rolling_thunder.pi_forge_location")
_MAX_ERROR_LENGTH = 500
_MAX_SPEED_M_S = 100.0
_DEFAULT_PUBLISH_INTERVAL_S = 600.0
_DEFAULT_RETRY_INTERVAL_S = 60.0
_DEFAULT_UNUSABLE_RETRY_INTERVAL_S = 30.0
_DEFAULT_SCHEDULER_INTERVAL_S = 30.0
_DEFAULT_MAXIMUM_GPS_SAMPLE_AGE_S = 5.0

GPSStateSource = Callable[[], GPSState]
Clock = Callable[[], datetime]
MonotonicClock = Callable[[], float]
ExecutorFactory = Callable[[], Executor]


class ForgeLocationClient(Protocol):
    """Synchronous client boundary used only by the background publisher worker."""

    def publish(self, location: MobileLocationRecord) -> ForgeLocationPublishReceipt:
        """Publish one location or raise a typed Forge location client error."""
        ...


class PiForgeLocationPublishStatus(StrEnum):
    """Latest outcome of the Pi-to-Forge location publisher."""

    IDLE = "idle"
    SKIPPED = "skipped"
    PUBLISHED = "published"
    REJECTED = "rejected"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class PiForgeLocationPublisherState:
    """Immutable observability state for location publication."""

    status: PiForgeLocationPublishStatus = PiForgeLocationPublishStatus.IDLE
    attempt_count: int = 0
    success_count: int = 0
    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    last_fix_at: datetime | None = None
    last_revision: int | None = None
    last_error: str | None = None


class PiForgeLocationPublisher:
    """Select one fresh typed GPS fix and synchronously publish it to Forge."""

    def __init__(
        self,
        state_source: GPSStateSource,
        client: ForgeLocationClient,
        *,
        clock: Clock | None = None,
        monotonic_clock: MonotonicClock = monotonic,
        maximum_gps_sample_age_s: float = _DEFAULT_MAXIMUM_GPS_SAMPLE_AGE_S,
    ) -> None:
        if maximum_gps_sample_age_s <= 0:
            raise ValueError("Maximum GPS publication sample age must be positive.")
        self._state_source = state_source
        self._client = client
        self._clock = clock or (lambda: datetime.now(UTC))
        self._monotonic_clock = monotonic_clock
        self._maximum_gps_sample_age_s = maximum_gps_sample_age_s
        self._lock = RLock()
        self._state = PiForgeLocationPublisherState()
        self._last_consumed_fix_at: datetime | None = None

    def get_state(self) -> PiForgeLocationPublisherState:
        """Return the latest immutable publisher state without external work."""
        with self._lock:
            return self._state

    def publish_latest(self) -> PiForgeLocationPublisherState:
        """Publish the latest usable GPS fix, converting expected failures into state."""
        now = self._aware_now()
        now_monotonic = self._monotonic_clock()
        gps_state = self._state_source()
        candidate, skip_reason = self._candidate(
            gps_state,
            now=now,
            now_monotonic=now_monotonic,
        )
        if candidate is None:
            return self._publish_state(
                replace(
                    self.get_state(),
                    status=PiForgeLocationPublishStatus.SKIPPED,
                    last_error=self._bounded_text(skip_reason or "GPS fix is not usable."),
                )
            )

        with self._lock:
            if self._last_consumed_fix_at == candidate.fix_at:
                self._state = replace(
                    self._state,
                    status=PiForgeLocationPublishStatus.SKIPPED,
                    last_error="Latest GPS fix was already consumed by Forge publication.",
                )
                return self._state

            attempt_count = self._state.attempt_count + 1
            self._state = replace(
                self._state,
                status=PiForgeLocationPublishStatus.IDLE,
                attempt_count=attempt_count,
                last_attempt_at=now,
                last_fix_at=candidate.fix_at,
                last_error=None,
            )

        try:
            receipt = self._client.publish(candidate)
        except ForgeLocationStaleError as error:
            with self._lock:
                self._last_consumed_fix_at = candidate.fix_at
                self._state = replace(
                    self._state,
                    status=PiForgeLocationPublishStatus.REJECTED,
                    last_error=self._bounded_error(error),
                )
                return self._state
        except ForgeLocationClientError as error:
            with self._lock:
                self._state = replace(
                    self._state,
                    status=PiForgeLocationPublishStatus.FAILED,
                    last_error=self._bounded_error(error),
                )
                return self._state

        with self._lock:
            self._last_consumed_fix_at = candidate.fix_at
            self._state = replace(
                self._state,
                status=PiForgeLocationPublishStatus.PUBLISHED,
                success_count=self._state.success_count + 1,
                last_success_at=now,
                last_revision=receipt.revision,
                last_error=None,
            )
            return self._state

    def _candidate(
        self,
        state: GPSState,
        *,
        now: datetime,
        now_monotonic: float,
    ) -> tuple[MobileLocationRecord | None, str | None]:
        if state.connection_state is not GPSConnectionState.CONNECTED:
            return None, "GPS is not connected."
        position = state.position
        if position is None or position.fix_state is GPSFixState.NO_FIX:
            return None, "GPS does not have a valid position fix."
        if position.latitude is None or position.longitude is None:
            return None, "GPS position is missing coordinates."

        utc = state.utc
        if not utc.trusted or utc.value is None:
            return None, "GPS UTC is not trusted and fresh."
        received_monotonic = utc.received_monotonic_s
        if received_monotonic is None:
            return None, "GPS UTC does not include a monotonic receipt timestamp."
        sample_age_s = now_monotonic - received_monotonic
        if sample_age_s < 0:
            return None, "GPS UTC receipt timestamp is in the future."
        if sample_age_s > self._maximum_gps_sample_age_s:
            return None, "GPS UTC sample is stale."

        fix_at = utc.value
        if fix_at > now:
            return None, "GPS fix timestamp is later than the Pi UTC clock."
        if now - fix_at > timedelta(seconds=30):
            return None, "GPS fix timestamp is more than 30 seconds old."

        speed_m_s = position.speed_m_s
        if speed_m_s is not None and speed_m_s > _MAX_SPEED_M_S:
            return None, "GPS speed exceeds the Forge mobile-location bound."

        try:
            return (
                MobileLocationRecord(
                    latitude=position.latitude,
                    longitude=position.longitude,
                    fix_at=fix_at,
                    received_at=now,
                    speed_m_s=speed_m_s,
                    heading_degrees=position.heading_degrees,
                ),
                None,
            )
        except ValueError as error:
            return None, self._bounded_error(error)

    def _aware_now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Pi Forge location publisher clock must be timezone-aware.")
        return value.astimezone(UTC)

    def _publish_state(
        self,
        state: PiForgeLocationPublisherState,
    ) -> PiForgeLocationPublisherState:
        with self._lock:
            self._state = state
            return self._state

    @staticmethod
    def _bounded_error(error: BaseException) -> str:
        return PiForgeLocationPublisher._bounded_text(
            str(error).strip() or error.__class__.__name__
        )

    @staticmethod
    def _bounded_text(value: str) -> str:
        return value.strip()[:_MAX_ERROR_LENGTH]


def _default_executor_factory() -> Executor:
    return ThreadPoolExecutor(
        max_workers=1,
        thread_name_prefix="rolling-thunder-pi-forge-location",
    )


class PiForgeLocationPublishingService:
    """Schedule bounded location publication without doing I/O on scheduler/UI threads."""

    def __init__(
        self,
        publisher: PiForgeLocationPublisher,
        scheduler: PollScheduler,
        *,
        scheduler_interval_s: float = _DEFAULT_SCHEDULER_INTERVAL_S,
        publish_interval_s: float = _DEFAULT_PUBLISH_INTERVAL_S,
        retry_interval_s: float = _DEFAULT_RETRY_INTERVAL_S,
        unusable_retry_interval_s: float = _DEFAULT_UNUSABLE_RETRY_INTERVAL_S,
        monotonic_clock: MonotonicClock = monotonic,
        executor_factory: ExecutorFactory | None = None,
    ) -> None:
        for value, name in (
            (scheduler_interval_s, "scheduler interval"),
            (publish_interval_s, "publish interval"),
            (retry_interval_s, "retry interval"),
            (unusable_retry_interval_s, "unusable retry interval"),
        ):
            if value <= 0:
                raise ValueError(f"Pi Forge location {name} must be positive.")

        self._publisher = publisher
        self._scheduler = scheduler
        self._scheduler_interval_s = scheduler_interval_s
        self._publish_interval_s = publish_interval_s
        self._retry_interval_s = retry_interval_s
        self._unusable_retry_interval_s = unusable_retry_interval_s
        self._monotonic_clock = monotonic_clock
        self._executor_factory = executor_factory or _default_executor_factory
        self._lock = RLock()
        self._scheduled_poll: ScheduledPoll | None = None
        self._executor: Executor | None = None
        self._worker_pending = False
        self._next_due_monotonic = 0.0
        self._run_count = 0

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._scheduled_poll is not None

    @property
    def is_publishing(self) -> bool:
        with self._lock:
            return self._worker_pending

    @property
    def run_count(self) -> int:
        with self._lock:
            return self._run_count

    @property
    def latest_state(self) -> PiForgeLocationPublisherState:
        return self._publisher.get_state()

    @property
    def scheduler_interval_s(self) -> float:
        """Return the configured background eligibility-check cadence."""
        return self._scheduler_interval_s

    @property
    def publish_interval_s(self) -> float:
        """Return the successful-location publication cadence."""
        return self._publish_interval_s

    @property
    def retry_interval_s(self) -> float:
        """Return the failed-publication retry cadence."""
        return self._retry_interval_s

    @property
    def unusable_retry_interval_s(self) -> float:
        """Return the unusable-GPS retry cadence."""
        return self._unusable_retry_interval_s

    def start(self) -> PiForgeLocationPublisherState:
        """Start scheduling and queue the first publication opportunity in background."""
        startup_state = self._publisher.get_state()
        with self._lock:
            if self._scheduled_poll is not None or self._executor is not None:
                raise RuntimeError("Pi Forge location publishing service is already running.")
            executor = self._executor_factory()
            try:
                scheduled_poll = self._scheduler.schedule_repeating(
                    self._scheduler_interval_s,
                    self._poll_once,
                )
            except Exception:
                executor.shutdown(wait=False, cancel_futures=True)
                raise
            self._executor = executor
            self._scheduled_poll = scheduled_poll
            self._next_due_monotonic = self._monotonic_clock()

        self._queue_if_due()
        return startup_state

    def stop(self) -> PiForgeLocationPublisherState:
        """Cancel future work and wait for any bounded in-flight request to finish."""
        with self._lock:
            scheduled_poll = self._scheduled_poll
            executor = self._executor
            self._scheduled_poll = None
            self._executor = None

        if scheduled_poll is not None:
            scheduled_poll.cancel()
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=True)

        with self._lock:
            self._worker_pending = False
        return self._publisher.get_state()

    def _poll_once(self) -> None:
        self._queue_if_due()

    def _queue_if_due(self) -> None:
        with self._lock:
            executor = self._executor
            if executor is None or self._scheduled_poll is None or self._worker_pending:
                return
            if self._monotonic_clock() < self._next_due_monotonic:
                return
            self._worker_pending = True

        try:
            executor.submit(self._run_publish)
        except Exception:
            with self._lock:
                self._worker_pending = False
            raise

    def _run_publish(self) -> None:
        try:
            state = self._publisher.publish_latest()
        except Exception:
            _LOGGER.exception(
                "Unexpected Pi Forge location publication failure; future attempts will continue."
            )
            delay_s = self._retry_interval_s
        else:
            if state.status in {
                PiForgeLocationPublishStatus.PUBLISHED,
                PiForgeLocationPublishStatus.REJECTED,
            }:
                delay_s = self._publish_interval_s
            elif state.status is PiForgeLocationPublishStatus.FAILED:
                delay_s = self._retry_interval_s
            else:
                delay_s = self._unusable_retry_interval_s
        finally:
            with self._lock:
                self._run_count += 1
                self._next_due_monotonic = self._monotonic_clock() + delay_s
                self._worker_pending = False
