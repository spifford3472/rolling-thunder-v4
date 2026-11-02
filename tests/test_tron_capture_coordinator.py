"""Cooperative cancellation and callsign priority without real audio."""

from threading import Event

from rolling_thunder.tron_capture_coordinator import TronCaptureCoordinator


def test_callsign_preempts_tron() -> None:
    coordinator = TronCaptureCoordinator()
    started = Event()

    def capture(stop: Event) -> None:
        started.set()
        stop.wait(2)

    assert coordinator.start_tron(capture)
    assert started.wait(1)
    assert coordinator.run_callsign(lambda: True)
    assert coordinator.gate.owner == "callsign"
    assert not coordinator.start_tron(capture)
    coordinator.callsign_finished()
    assert coordinator.gate.owner is None


def test_rejected_callsign_releases_reservation() -> None:
    coordinator = TronCaptureCoordinator()
    assert not coordinator.run_callsign(lambda: False)
    assert coordinator.gate.owner is None


def test_tron_worker_failure_releases_gate() -> None:
    coordinator = TronCaptureCoordinator()
    started = Event()

    def capture(stop: Event) -> None:
        started.set()

    assert coordinator.start_tron(capture)
    assert started.wait(1)
    assert coordinator.stop_tron()
    assert coordinator.gate.owner is None
