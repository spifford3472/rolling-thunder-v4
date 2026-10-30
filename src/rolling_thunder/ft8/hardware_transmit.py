"""Bounded FT8 hardware transmit executor.

Checkpoint 6 introduced a supervised owner-test request. Checkpoint 7 retains
that API and adds a separate QSO-authorized request. Both use the same verified
CAT/PTT, watchdog, radio-verification, and left-only audio mechanics. Neither
API is a general-purpose application PTT surface.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Event, Lock, Thread, Timer
from typing import Protocol
from uuid import UUID, uuid4

from rolling_thunder.domain import Frequency, RadioConnectionState, RadioState
from rolling_thunder.ft8.audio_output import FT8AudioOutput
from rolling_thunder.ft8.domain import FT8QsoContext
from rolling_thunder.ft8.encoder import FT8_SAMPLE_RATE_HZ, FT8Waveform
from rolling_thunder.ft8.power_advisor import FT8PowerPolicy
from rolling_thunder.radio import RadioError
from rolling_thunder.radio_band import RadioBandResolutionError, resolve_radio_band


@dataclass(frozen=True, slots=True)
class FT8TransmitMeterSummary:
    """Peak raw FT-891 meter values observed while one QSO was keyed."""

    sample_count: int = 0
    alc_peak_raw: int | None = None
    power_peak_raw: int | None = None
    swr_peak_raw: int | None = None


@dataclass(frozen=True, slots=True)
class FT8TransmitPeriodTelemetry:
    """Per-emission CAT power readback; raw RF meter is not calibrated watts."""

    qso_id: UUID
    started_at_utc: datetime
    ended_at_utc: datetime
    configured_power_watts: int | None
    power_readback_verified: bool
    frequency_hz: int
    transmitted: bool
    transmit_audio_offset_hz: int | None = None


@dataclass(frozen=True, slots=True)
class FT8HardwareTestAuthorization:
    """One explicit owner authorization for a supervised hardware test."""

    authorization_id: str
    approved_at_utc: datetime

    def __post_init__(self) -> None:
        if not self.authorization_id.strip():
            raise ValueError("authorization_id must not be blank")
        if self.approved_at_utc.tzinfo is None or self.approved_at_utc.utcoffset() is None:
            raise ValueError("approved_at_utc must be timezone-aware")
        object.__setattr__(self, "approved_at_utc", self.approved_at_utc.astimezone(UTC))


@dataclass(frozen=True, slots=True)
class FT8QsoHardwareTransmitAuthorization:
    """One physical-transmit authority tied to one frozen QSO context."""

    authorization_id: str
    authorized_at_utc: datetime
    context: FT8QsoContext

    def __post_init__(self) -> None:
        if not self.authorization_id.strip():
            raise ValueError("authorization_id must not be blank")
        if self.authorized_at_utc.tzinfo is None or self.authorized_at_utc.utcoffset() is None:
            raise ValueError("authorized_at_utc must be timezone-aware")
        normalized = self.authorized_at_utc.astimezone(UTC)
        object.__setattr__(self, "authorized_at_utc", normalized)
        if normalized != self.context.authorized_utc:
            raise ValueError("QSO hardware authorization must match the frozen QSO context")


@dataclass(frozen=True, slots=True)
class FT8HardwareTestRequest:
    """One bounded, already-prepared, explicitly authorized hardware test."""

    authorization: FT8HardwareTestAuthorization
    waveform: FT8Waveform
    maximum_key_down_s: float
    expected_radio_frequency_hz: int
    expected_radio_mode: str

    def __post_init__(self) -> None:
        _validate_physical_request(
            waveform=self.waveform,
            maximum_key_down_s=self.maximum_key_down_s,
            expected_radio_frequency_hz=self.expected_radio_frequency_hz,
            expected_radio_mode=self.expected_radio_mode,
            label="hardware-test",
        )


@dataclass(frozen=True, slots=True)
class FT8QsoHardwareTransmitRequest:
    """One bounded physical transmit belonging to one authorized QSO."""

    authorization: FT8QsoHardwareTransmitAuthorization
    waveform: FT8Waveform
    maximum_key_down_s: float
    expected_radio_frequency_hz: int
    expected_radio_mode: str
    busy_extension: bool = False

    def __post_init__(self) -> None:
        _validate_physical_request(
            waveform=self.waveform,
            maximum_key_down_s=self.maximum_key_down_s,
            expected_radio_frequency_hz=self.expected_radio_frequency_hz,
            expected_radio_mode=self.expected_radio_mode,
            label="QSO",
        )
        context = self.authorization.context
        if self.expected_radio_frequency_hz != context.radio_frequency_hz:
            raise ValueError("QSO hardware frequency must match the frozen QSO context")
        if self.expected_radio_mode.strip().upper() != context.radio_mode.strip().upper():
            raise ValueError("QSO hardware mode must match the frozen QSO context")


class FT8HardwareTransmitExecutor(Protocol):
    """Owner-test physical capability retained from Checkpoint 6."""

    def execute_test(self, request: FT8HardwareTestRequest) -> None:
        """Execute one already-authorized supervised hardware test."""
        ...

    def cancel_test(self) -> None:
        """Cancel the active owner test if one exists."""
        ...

    def close(self) -> None:
        """Release executor resources without creating another test."""
        ...


class FT8QsoHardwareTransmitExecutor(Protocol):
    """Physical capability available only to one CP7 QSO transmit session."""

    @property
    def transmitting(self) -> bool:
        """Return the executor's already-published PTT assertion state."""
        ...

    def execute_qso(self, request: FT8QsoHardwareTransmitRequest) -> None:
        """Execute one already-authorized QSO waveform."""
        ...

    def cancel_qso(self) -> None:
        """Force receive and revoke the active QSO transmit."""
        ...

    def meter_summary(self, qso_id: UUID) -> FT8TransmitMeterSummary | None:
        """Return the peak meter summary collected for one QSO UUID."""
        ...

    def close(self) -> None:
        """Force receive and permanently close the physical executor."""
        ...


