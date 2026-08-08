"""Least-privilege adapter for the installed chrony clock helper."""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

from rolling_thunder.clock_sync import ClockSetError

DEFAULT_CLOCK_HELPER_PATH = Path("/usr/local/sbin/rolling-thunder-chrony-settime")
_MIN_EPOCH = 1_577_836_800  # 2020-01-01T00:00:00Z
_MAX_EPOCH = 4_102_444_800  # 2100-01-01T00:00:00Z

CommandRunner = Callable[[Sequence[str], float], None]


def _run_command(command: Sequence[str], timeout_s: float) -> None:
    try:
        completed = subprocess.run(
            list(command),
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise ClockSetError(f"Clock helper execution failed: {error}") from error

    if completed.returncode == 0:
        return

    detail = (completed.stderr or completed.stdout).strip()
    if not detail:
        detail = f"exit status {completed.returncode}"
    raise ClockSetError(f"Clock helper failed: {detail}")


class ChronyHelperClockSetter:
    """Invoke one fixed privileged helper with a validated UTC epoch."""

    def __init__(
        self,
        helper_path: Path = DEFAULT_CLOCK_HELPER_PATH,
        *,
        sudo_path: Path = Path("/usr/bin/sudo"),
        timeout_s: float = 10.0,
        runner: CommandRunner = _run_command,
    ) -> None:
        if not helper_path.is_absolute():
            raise ValueError("Clock helper path must be absolute.")
        if not sudo_path.is_absolute():
            raise ValueError("sudo path must be absolute.")
        if timeout_s <= 0:
            raise ValueError("Clock helper timeout must be positive.")

        self._helper_path = helper_path
        self._sudo_path = sudo_path
        self._timeout_s = timeout_s
        self._runner = runner

    def set_utc(self, value: datetime) -> None:
        """Set UTC through sudo -n and the fixed root-owned chrony helper."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ClockSetError("Clock target must include timezone information.")

        normalized = value.astimezone(UTC)
        epoch = int(normalized.timestamp())
        if epoch < _MIN_EPOCH or epoch >= _MAX_EPOCH:
            raise ClockSetError("Clock target is outside the permitted 2020-2100 range.")

        self._runner(
            (
                str(self._sudo_path),
                "-n",
                str(self._helper_path),
                str(epoch),
            ),
            self._timeout_s,
        )
