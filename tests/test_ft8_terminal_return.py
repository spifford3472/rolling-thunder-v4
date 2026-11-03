"""Regression coverage for FT8 terminal auto-return timing."""

import pytest

from rolling_thunder.ft8.domain import FT8QsoState
from rolling_thunder.ft8.terminal_return import FT8TerminalReturnTimer


@pytest.mark.parametrize(
    "terminal",
    [
        FT8QsoState.COMPLETED,
        FT8QsoState.ABORTED,
        FT8QsoState.RETRY_EXHAUSTED,
        FT8QsoState.ERROR,
    ],
)
def test_every_terminal_outcome_returns_once_after_three_seconds(
    terminal: FT8QsoState,
) -> None:
    timer = FT8TerminalReturnTimer(3.0)

    assert not timer.poll(terminal, 10.0)
    assert not timer.poll(terminal, 12.99)
    assert timer.poll(terminal, 13.0)
    assert not timer.poll(terminal, 13.1)


def test_new_qso_state_resets_terminal_timer() -> None:
    timer = FT8TerminalReturnTimer(3.0)
    assert not timer.poll(FT8QsoState.COMPLETED, 1.0)
    assert not timer.poll(FT8QsoState.WAIT_REPORT, 2.0)
    assert not timer.poll(FT8QsoState.ERROR, 3.0)
    assert not timer.poll(FT8QsoState.ERROR, 5.99)
    assert timer.poll(FT8QsoState.ERROR, 6.0)
