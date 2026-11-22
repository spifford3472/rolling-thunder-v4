"""Manually started WSPR receive lifecycle and volatile operator statistics."""

import logging
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from math import isfinite
from threading import Event, RLock, Thread
from time import monotonic
from typing import Protocol

from rolling_thunder.domain import GPSFixState, GPSPosition
from rolling_thunder.ft8.diagnostics import FT8ClockQuality, NTPClockStatus, assess_ft8_clock
from rolling_thunder.gps import GPSConnectionState, GPSState
from rolling_thunder.maidenhead import maidenhead_grid, maidenhead_grid_center
from rolling_thunder.repeater_nearby import haversine_distance_miles
from rolling_thunder.wspr_audio import WsprAudioError
from rolling_thunder.wspr_decoder import (
    WSPR_PCM_BYTES,
    WSPR_WINDOW_SECONDS,
    WsprDecode,
    WsprDecoder,
    WsprDecoderError,
)
from rolling_thunder.wspr_reporting import WsprSpot, WsprUploadStatus

# WSJT-X FrequencyList.cpp, including the IARU Region 2 six-meter frequency.
WSPR_BANDS = (
    ("40 m", 7_038_600), ("30 m", 10_138_700), ("20 m", 14_095_600),
    ("17 m", 18_104_600), ("15 m", 21_094_600), ("12 m", 24_924_600),
    ("10 m", 28_124_600), ("6 m", 50_293_000),
)
_SLOT_SECONDS = 120
_SETTLE_SECONDS = 2.0
_GPS_MAX_AGE_S = 4.0
_STATIONARY_SECONDS = 5.0
_STATIONARY_SPEED_M_S = 0.15
_RESULT_WINDOW_SECONDS = 90.0
_LOGGER = logging.getLogger(__name__)
_MAX_NTP_OFFSET_S = 0.25
_MAX_CLOCK_STEP_S = 0.25
_MAX_GPS_DISAGREEMENT_WITH_NTP_S = 2.0


class WsprInhibit(RuntimeError):
    """Release resources and display this operator-facing reason."""


class WsprCancelled(Exception):
    """The operator or dashboard revoked the session."""


class WsprBandUnavailable(Exception):
    """The requested band cannot be tuned on the current receive path."""


class WsprLease(Protocol):
    def tune(self, dial_hz: int) -> None: ...
    def verify(self, dial_hz: int) -> None: ...


class WsprAudioSource(Protocol):
    def capture(
        self, start_utc: datetime, byte_count: int, now_utc: Callable[[], datetime],
        check: Callable[[], None],
    ) -> bytes: ...


class WsprReporter(Protocol):
    def report(self, spot: WsprSpot, *, cancel: Event) -> WsprUploadStatus: ...


@dataclass(frozen=True, slots=True)
class WsprOrigin:
    latitude: float
    longitude: float
    grid: str

    @classmethod
    def from_fix(cls, fix: GPSPosition) -> "WsprOrigin":
        assert fix.latitude is not None and fix.longitude is not None
        return cls(fix.latitude, fix.longitude, maidenhead_grid(fix.latitude, fix.longitude)[:4])


@dataclass(frozen=True, slots=True)
class WsprExtreme:
    callsign: str
    miles: float


@dataclass(frozen=True, slots=True)
class WsprSnapshot:
    detail: str
    grid: str | None
    band: str | None
    elapsed_s: float
    decodes_per_hour: float
    band_totals: tuple[tuple[str, int], ...]
    closest: WsprExtreme | None
    farthest: WsprExtreme | None
    upload: str
    active: bool