class FT8TestPtt(Protocol):
    """Narrow PTT capability used only by the bounded FT8 executor."""

    def key(self) -> None:
        """Assert the selected physical PTT mechanism."""
        ...

    def release(self) -> None:
        """Return the radio to receive."""
        ...

    def cancel(self) -> None:
        """Cancel any active keying."""
        ...

    def close(self) -> None:
        """Release and close the capability."""
        ...


class FT8TestRadio(Protocol):
    """Minimum concrete-radio surface needed by the bounded FT8 executor."""

    def refresh_state(self) -> RadioState:
        """Read the current physical frequency and mode."""
        ...

    def create_cp6_cat_ptt_capability(self) -> FT8TestPtt:
        """Return the already-validated Enhanced-CAT FT8 PTT capability."""
        ...


class WatchdogTimer(Protocol):
    """Cancelable watchdog timer boundary used for deterministic tests."""

    def start(self) -> None:
        """Start the watchdog."""
        ...

    def cancel(self) -> None:
        """Cancel the watchdog."""
        ...


WatchdogFactory = Callable[[float, Callable[[], None]], WatchdogTimer]


def _threading_watchdog(delay_s: float, callback: Callable[[], None]) -> WatchdogTimer:
    timer = Timer(delay_s, callback)
    timer.daemon = True
    return timer


