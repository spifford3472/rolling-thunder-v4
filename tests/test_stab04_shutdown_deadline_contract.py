"""STAB-04 offline shutdown-deadline evidence, not a safety acceptance pass.

The 20-second systemd stop deadline cannot force Python callbacks to complete.
Events let tests observe the blocked phase without sleeping for 20 seconds or
opening hardware. Strict expected failures are requirements for a future fix.
"""

from threading import Event, Thread

import pytest

from rolling_thunder.ui_main import _run_cleanup_steps


@pytest.mark.xfail(
    strict=True,
    reason=(
        "STAB-04: a stuck unrelated UI close callback currently prevents "
        "the application runtime cleanup from being reached"
    ),
)
def test_runtime_close_is_reachable_while_unrelated_ui_step_is_stuck() -> None:
    """Desired shutdown guarantee: runtime is not starved by peripheral cleanup."""
    entered = Event()
    release = Event()
    reached_runtime = Event()
    finished = Event()
    errors: list[str] = []

    def blocked_peripheral() -> None:
        entered.set()
        assert release.wait(timeout=3.0)

    def shutdown() -> None:
        try:
            _run_cleanup_steps(
                (
                    ("unrelated UI", blocked_peripheral),
                    ("application runtime", reached_runtime.set),
                ),
                errors,
            )
        finally:
            finished.set()

    worker = Thread(target=shutdown, daemon=True)
    worker.start()
    try:
        assert entered.wait(timeout=1.0)
        # A bounded observation, NOT a claim that twenty seconds elapsed.
        assert reached_runtime.wait(timeout=0.05)
    finally:
        release.set()
        worker.join(timeout=3.0)

    assert not worker.is_alive()
    assert finished.is_set()
    assert errors == []


def test_stuck_ui_step_does_not_falsely_report_runtime_cleanup_complete(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Logging must distinguish a blocked step from a completed cleanup."""
    entered = Event()
    release = Event()
    reached_runtime = Event()
    finished = Event()
    errors: list[str] = []

    def blocked_peripheral() -> None:
        entered.set()
        assert release.wait(timeout=3.0)

    def shutdown() -> None:
        try:
            _run_cleanup_steps(
                (
                    ("unrelated UI", blocked_peripheral),
                    ("application runtime", reached_runtime.set),
                ),
                errors,
            )
        finally:
            finished.set()

    worker = Thread(target=shutdown, daemon=True)
    worker.start()
    try:
        assert entered.wait(timeout=1.0)
        output = capsys.readouterr().out
        assert "phase=step_start step='unrelated UI'" in output
        assert "phase=step_end step='unrelated UI'" not in output
        assert "phase=step_start step='application runtime'" not in output
        assert "phase=cleanup_end" not in output
        assert not reached_runtime.is_set()
        assert not finished.is_set()
    finally:
        release.set()
        worker.join(timeout=3.0)

    assert not worker.is_alive()
    assert reached_runtime.is_set()
    assert finished.is_set()
    assert errors == []