def next_wspr_slot(now_utc: datetime) -> datetime:
    """Find the first even UTC minute with room to tune and settle."""
    earliest = now_utc.timestamp() + _SETTLE_SECONDS
    index = int(earliest // _SLOT_SECONDS) + 1
    return datetime.fromtimestamp(index * _SLOT_SECONDS, UTC)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _local_midnight(day: date) -> datetime:
    # The system timezone rules for midnight may differ from the current offset.
    return datetime.combine(day, time()).astimezone(UTC)


class WsprReceive:
    """Own one manually authorized WSPR worker and one bounded result worker."""

    def __init__(
        self,
        *,
        callsign: str,
        lease: Callable[[], AbstractContextManager[WsprLease]] | None,
        audio: WsprAudioSource,
        decoder: WsprDecoder,
        reporter: WsprReporter,
        ntp_status: Callable[[], NTPClockStatus] | None = None,
        now_utc: Callable[[], datetime] = _utc_now,
        elapsed_clock: Callable[[], float] = monotonic,
    ) -> None:
        self._callsign = callsign
        self._lease = lease
        self._audio = audio
        self._decoder = decoder
        self._reporter = reporter
        self._ntp_status = ntp_status
        self._ntp: NTPClockStatus | None = None
        self._clock_anchor: tuple[datetime, float] | None = None
        self._now = now_utc
        self._elapsed = elapsed_clock
        self._lock = RLock()
        self._gps: GPSState | None = None
        self._stationary_since: float | None = None
        self._last_motion_sample: float | None = None
        self._selected = False
        self._closed = False
        self._worker: Thread | None = None
        self._cancel = Event()
        self._origin: WsprOrigin | None = None
        self._started: float | None = None
        self._last_elapsed = 0.0
        self._listening_started: float | None = None
        self._band: str | None = None
        self._detail = "Idle"
        self._upload = "Waiting for a decode"
        self._day: date | None = None
        self._accounted_at = self._elapsed()
        self._listening_seconds = 0.0
        self._totals = dict.fromkeys((band for band, _ in WSPR_BANDS), 0)
        self._closest: WsprExtreme | None = None
        self._farthest: WsprExtreme | None = None

    @property
    def busy(self) -> bool:
        """Report resource cleanup as busy even after cancellation."""
        with self._lock:
            return self._worker is not None

    def observe_gps(self, state: GPSState) -> None:
        """Consume existing GPS publications without acquiring hardware or doing I/O."""
        with self._lock:
            self._gps = state
            problem = self._motion_problem()
            if problem is not None:
                self._stationary_since = self._last_motion_sample = None
                if self._worker is not None and not self._cancel.is_set():
                    self.stop(problem)
                return
            receipt = state.utc.received_monotonic_s
            assert receipt is not None
            if (
                self._last_motion_sample is None
                or receipt - self._last_motion_sample > _GPS_MAX_AGE_S
                or receipt < self._last_motion_sample
            ):
                self._stationary_since = receipt
            self._last_motion_sample = receipt

    def select(self, selected: bool) -> None:
        """Update context availability. Selection alone never starts reception."""
        with self._lock:
            if self._selected and not selected:
                self.stop("Left WSPR screen")
            if selected and not self._selected:
                self._band = None
                if self._worker is None:
                    self._detail = "Idle"
            self._selected = selected

    def start(self) -> bool:
        """Accept only an explicit selected-screen command with healthy inputs."""
        with self._lock:
            if self._closed or not self._selected or self._worker is not None:
                return False
            problem = self._motion_problem()
            since = self._stationary_since
            if problem is None and (
                since is None or self._last_motion_sample is None
                or self._last_motion_sample - since < _STATIONARY_SECONDS
            ):
                problem = "Wait for five seconds of stationary GPS fixes"
            reserve = self._lease
            if reserve is None:
                problem = "FT-891 receive path unavailable"
            if problem is not None or reserve is None:
                self._detail = f"Start inhibited: {problem}"
                return False
            assert self._gps is not None and self._gps.position is not None
            origin = WsprOrigin.from_fix(self._gps.position)
            cancel = Event()
            self._cancel = cancel
            self._ntp = None
            self._clock_anchor = (self._now(), self._elapsed())
            self._origin = origin
            self._detail = "Starting"
            self._upload = "Waiting for a decode"
            self._band = None
            self._last_elapsed = 0.0
            self._worker = Thread(
                target=self._run, args=(reserve, origin, cancel), name="wspr-receive", daemon=True,
            )
            self._worker.start()
            return True

    def start_inhibited(self, reason: str) -> None:
        with self._lock:
            if self._worker is None:
                self._detail = f"Start inhibited: {reason}"

    def stop(self, reason: str = "Operator stopped") -> bool:
        """Revoke current results and request bounded release without blocking Tk."""
        with self._lock:
            if self._worker is None or self._cancel.is_set():
                return False
            self._finish_listening()
            self._detail = f"Stopped: {reason}"
            self._cancel.set()
            return True

    def close(self) -> None:
        """Release the WSPR lease before the runtime disconnects the radio."""
        with self._lock:
            self._closed = True
            self.stop("Application shutting down")
            worker = self._worker
        if worker is not None:
            worker.join(timeout=12)
            if worker.is_alive():
                raise RuntimeError("WSPR receive resources did not release")

    def snapshot(self) -> WsprSnapshot:
        with self._lock:
            now = self._elapsed()
            self._account(now)
            elapsed = self._last_elapsed if self._started is None else now - self._started
            grid = self._origin.grid if self._origin is not None and self._worker else None
            if grid is None and self._motion_problem() is None:
                assert self._gps is not None and self._gps.position is not None
                grid = WsprOrigin.from_fix(self._gps.position).grid
            return WsprSnapshot(
                detail=self._detail, grid=grid, band=self._band, elapsed_s=elapsed,
                decodes_per_hour=(
                    sum(self._totals.values()) * 3600 / self._listening_seconds
                    if self._listening_seconds else 0
                ),
                band_totals=tuple(self._totals.items()), closest=self._closest,
                farthest=self._farthest, upload=self._upload,
                active=self._worker is not None and not self._cancel.is_set(),
            )

    def _motion_problem(self) -> str | None:
        state = self._gps
        if state is None or state.connection_state is not GPSConnectionState.CONNECTED:
            return "GPS motion unavailable"
        position = state.position
        receipt = state.utc.received_monotonic_s
        if (
            position is None or position.fix_state is GPSFixState.NO_FIX
            or position.speed_m_s is None or position.latitude is None
            or not state.utc.trusted or receipt is None
            or not 0 <= self._elapsed() - receipt <= _GPS_MAX_AGE_S
            or abs((self._now() - position.updated_at).total_seconds()) > _GPS_MAX_AGE_S
        ):
            return "GPS position or motion is stale or unavailable"
        if position.speed_m_s > _STATIONARY_SPEED_M_S:
            return "Vehicle motion detected"
        return None

    def _clock_problem(self) -> str | None:
        wall, elapsed = self._now(), self._elapsed()
        if self._clock_anchor is not None:
            start_wall, start_elapsed = self._clock_anchor
            change = (wall - start_wall).total_seconds() - (elapsed - start_elapsed)
            if abs(change) > _MAX_CLOCK_STEP_S:
                return "System UTC shifted during WSPR"

        ntp = self._ntp
        if ntp is not None and ntp.synchronized:
            offset = ntp.offset_seconds
            if offset is None or not isfinite(offset) or abs(offset) > _MAX_NTP_OFFSET_S:
                return "NTP clock offset exceeds WSPR limit"
            # NMEA time is referenced to the fix, while its receipt includes
            # receiver and serial latency. Use it as a coarse cross-check when
            # chrony independently verifies the clock used to align the audio.
            tolerance = _MAX_GPS_DISAGREEMENT_WITH_NTP_S
        else:
            tolerance = 1.0
        assessment = assess_ft8_clock(
            system_utc=wall, monotonic_seconds=elapsed,
            gps_utc=self._gps.utc if self._gps is not None else None,
            ntp=ntp, maximum_offset_seconds=tolerance,
        )
        if assessment.quality is FT8ClockQuality.TRUSTED:
            return None
        offset = assessment.offset_seconds
        if offset is None:
            return "UTC could not be verified by NTP or GPS"
        return f"System UTC disagrees with GPS ({offset:+.2f} s)"

    def _refresh_ntp(self, cancel: Event) -> None:
        # Run once per slot on the receive worker, before tuning or audio capture.
        if self._ntp_status is None or cancel.is_set():
            return
        status = self._ntp_status()
        with self._lock:
            self._ntp = status

    def _check(self, cancel: Event) -> None:
        with self._lock:
            if cancel.is_set():
                raise WsprCancelled
            problem = self._motion_problem() or self._clock_problem()
            if problem is not None:
                self.stop(problem)
                raise WsprCancelled

    def _finish_listening(self) -> None:
        now = self._elapsed()
        self._account(now)
        if self._started is not None:
            self._last_elapsed = now - self._started
        self._started = None
        self._listening_started = None

    def _account(self, now: float) -> None:
        wall = self._now()
        day = wall.astimezone().date()
        start = self._accounted_at
        if day != self._day:
            self._day = day
            self._totals = dict.fromkeys(self._totals, 0)
            self._closest = self._farthest = None
            self._listening_seconds = 0.0
            start = max(start, now - (wall - _local_midnight(day)).total_seconds())
        if self._listening_started is not None:
            self._listening_seconds += max(0, now - max(start, self._listening_started))
        self._accounted_at = now

    def _run(
        self, reserve: Callable[[], AbstractContextManager[WsprLease]],
        origin: WsprOrigin, cancel: Event,
    ) -> None:
        result: Thread | None = None
        try:
            self._refresh_ntp(cancel)
            self._check(cancel)
            if not self._decoder.available:
                raise WsprInhibit("Pipe-only WSPR decoder unavailable")
            with reserve() as lease:
                self._check(cancel)
                with self._lock:
                    self._check(cancel)
                    self._started = self._elapsed()
                    self._account(self._started)
                slot = next_wspr_slot(self._now())
                index = 0
                while True:
                    self._check(cancel)
                    band, dial = WSPR_BANDS[index]
                    with self._lock:
                        self._band = band
                        self._detail = "Listening · waiting for UTC slot"
                    try:
                        lease.tune(dial)
                    except WsprBandUnavailable:
                        with self._lock:
                            self._detail = f"Skipped {band}: receive tuning unavailable"
                        self._wait_until(slot + timedelta(seconds=_SLOT_SECONDS - 6), cancel)
                    else:
                        if (slot - self._now()).total_seconds() < _SETTLE_SECONDS:
                            slot = next_wspr_slot(self._now())
                        self._wait_until(slot - timedelta(seconds=1), cancel)
                        # Check the radio before launching ALSA so CAT latency
                        # does not delay the first PCM read across the slot boundary.
                        lease.verify(dial)
                        next_verify = self._elapsed() + 5.0

                        def verify_receive(frequency: int = dial) -> None:
                            nonlocal next_verify
                            self._check(cancel)
                            if self._elapsed() >= next_verify:
                                lease.verify(frequency)
                                next_verify = self._elapsed() + 5.0

                        with self._lock:
                            self._check(cancel)
                            self._detail = "Listening"
                            self._listening_started = self._elapsed() + max(
                                0.0, (slot - self._now()).total_seconds(),
                            )
                        try:
                            pcm = self._audio.capture(slot, WSPR_PCM_BYTES, self._now, verify_receive)
                        finally:
                            with self._lock:
                                self._account(self._elapsed())
                                self._listening_started = None
                        self._check(cancel)
                        lease.verify(dial)
                        if result is not None and result.is_alive():
                            raise WsprInhibit("Decoder exceeded the available processing window")
                        result = Thread(
                            target=self._decode, args=(pcm, index, slot, origin, cancel),
                            name="wspr-results", daemon=True,
                        )
                        result.start()
                        del pcm
                    index = (index + 1) % len(WSPR_BANDS)
                    slot += timedelta(seconds=_SLOT_SECONDS)
                    self._refresh_ntp(cancel)
        except WsprCancelled:
            pass
        except WsprInhibit as error:
            _LOGGER.warning("WSPR stopped: %s", error)
            with self._lock:
                if not self.stop(str(error)):
                    self._detail = f"Stopped: {error}"
        except WsprAudioError as error:
            _LOGGER.warning("WSPR stopped: %s", error)
            self.stop(str(error))
        except OSError:
            self.stop("Receive audio unavailable; check DigiRig")
        except Exception:  # noqa: BLE001 - Suppress payload-bearing worker exception text.
            self.stop("Receive resources failed; verify radio and audio")
        finally:
            cancel.set()
            if result is not None:
                result.join()
            with self._lock:
                self._finish_listening()
                self._worker = None

    def _wait_until(self, deadline: datetime, cancel: Event) -> None:
        while (remaining := (deadline - self._now()).total_seconds()) > 0:
            self._check(cancel)
            cancel.wait(min(0.2, remaining))

    def _decode(
        self, pcm: bytes, index: int, slot: datetime, origin: WsprOrigin, cancel: Event,
    ) -> None:
        band, dial = WSPR_BANDS[index]
        result_deadline = self._elapsed() + _RESULT_WINDOW_SECONDS
        try:
            decodes = self._decoder.decode(pcm, dial, cancel)
            del pcm
            # Use the receive window's date, even if a worker result arrives after midnight.
            sample_day = (slot + timedelta(seconds=WSPR_WINDOW_SECONDS)).astimezone().date()
            with self._lock:
                self._check(cancel)
                self._account(self._elapsed())
                if self._day == sample_day:
                    self._totals[band] += len(decodes)
            for decode in decodes:
                self._check(cancel)
                if self._elapsed() >= result_deadline:
                    with self._lock:
                        self._check(cancel)
                        self._upload = "Upload window ended"
                    return
                status = self._reporter.report(
                    WsprSpot(
                        receiver_callsign=self._callsign, receiver_grid=origin.grid, slot_utc=slot,
                        dial_hz=dial, callsign=decode.callsign, grid=decode.locator,
                        frequency_hz=decode.frequency_hz, snr_db=decode.snr_db,
                        dt_s=decode.time_offset_s, drift_hz=decode.drift_hz,
                        power_dbm=decode.power_dbm,
                    ),
                    cancel=cancel,
                )
                with self._lock:
                    if cancel.is_set():
                        if status is WsprUploadStatus.IN_FLIGHT_UNKNOWN:
                            self._upload = "Sent; acknowledgement unknown"
                        return
                    self._check(cancel)
                    self._upload = (
                        "Sent; acknowledgement unknown"
                        if status is WsprUploadStatus.IN_FLIGHT_UNKNOWN
                        else status.value.capitalize()
                    )
                    self._account(self._elapsed())
                    if status is WsprUploadStatus.ACCEPTED and self._day == sample_day:
                        self._record_extreme(decode, origin)
                if status in (WsprUploadStatus.UNAVAILABLE, WsprUploadStatus.IN_FLIGHT_UNKNOWN):
                    break
        except WsprCancelled:
            pass
        except WsprDecoderError:
            self.stop("WSPR decoder failed")
        except Exception:  # noqa: BLE001 - Suppress payload-bearing transport exception text.
            self.stop("WSPR result processing failed")

    def _record_extreme(self, decode: WsprDecode, origin: WsprOrigin) -> None:
        if decode.locator is None:
            return
        try:
            latitude, longitude = maidenhead_grid_center(decode.locator)
        except ValueError:
            return
        extreme = WsprExtreme(
            decode.callsign, haversine_distance_miles(
                origin.latitude, origin.longitude, latitude, longitude,
            ),
        )
        if self._closest is None or extreme.miles < self._closest.miles:
            self._closest = extreme
        if self._farthest is None or extreme.miles > self._farthest.miles:
            self._farthest = extreme
