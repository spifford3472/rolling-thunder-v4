"""Bounded, read-only diagnostics for the FT8 receive chain."""

from __future__ import annotations

import math
import re
import subprocess
import threading
from array import array
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, is_dataclass
from datetime import UTC, datetime, time, timedelta
from enum import StrEnum
from pathlib import Path
from sys import byteorder
from typing import TYPE_CHECKING, Any, cast
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from rolling_thunder.gps import GPSUTCObservation


class FT8AudioQuality(StrEnum):
    """Coarse operator-facing PCM quality classification."""

    SILENCE = "silence"
    VERY_LOW = "very_low"
    HEALTHY = "healthy"
    CLIPPING = "clipping"


@dataclass(frozen=True, slots=True)
class FT8AudioDiagnostics:
    """Level summary for one exact decoder PCM period."""

    sample_count: int
    peak_dbfs: float | None
    rms_dbfs: float | None
    clipped_samples: int
    quality: FT8AudioQuality
    boundary_lateness_ms: float = 0.0


class FT8ClockQuality(StrEnum):
    """Trust state of wall UTC used for FT8 slicing."""

    TRUSTED = "trusted"
    UNVERIFIED = "unverified"
    DEGRADED = "degraded"


@dataclass(frozen=True, slots=True)
class FT8ClockDiagnostics:
    """Read-only readiness of the UTC clock used to slice FT8 periods."""

    quality: FT8ClockQuality
    source: str | None = None
    offset_seconds: float | None = None
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class NTPClockStatus:
    """Bounded read-only observation of the host's primary NTP authority."""

    synchronized: bool
    source: str | None = None
    stratum: int | None = None
    offset_seconds: float | None = None
    detail: str | None = None


CommandRunner = Callable[[Sequence[str], float], subprocess.CompletedProcess[str]]


def _run_command(
    command: Sequence[str],
    timeout_s: float,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )


class ChronyNTPClockProbe:
    """Query chrony readiness without changing services or clock configuration."""

    def __init__(
        self,
        executable: Path = Path("/usr/bin/chronyc"),
        *,
        timeout_s: float = 2.0,
        runner: CommandRunner = _run_command,
    ) -> None:
        if not executable.is_absolute():
            raise ValueError("chronyc executable path must be absolute")
        if timeout_s <= 0:
            raise ValueError("chronyc timeout must be positive")
        self._executable = executable
        self._timeout_s = timeout_s
        self._runner = runner

    def __call__(self) -> NTPClockStatus:
        try:
            completed = self._runner(
                (str(self._executable), "tracking"),
                self._timeout_s,
            )
        except (OSError, subprocess.SubprocessError) as error:
            return NTPClockStatus(
                synchronized=False,
                detail=f"chrony readiness query failed: {error}",
            )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()
            return NTPClockStatus(
                synchronized=False,
                detail=(
                    f"chrony readiness query exited {completed.returncode}"
                    + (f": {detail}" if detail else "")
                ),
            )

        fields: dict[str, str] = {}
        for line in completed.stdout.splitlines():
            label, separator, value = line.partition(":")
            if separator:
                fields[label.strip().lower()] = value.strip()
        source = fields.get("reference id")
        leap = fields.get("leap status", "")
        stratum = _first_int(fields.get("stratum"))
        offset = _first_float(fields.get("system time"))
        synchronized = (
            leap.casefold() == "normal"
            and stratum is not None
            and 1 <= stratum <= 15
            and source not in {None, "00000000", "0.0.0.0"}
        )
        if not synchronized:
            return NTPClockStatus(
                synchronized=False,
                source=source,
                stratum=stratum,
                offset_seconds=offset,
                detail=(
                    "chrony is not synchronized "
                    f"(source={source or 'none'}, stratum={stratum}, leap={leap or 'unknown'})"
                ),
            )
        return NTPClockStatus(
            synchronized=True,
            source=source,
            stratum=stratum,
            offset_seconds=offset,
            detail=f"chrony synchronized to {source} at stratum {stratum}",
        )


@dataclass(frozen=True, slots=True)
class FT8DiagnosticSessionState:
    """Bounded aggregate counts for one morning same-PCM comparison."""

    active: bool
    started_at: datetime
    ends_at: datetime
    periods_compared: int = 0
    primary_all_decodes: int = 0
    primary_cq_decodes: int = 0
    comparison_all_decodes: int = 0
    comparison_cq_decodes: int = 0
    comparison_errors: int = 0


