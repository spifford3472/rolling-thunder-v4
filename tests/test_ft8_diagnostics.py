"""Tests for bounded FT8 receive-chain diagnostics."""

import subprocess
from collections.abc import Sequence
from datetime import UTC, datetime, time, timedelta

import pytest

from rolling_thunder.ft8.decoder import FT8DecoderDiagnostics
from rolling_thunder.ft8.diagnostics import (
    ChronyNTPClockProbe,
    FT8AudioQuality,
    FT8ClockQuality,
    FT8MorningDiagnosticSession,
    NTPClockStatus,
    analyze_ft8_pcm,
    assess_ft8_clock,
)
from rolling_thunder.gps import GPSUTCObservation, GPSUTCSource


class MutableUTC:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


def trusted_gps(value: datetime, *, received_monotonic_s: float) -> GPSUTCObservation:
    return GPSUTCObservation(
        value=value,
        source=GPSUTCSource.RMC,
        valid=True,
        fix_valid=True,
        advancing=True,
        fresh=True,
        age_s=0.1,
        received_monotonic_s=received_monotonic_s,
    )


def decoder_diagnostics(
    *,
    all_decodes: int,
    cq_decodes: int,
    error: str | None = None,
) -> FT8DecoderDiagnostics:
    return FT8DecoderDiagnostics(
        backend="test",
        runtime_seconds=0.1,
        raw_line_count=all_decodes,
        parsed_decode_count=all_decodes,
        cq_decode_count=cq_decodes,
        malformed_line_count=0,
        error=error,
    )


def test_audio_diagnostics_classify_silence_and_clipping() -> None:
    silence = analyze_ft8_pcm(b"\x00\x00" * 8, boundary_lateness_ms=12.5)
    clipping = analyze_ft8_pcm((32767).to_bytes(2, "little", signed=True) * 8)

    assert silence.quality is FT8AudioQuality.SILENCE
    assert silence.rms_dbfs is None
    assert silence.boundary_lateness_ms == 12.5
    assert clipping.quality is FT8AudioQuality.CLIPPING
    assert clipping.clipped_samples == 8


def test_chrony_probe_reports_synchronized_ntp_without_mutating_clock() -> None:
    calls: list[tuple[tuple[str, ...], float]] = []

    def runner(
        command: Sequence[str],
        timeout_s: float,
    ) -> subprocess.CompletedProcess[str]:
        calls.append((tuple(command), timeout_s))
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout=(
                "Reference ID    : C0A80101 (time.example)\n"
                "Stratum         : 3\n"
                "System time     : 0.000123 seconds slow of NTP time\n"
                "Leap status     : Normal\n"
            ),
            stderr="",
        )

    status = ChronyNTPClockProbe(runner=runner)()

    assert status.synchronized is True
    assert status.source == "C0A80101 (time.example)"
    assert status.stratum == 3
    assert status.offset_seconds == pytest.approx(0.000123)
    assert calls == [(('/usr/bin/chronyc', 'tracking'), 2.0)]


def test_clock_readiness_prefers_ntp_and_falls_back_to_trusted_gps() -> None:
    system_utc = datetime(2026, 10, 6, 5, 0, tzinfo=UTC)
    ready_ntp = NTPClockStatus(
        synchronized=True,
        source="time.example",
        stratum=3,
        offset_seconds=0.01,
    )

    ntp_result = assess_ft8_clock(
        system_utc=system_utc,
        monotonic_seconds=100.0,
        gps_utc=None,
        ntp=ready_ntp,
    )
    gps_result = assess_ft8_clock(
        system_utc=system_utc,
        monotonic_seconds=101.0,
        gps_utc=trusted_gps(
            system_utc - timedelta(seconds=1.2),
            received_monotonic_s=100.0,
        ),
        ntp=NTPClockStatus(synchronized=False),
    )

    assert ntp_result.quality is FT8ClockQuality.TRUSTED
    assert ntp_result.source == "ntp"
    assert gps_result.quality is FT8ClockQuality.TRUSTED
    assert gps_result.source == "gps_fallback"
    assert gps_result.offset_seconds == pytest.approx(0.2)


def test_clock_readiness_fails_safe_when_ntp_and_gps_disagree() -> None:
    system_utc = datetime(2026, 10, 6, 5, 0, tzinfo=UTC)
    result = assess_ft8_clock(
        system_utc=system_utc,
        monotonic_seconds=100.0,
        gps_utc=trusted_gps(
            system_utc - timedelta(seconds=2),
            received_monotonic_s=100.0,
        ),
        ntp=NTPClockStatus(synchronized=True, offset_seconds=0.001),
    )

    assert result.quality is FT8ClockQuality.DEGRADED
    assert result.source == "ntp+gps"
    assert "disagree" in (result.detail or "")


def test_morning_session_ends_at_0515_new_york_and_counts_all_vs_cq() -> None:
    clock = MutableUTC(datetime(2026, 10, 6, 5, 0, tzinfo=UTC))
    session = FT8MorningDiagnosticSession(
        now_utc=clock,
        end_local=time(5, 15),
    )

    state = session.record(
        decoder_diagnostics(all_decodes=7, cq_decodes=2),
        decoder_diagnostics(all_decodes=11, cq_decodes=4),
    )

    assert state.active is True
    assert state.ends_at == datetime(2026, 10, 6, 9, 15, tzinfo=UTC)
    assert state.periods_compared == 1
    assert state.primary_all_decodes == 7
    assert state.primary_cq_decodes == 2
    assert state.comparison_all_decodes == 11
    assert state.comparison_cq_decodes == 4

    clock.value = state.ends_at
    assert session.is_active is False
    assert session.latest_state.periods_compared == 1


def test_morning_session_started_after_cutoff_does_not_run_all_day() -> None:
    clock = MutableUTC(datetime(2026, 10, 6, 14, 0, tzinfo=UTC))
    session = FT8MorningDiagnosticSession(
        now_utc=clock,
        end_local=time(5, 15),
    )

    assert session.is_active is False
