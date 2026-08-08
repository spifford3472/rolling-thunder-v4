"""Tests for the narrow chrony helper clock-setting adapter."""

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest

from rolling_thunder.chrony_clock import ChronyHelperClockSetter
from rolling_thunder.clock_sync import ClockSetError


class RecordingRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, ...], float]] = []
        self.error: ClockSetError | None = None

    def __call__(self, command: Sequence[str], timeout_s: float) -> None:
        if self.error is not None:
            raise self.error
        self.calls.append((tuple(command), timeout_s))


def test_setter_invokes_only_fixed_sudo_helper_with_utc_epoch() -> None:
    runner = RecordingRunner()
    setter = ChronyHelperClockSetter(runner=runner)

    setter.set_utc(datetime(2026, 8, 8, 21, 23, 12, 900_000, tzinfo=UTC))

    assert runner.calls == [
        (
            (
                "/usr/bin/sudo",
                "-n",
                "/usr/local/sbin/rolling-thunder-chrony-settime",
                "1786224192",
            ),
            10.0,
        )
    ]


def test_setter_normalizes_aware_non_utc_timestamp() -> None:
    runner = RecordingRunner()
    setter = ChronyHelperClockSetter(runner=runner)
    eastern = datetime.fromisoformat("2026-08-08T17:23:12-04:00")

    setter.set_utc(eastern)

    assert runner.calls[0][0][-1] == "1786224192"


def test_setter_rejects_naive_timestamp_before_runner() -> None:
    runner = RecordingRunner()
    setter = ChronyHelperClockSetter(runner=runner)
    naive = datetime.fromisoformat("2026-08-08T21:23:12")

    with pytest.raises(ClockSetError, match="timezone"):
        setter.set_utc(naive)

    assert runner.calls == []


@pytest.mark.parametrize(
    "value",
    [
        datetime(2019, 12, 31, 23, 59, 59, tzinfo=UTC),
        datetime(2100, 1, 1, 0, 0, 0, tzinfo=UTC),
    ],
)
def test_setter_rejects_timestamp_outside_helper_range(value: datetime) -> None:
    runner = RecordingRunner()
    setter = ChronyHelperClockSetter(runner=runner)

    with pytest.raises(ClockSetError, match="2020-2100"):
        setter.set_utc(value)

    assert runner.calls == []


def test_setter_propagates_typed_helper_failure() -> None:
    runner = RecordingRunner()
    runner.error = ClockSetError("Clock helper failed: authorization denied")
    setter = ChronyHelperClockSetter(runner=runner)

    with pytest.raises(ClockSetError, match="authorization denied"):
        setter.set_utc(datetime(2026, 8, 8, 21, 23, 12, tzinfo=UTC))


def test_setter_requires_absolute_paths_and_positive_timeout() -> None:
    with pytest.raises(ValueError, match="helper path"):
        ChronyHelperClockSetter(helper_path=Path("relative-helper"))
    with pytest.raises(ValueError, match="sudo path"):
        ChronyHelperClockSetter(sudo_path=Path("sudo"))
    with pytest.raises(ValueError, match="timeout"):
        ChronyHelperClockSetter(timeout_s=0.0)