class FT8MorningDiagnosticSession:
    """Bound a diagnostic run to the next configured New York morning cutoff."""

    _EVENING_START = time(18, 0)

    def __init__(
        self,
        *,
        now_utc: Callable[[], datetime],
        end_local: time,
        timezone: str = "America/New_York",
    ) -> None:
        if end_local.tzinfo is not None:
            raise ValueError("diagnostic end_local must not include timezone information")
        observed_now = now_utc()
        if observed_now.tzinfo is None or observed_now.utcoffset() is None:
            raise ValueError("diagnostic session clock must be timezone-aware")
        started_at = observed_now.astimezone(UTC)
        local_zone = ZoneInfo(timezone)
        local_started = started_at.astimezone(local_zone)
        local_end = datetime.combine(
            local_started.date(),
            end_local,
            tzinfo=local_zone,
        )
        if local_started.timetz().replace(tzinfo=None) >= self._EVENING_START:
            local_end += timedelta(days=1)
        self._now_utc = now_utc
        self._lock = threading.Lock()
        self._state = FT8DiagnosticSessionState(
            active=started_at < local_end.astimezone(UTC),
            started_at=started_at,
            ends_at=local_end.astimezone(UTC),
        )

    @property
    def latest_state(self) -> FT8DiagnosticSessionState:
        with self._lock:
            return self._latest_state_locked()

    def _latest_state_locked(self) -> FT8DiagnosticSessionState:
        state = self._state
        if state.active and self._now_utc().astimezone(UTC) >= state.ends_at:
            self._state = FT8DiagnosticSessionState(
                active=False,
                started_at=state.started_at,
                ends_at=state.ends_at,
                periods_compared=state.periods_compared,
                primary_all_decodes=state.primary_all_decodes,
                primary_cq_decodes=state.primary_cq_decodes,
                comparison_all_decodes=state.comparison_all_decodes,
                comparison_cq_decodes=state.comparison_cq_decodes,
                comparison_errors=state.comparison_errors,
            )
        return self._state

    @property
    def is_active(self) -> bool:
        return self.latest_state.active

    def record(
        self,
        primary: object,
        comparison: object | None,
    ) -> FT8DiagnosticSessionState:
        """Record decoder diagnostics without importing the decoder module."""
        with self._lock:
            state = self._latest_state_locked()
            if not state.active or comparison is None:
                return state
            primary_all = _diagnostic_count(primary, "parsed_decode_count")
            primary_cq = _diagnostic_count(primary, "cq_decode_count")
            comparison_all = _diagnostic_count(comparison, "parsed_decode_count")
            comparison_cq = _diagnostic_count(comparison, "cq_decode_count")
            comparison_error = getattr(comparison, "error", None)
            self._state = FT8DiagnosticSessionState(
                active=True,
                started_at=state.started_at,
                ends_at=state.ends_at,
                periods_compared=state.periods_compared + 1,
                primary_all_decodes=state.primary_all_decodes + primary_all,
                primary_cq_decodes=state.primary_cq_decodes + primary_cq,
                comparison_all_decodes=(
                    state.comparison_all_decodes + comparison_all
                ),
                comparison_cq_decodes=(
                    state.comparison_cq_decodes + comparison_cq
                ),
                comparison_errors=(
                    state.comparison_errors + int(comparison_error is not None)
                ),
            )
            return self._state


def analyze_ft8_pcm(
    pcm_s16le: bytes,
    *,
    boundary_lateness_ms: float = 0.0,
) -> FT8AudioDiagnostics:
    """Measure one mono S16LE buffer without retaining or copying it indefinitely."""
    if not pcm_s16le or len(pcm_s16le) % 2:
        raise ValueError("FT8 PCM must contain complete signed 16-bit samples")
    if boundary_lateness_ms < 0:
        raise ValueError("boundary_lateness_ms must not be negative")

    samples = array("h")
    samples.frombytes(pcm_s16le)
    if byteorder != "little":
        samples.byteswap()

    sample_count = len(samples)
    peak = max(abs(value) for value in samples)
    clipped = sum(1 for value in samples if value in {-32768, 32767})
    mean_square = sum(value * value for value in samples) / sample_count
    rms = math.sqrt(mean_square)
    peak_dbfs = _dbfs(peak)
    rms_dbfs = _dbfs(rms)

    if peak == 0:
        quality = FT8AudioQuality.SILENCE
    elif clipped > 0:
        quality = FT8AudioQuality.CLIPPING
    elif rms_dbfs is not None and rms_dbfs < -50.0:
        quality = FT8AudioQuality.VERY_LOW
    else:
        quality = FT8AudioQuality.HEALTHY

    return FT8AudioDiagnostics(
        sample_count=sample_count,
        peak_dbfs=peak_dbfs,
        rms_dbfs=rms_dbfs,
        clipped_samples=clipped,
        quality=quality,
        boundary_lateness_ms=boundary_lateness_ms,
    )