class BoundedFT8HardwareTransmitExecutor:
    """Combine verified Enhanced-CAT PTT and left-only DigiRig playback."""

    def __init__(
        self,
        radio: FT8TestRadio,
        audio_output: FT8AudioOutput,
        *,
        watchdog_factory: WatchdogFactory = _threading_watchdog,
        period_recorder: Callable[[FT8TransmitPeriodTelemetry], None] | None = None,
        intent_started: Callable[[UUID, UUID, int, int | None], None] | None = None,
        intent_finished: Callable[[UUID], None] | None = None,
        intent_completed: Callable[[UUID, FT8TransmitPeriodTelemetry], None] | None = None,
        power_policy: FT8PowerPolicy | None = None,
        ptt_uncertain: Callable[[], None] | None = None,
        transmit_inhibited: Callable[[], bool] | None = None,
    ) -> None:
        self._radio = radio
        self._audio_output = audio_output
        self._ptt = radio.create_cp6_cat_ptt_capability()
        self._watchdog_factory = watchdog_factory
        self._period_recorder = period_recorder
        self._intent_started = intent_started
        self._intent_finished = intent_finished
        self._intent_completed = intent_completed
        self._power_policy = power_policy
        self._ptt_uncertain = ptt_uncertain
        self._transmit_inhibited = transmit_inhibited
        self._lock = Lock()
        self._active = False
        self._keyed = False
        self._closed = False
        self._meter_summaries: dict[UUID, FT8TransmitMeterSummary] = {}
        self._transmit_periods: dict[UUID, list[FT8TransmitPeriodTelemetry]] = {}
        # Per-QSO state is local to the existing authorized transmit executor.
        self._auto_power_last: dict[UUID, tuple[str, int]] = {}
        self._auto_power_suspended: set[UUID] = set()

    @property
    def transmitting(self) -> bool:
        """Read-only indication of PTT asserted by this executor."""
        with self._lock:
            return self._keyed

    def execute_test(self, request: FT8HardwareTestRequest) -> None:
        self._execute(
            waveform=request.waveform,
            maximum_key_down_s=request.maximum_key_down_s,
            expected_radio_frequency_hz=request.expected_radio_frequency_hz,
            expected_radio_mode=request.expected_radio_mode,
            label="hardware test",
            qso_id=None,
        )

    def execute_qso(self, request: FT8QsoHardwareTransmitRequest) -> None:
        self._execute(
            waveform=request.waveform,
            maximum_key_down_s=request.maximum_key_down_s,
            expected_radio_frequency_hz=request.expected_radio_frequency_hz,
            expected_radio_mode=request.expected_radio_mode,
            label="QSO transmit",
            qso_id=request.authorization.context.qso_id,
            power_message=request.waveform.encoded.message,
            busy_extension=request.busy_extension,
        )

    def meter_summary(self, qso_id: UUID) -> FT8TransmitMeterSummary | None:
        """Return the peak meter summary collected for one QSO UUID."""
        with self._lock:
            return self._meter_summaries.get(qso_id)

    def transmit_periods(self, qso_id: UUID) -> tuple[FT8TransmitPeriodTelemetry, ...]:
        """Return bounded in-memory emission records, not yet persisted."""
        with self._lock:
            return tuple(self._transmit_periods.get(qso_id, ()))

    def cancel_test(self) -> None:
        """Force receive even when no owner test is currently active."""
        try:
            self._ptt.cancel()
        except Exception:
            if self._ptt_uncertain is not None:
                self._ptt_uncertain()
            raise

    def cancel_qso(self) -> None:
        """Force receive even when no QSO transmit is currently active."""
        try:
            self._ptt.cancel()
        except Exception:
            if self._ptt_uncertain is not None:
                self._ptt_uncertain()
            raise

    def close(self) -> None:
        """Force receive and permanently close the executor."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
        try:
            self._ptt.close()
        except Exception:
            if self._ptt_uncertain is not None:
                self._ptt_uncertain()
            raise

    def _execute(
        self,
        *,
        waveform: FT8Waveform,
        maximum_key_down_s: float,
        expected_radio_frequency_hz: int,
        expected_radio_mode: str,
        label: str,
        qso_id: UUID | None,
        power_message: str | None = None,
        busy_extension: bool = False,
    ) -> None:
        with self._lock:
            if self._closed:
                raise RuntimeError("FT8 hardware transmit executor is closed")
            if self._active:
                raise RuntimeError("FT8 hardware transmit is already active")
            if self._transmit_inhibited is not None and self._transmit_inhibited():
                raise RuntimeError("FT8 transmission inhibited by unresolved PTT alarm")
            self._active = True

        watchdog: WatchdogTimer | None = None
        meter_stop: Event | None = None
        meter_thread: Thread | None = None
        emission_started: datetime | None = None
        verified_power: int | None = None
        power_readback_verified = False
        keyed = False
        intent_id: UUID | None = None
        try:
            self._verify_radio(
                expected_radio_frequency_hz=expected_radio_frequency_hz,
                expected_radio_mode=expected_radio_mode,
                label=label,
            )
            # A missing/unreadable CAT power setting is unknown, NEVER inferred
            # from a raw power meter value or a previous QSO power target.
            reader = getattr(self._radio, "read_power_watts", None)
            if callable(reader):
                try:
                    value = reader()
                    if type(value) is int and 5 <= value <= 100:
                        verified_power = value
                        power_readback_verified = True
                except (RadioError, RuntimeError, ValueError, TypeError):
                    pass
            if self._power_policy is not None:
                # Final QSO transmit boundary: never reprogram a manual change.
                # Unknown CAT settings or an exceeded cap require operator action.
                try:
                    band = resolve_radio_band(Frequency(hz=expected_radio_frequency_hz))
                except RadioBandResolutionError as exc:
                    raise RuntimeError("FT8 transmit band is unrecognized") from exc
                if verified_power is None:
                    raise RuntimeError("FT8 transmit requires verified CAT power readback")
                cap = self._power_policy.limit_for(band.value)
                if verified_power > cap:
                    raise RuntimeError(
                        f"FT8 CAT power {verified_power} W exceeds {band.value} ceiling {cap} W"
                    )
            # Only a repeated, identical unanswered call may step upward.
            # A newly changed message (report/73) holds the existing power.
            # Manual CAT changes suspend automation rather than being overwritten.
            policy = self._power_policy
            if (
                qso_id is not None and policy is not None and policy.adaptive_enabled
                and power_message is not None and verified_power is not None
            ):
                history = self._auto_power_last.get(qso_id)
                if history is not None:
                    previous_message, previous_power = history
                    if verified_power != previous_power:
                        # An operator changed RF power: suspend this attempt.
                        self._auto_power_suspended.add(qso_id)
                    elif (
                        qso_id not in self._auto_power_suspended
                        and not busy_extension
                        and previous_message == power_message
                        and re.fullmatch(r"[A-R]{2}[0-9]{2}(?:[A-X]{2})?", power_message.split()[-1])
                        and verified_power < cap
                    ):
                        setter = getattr(self._radio, "set_power_watts", None)
                        if not callable(setter):
                            raise RuntimeError("FT8 auto power needs CAT setting capability")
                        requested = min(cap, verified_power + 5)
                        try:
                            programmed = setter(requested)
                            observed = reader() if callable(reader) else None
                        except (RadioError, ValueError, RuntimeError, TypeError) as exc:
                            raise RuntimeError("FT8 automatic CAT power change failed") from exc
                        if programmed != requested or observed != requested:
                            raise RuntimeError("FT8 automatic power readback mismatch")
                        verified_power = requested
                if qso_id not in self._auto_power_suspended:
                    self._auto_power_last[qso_id] = (power_message, verified_power)
            if qso_id is not None and self._intent_started is not None:
                intent_id = uuid4()
                self._intent_started(intent_id, qso_id, expected_radio_frequency_hz, verified_power)
            self._ptt.key()
            keyed = True
            with self._lock:
                self._keyed = True
            emission_started = datetime.now(UTC)
            def watchdog_release() -> None:
                try:
                    self._ptt.release()
                    with self._lock:
                        self._keyed = False
                except Exception:
                    if self._ptt_uncertain is not None:
                        self._ptt_uncertain()
                    raise

            watchdog = self._watchdog_factory(
                maximum_key_down_s,
                watchdog_release,
            )
            watchdog.start()
            if qso_id is not None:
                meter_stop, meter_thread = self._start_meter_sampling(qso_id)
            self._audio_output.play(waveform)
        finally:
            # Even release, journal, or meter cleanup failures must not strand
            # the executor in a permanently active state.
            try:
                if meter_stop is not None:
                    meter_stop.set()
                # Keep the independent timer armed until normal release
                # succeeds. If CAT release raises, allow watchdog retry.
                try:
                    self._ptt.release()
                    with self._lock:
                        self._keyed = False
                except Exception:
                    if self._ptt_uncertain is not None:
                        self._ptt_uncertain()
                    raise
                if watchdog is not None:
                    watchdog.cancel()
                if qso_id is not None and keyed and emission_started is not None:
                    record = FT8TransmitPeriodTelemetry(
                        qso_id=qso_id,
                        started_at_utc=emission_started,
                        ended_at_utc=datetime.now(UTC),
                        configured_power_watts=verified_power,
                        power_readback_verified=power_readback_verified,
                        frequency_hz=expected_radio_frequency_hz,
                        transmitted=True,
                        transmit_audio_offset_hz=waveform.base_frequency_hz,
                    )
                    if intent_id is not None and self._intent_completed is not None:
                        self._intent_completed(intent_id, record)
                    else:
                        if self._period_recorder is not None:
                            self._period_recorder(record)
                        if intent_id is not None and self._intent_finished is not None:
                            self._intent_finished(intent_id)
                    with self._lock:
                        self._transmit_periods.setdefault(qso_id, []).append(record)
                        self._transmit_periods[qso_id] = self._transmit_periods[qso_id][-64:]
            finally:
                if meter_thread is not None:
                    meter_thread.join(timeout=1.0)
                with self._lock:
                    self._keyed = False
                    self._active = False

    def _start_meter_sampling(self, qso_id: UUID) -> tuple[Event, Thread] | tuple[None, None]:
        reader = getattr(self._radio, "read_cp6_tx_meters", None)
        if not callable(reader):
            return None, None

        stop = Event()

        def sample() -> None:
            while not stop.wait(0.25):
                try:
                    alc, power, swr = reader()
                except (RadioError, RuntimeError, ValueError):
                    return
                self._record_meter_sample(
                    qso_id,
                    alc=alc,
                    power=power,
                    swr=swr,
                )

        thread = Thread(
            target=sample,
            daemon=True,
            name="rolling-thunder-ft8-meters",
        )
        thread.start()
        return stop, thread

    def _record_meter_sample(
        self,
        qso_id: UUID,
        *,
        alc: int,
        power: int,
        swr: int,
    ) -> None:
        with self._lock:
            previous = self._meter_summaries.get(qso_id, FT8TransmitMeterSummary())
            self._meter_summaries[qso_id] = FT8TransmitMeterSummary(
                sample_count=previous.sample_count + 1,
                alc_peak_raw=_peak(previous.alc_peak_raw, alc),
                power_peak_raw=_peak(previous.power_peak_raw, power),
                swr_peak_raw=_peak(previous.swr_peak_raw, swr),
            )

    def _verify_radio(
        self,
        *,
        expected_radio_frequency_hz: int,
        expected_radio_mode: str,
        label: str,
    ) -> None:
        state = self._radio.refresh_state()
        if state.connection_state is not RadioConnectionState.CONNECTED:
            raise RuntimeError(f"FT8 {label} requires a connected radio")
        if state.transmitting:
            raise RuntimeError(f"FT8 {label} requires the radio to be in receive")
        if state.frequency is None or state.frequency.hz != expected_radio_frequency_hz:
            actual = None if state.frequency is None else state.frequency.hz
            raise RuntimeError(
                f"FT8 {label} frequency mismatch: "
                f"expected {expected_radio_frequency_hz} Hz, got {actual}"
            )
        expected_mode = expected_radio_mode.strip().upper()
        actual_mode = None if state.mode is None else state.mode.value
        if actual_mode != expected_mode:
            raise RuntimeError(
                f"FT8 {label} mode mismatch: expected {expected_mode}, got {actual_mode}"
            )


class RecordingFT8HardwareTransmitExecutor:
    """Hardware-free fake supporting both CP6 and CP7 physical boundaries."""

    def __init__(self) -> None:
        self.requests: list[FT8HardwareTestRequest] = []
        self.qso_requests: list[FT8QsoHardwareTransmitRequest] = []
        self.cancel_count = 0
        self.qso_cancel_count = 0
        self.close_count = 0
        self._closed = False

    def execute_test(self, request: FT8HardwareTestRequest) -> None:
        if self._closed:
            raise RuntimeError("FT8 hardware transmit executor is closed")
        self.requests.append(request)

    def execute_qso(self, request: FT8QsoHardwareTransmitRequest) -> None:
        if self._closed:
            raise RuntimeError("FT8 hardware transmit executor is closed")
        self.qso_requests.append(request)

    def cancel_test(self) -> None:
        self.cancel_count += 1

    def cancel_qso(self) -> None:
        self.qso_cancel_count += 1

    def meter_summary(self, qso_id: UUID) -> FT8TransmitMeterSummary | None:
        """Hardware-free fake has no physical meter samples."""
        _ = qso_id
        return None

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.close_count += 1


def _peak(previous: int | None, current: int) -> int:
    return current if previous is None else max(previous, current)


def _validate_physical_request(
    *,
    waveform: FT8Waveform,
    maximum_key_down_s: float,
    expected_radio_frequency_hz: int,
    expected_radio_mode: str,
    label: str,
) -> None:
    if not math.isfinite(maximum_key_down_s) or maximum_key_down_s <= 0:
        raise ValueError("maximum_key_down_s must be finite and positive")
    if maximum_key_down_s > 20.0:
        raise ValueError("maximum_key_down_s must not exceed 20 seconds")
    if expected_radio_frequency_hz <= 0:
        raise ValueError("expected_radio_frequency_hz must be positive")
    if not expected_radio_mode.strip():
        raise ValueError("expected_radio_mode must not be blank")
    if waveform.sample_rate_hz != FT8_SAMPLE_RATE_HZ:
        raise ValueError(f"{label} waveform must use the FT8 12000 Hz sample rate")
    if not waveform.pcm_s16le:
        raise ValueError(f"{label} waveform PCM must not be empty")
