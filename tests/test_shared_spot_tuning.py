"""Tests for background shared-spot receive tuning."""

from __future__ import annotations

from datetime import UTC, datetime
from threading import Event, get_ident
from time import monotonic

from rolling_thunder.domain import (
    Frequency,
    RadioConnectionState,
    RadioMode,
    RadioState,
)
from rolling_thunder.radio import RadioBand, RadioConnectionError
from rolling_thunder.receive_tuning import ReceiveTuneOutcome
from rolling_thunder.shared_spot_tuning import (
    SharedSpotTuneController,
    SharedSpotTuneState,
)
from rolling_thunder.spot_domain import DxSpotIdentity
from rolling_thunder.spot_selection import StagedSpotAction


def action() -> StagedSpotAction:
    """Return one immutable shared DX receive target."""
    frequency = Frequency(hz=14_025_000)
    return StagedSpotAction(
        identity=DxSpotIdentity(
            callsign="K1DX",
            frequency=frequency,
        ),
        callsign="K1DX",
        frequency=frequency,
        mode=RadioMode.CW,
    )


def outcome() -> ReceiveTuneOutcome:
    """Return one successful verified receive-tune outcome."""
    return ReceiveTuneOutcome(
        state=RadioState(
            connection_state=RadioConnectionState.CONNECTED,
            frequency=Frequency(hz=14_025_000),
            mode=RadioMode.CW,
            updated_at=datetime(2026, 8, 8, 3, 30, tzinfo=UTC),
        ),
        target_band=RadioBand.BAND_20M,
        band_changed=False,
    )


def wait_until_complete(
    controller: SharedSpotTuneController,
    *,
    timeout_s: float = 1.0,
) -> None:
    """Wait only for a deterministic test worker to publish completion."""
    deadline = monotonic() + timeout_s
    while controller.status.tuning:
        if monotonic() >= deadline:
            raise AssertionError("background tune did not complete")

    assert not controller.status.tuning


class BlockingTuner:
    """Record thread identity and block until the test releases tuning."""

    def __init__(self) -> None:
        self.started = Event()
        self.release = Event()
        self.thread_id: int | None = None
        self.calls: list[tuple[Frequency, RadioMode]] = []

    def tune(
        self,
        frequency: Frequency,
        mode: RadioMode,
    ) -> ReceiveTuneOutcome:
        self.thread_id = get_ident()
        self.calls.append((frequency, mode))
        self.started.set()
        assert self.release.wait(timeout=1.0)
        return outcome()


class FailingTuner:
    """Raise one typed radio failure from the worker thread."""

    def tune(
        self,
        frequency: Frequency,
        mode: RadioMode,
    ) -> ReceiveTuneOutcome:
        raise RadioConnectionError("radio unavailable")


def test_start_tune_runs_off_calling_thread_and_rejects_concurrent_work() -> None:
    tuner = BlockingTuner()
    controller = SharedSpotTuneController(tuner)
    staged = action()
    caller_thread = get_ident()

    assert controller.start_tune(staged) is True
    assert tuner.started.wait(timeout=1.0)

    active = controller.status
    assert active.state is SharedSpotTuneState.TUNING
    assert active.action == staged
    assert tuner.thread_id is not None
    assert tuner.thread_id != caller_thread

    assert controller.start_tune(staged) is False
    assert len(tuner.calls) == 1

    tuner.release.set()
    wait_until_complete(controller)

    completed = controller.status
    assert completed.state is SharedSpotTuneState.SUCCEEDED
    assert completed.action == staged
    assert completed.outcome == outcome()
    assert completed.error is None
    assert tuner.calls == [(staged.frequency, staged.mode)]


def test_clear_result_cannot_interrupt_active_tuning() -> None:
    tuner = BlockingTuner()
    controller = SharedSpotTuneController(tuner)
    staged = action()

    assert controller.start_tune(staged) is True
    assert tuner.started.wait(timeout=1.0)

    controller.clear_result()

    assert controller.status.state is SharedSpotTuneState.TUNING
    assert controller.status.action == staged

    tuner.release.set()
    wait_until_complete(controller)

    assert controller.status.state is SharedSpotTuneState.SUCCEEDED

    controller.clear_result()

    assert controller.status.state is SharedSpotTuneState.IDLE
    assert controller.status.action is None
    assert controller.status.outcome is None
    assert controller.status.error is None


def test_radio_failure_is_published_without_escaping_worker() -> None:
    controller = SharedSpotTuneController(FailingTuner())
    staged = action()

    assert controller.start_tune(staged) is True
    wait_until_complete(controller)

    failed = controller.status
    assert failed.state is SharedSpotTuneState.FAILED
    assert failed.action == staged
    assert failed.outcome is None
    assert failed.error == "radio unavailable"


def test_start_tune_requires_staged_spot_action() -> None:
    controller = SharedSpotTuneController(FailingTuner())

    try:
        controller.start_tune(object())  # type: ignore[arg-type]
    except TypeError as error:
        assert str(error) == "action must be a StagedSpotAction"
    else:
        raise AssertionError("Expected TypeError")