def assess_ft8_clock(
    *,
    system_utc: datetime,
    monotonic_seconds: float,
    gps_utc: GPSUTCObservation | None,
    ntp: NTPClockStatus | None = None,
    maximum_offset_seconds: float = 1.0,
) -> FT8ClockDiagnostics:
    """Assess NTP-primary FT8 UTC readiness with independent GPS fallback."""
    if system_utc.tzinfo is None or system_utc.utcoffset() is None:
        raise ValueError("system_utc must be timezone-aware")
    if maximum_offset_seconds <= 0:
        raise ValueError("maximum_offset_seconds must be positive")
    gps_offset = _gps_offset(
        system_utc=system_utc,
        monotonic_seconds=monotonic_seconds,
        gps_utc=gps_utc,
    )
    if ntp is not None and ntp.synchronized:
        if (
            ntp.offset_seconds is not None
            and abs(ntp.offset_seconds) > maximum_offset_seconds
        ):
            return FT8ClockDiagnostics(
                quality=FT8ClockQuality.DEGRADED,
                source="ntp",
                offset_seconds=ntp.offset_seconds,
                detail=(
                    f"chrony reports a {ntp.offset_seconds:+.3f}s system offset; "
                    "FT8 wall-clock alignment is not credible"
                ),
            )
        if gps_offset is not None and abs(gps_offset) > maximum_offset_seconds:
            return FT8ClockDiagnostics(
                quality=FT8ClockQuality.DEGRADED,
                source="ntp+gps",
                offset_seconds=gps_offset,
                detail=(
                    f"NTP reports synchronized but trusted GPS differs by "
                    f"{gps_offset:+.3f}s; FT8 timing sources disagree"
                ),
            )
        return FT8ClockDiagnostics(
            quality=FT8ClockQuality.TRUSTED,
            source="ntp",
            offset_seconds=ntp.offset_seconds,
            detail=ntp.detail or "system UTC is synchronized by NTP",
        )

    if gps_offset is None:
        ntp_detail = None if ntp is None else ntp.detail
        return FT8ClockDiagnostics(
            quality=FT8ClockQuality.UNVERIFIED,
            detail=(
                "NTP is not ready and trusted GPS UTC is unavailable; "
                "FT8 wall-clock alignment is unverified"
                + (f" ({ntp_detail})" if ntp_detail else "")
            ),
        )
    if abs(gps_offset) > maximum_offset_seconds:
        return FT8ClockDiagnostics(
            quality=FT8ClockQuality.DEGRADED,
            source="gps_fallback",
            offset_seconds=gps_offset,
            detail=(
                f"NTP is not ready and system UTC differs from trusted GPS UTC "
                f"by {gps_offset:+.3f}s; "
                "FT8 decode alignment is not credible"
            ),
        )
    return FT8ClockDiagnostics(
        quality=FT8ClockQuality.TRUSTED,
        source="gps_fallback",
        offset_seconds=gps_offset,
        detail=f"NTP is not ready; system UTC verified against GPS ({gps_offset:+.3f}s)",
    )


def diagnostic_json_value(value: object) -> object:
    """Convert nested immutable diagnostic values into JSON-safe data."""
    if is_dataclass(value) and not isinstance(value, type):
        return diagnostic_json_value(asdict(cast(Any, value)))
    if isinstance(value, dict):
        return {str(key): diagnostic_json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [diagnostic_json_value(item) for item in value]
    if isinstance(value, (StrEnum, Path)):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    return value


def _dbfs(amplitude: float) -> float | None:
    if amplitude <= 0:
        return None
    return 20.0 * math.log10(amplitude / 32768.0)


def _gps_offset(
    *,
    system_utc: datetime,
    monotonic_seconds: float,
    gps_utc: GPSUTCObservation | None,
) -> float | None:
    if gps_utc is None or not gps_utc.trusted or gps_utc.value is None:
        return None
    gps_value = gps_utc.value
    if gps_utc.received_monotonic_s is not None:
        age = max(0.0, monotonic_seconds - gps_utc.received_monotonic_s)
        gps_value += timedelta(seconds=age)
    return (system_utc.astimezone(UTC) - gps_value).total_seconds()


def _first_int(value: str | None) -> int | None:
    if value is None:
        return None
    match = re.search(r"[+-]?\d+", value)
    return None if match is None else int(match.group())


def _first_float(value: str | None) -> float | None:
    if value is None:
        return None
    match = re.search(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", value)
    return None if match is None else float(match.group())


def _diagnostic_count(value: object, attribute: str) -> int:
    count = getattr(value, attribute, 0)
    return count if isinstance(count, int) and count >= 0 else 0
