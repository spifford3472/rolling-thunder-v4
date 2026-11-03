"""Cooperative cancellation and callsign priority without real audio."""

from threading import Event

from rolling_thunder.tron_capture_coordinator import TronCaptureCoordinator


def wait(event: Event) -> None:
    assert event.wait(1), "coordinator transition did not complete"


def test_callsign_preempts_tron_without_blocking_requester() -> None:
    coordinator = TronCaptureCoordinator()
    started = Event()
    callsign_started = Event()
    capture_exited = Event()

    def capture(stop: Event) -> None:
        started.set()
        stop.wait(2)
        capture_exited.set()

    assert coordinator.start_tron(capture)
    wait(started)
    assert coordinator.request_callsign(lambda: (callsign_started.set() or True))
    assert capture_exited.wait(1)
    wait(callsign_started)
    assert coordinator.gate.owner == "callsign"
    assert not coordinator.start_tron(capture)
    assert not coordinator.request_callsign(callsign_started.set)
    coordinator.callsign_finished()
    assert coordinator.gate.owner is None


def test_callsign_request_during_worker_startup_is_safe() -> None:
    coordinator = TronCaptureCoordinator()
    startup = Event()
    permit_startup_exit = Event()
    callsign_started = Event()

    def capture(stop: Event) -> None:
        startup.set()
        permit_startup_exit.wait(1)
        stop.wait(1)

    assert coordinator.start_tron(capture)
    wait(startup)
    assert coordinator.request_callsign(lambda: (callsign_started.set() or True))
    permit_startup_exit.set()
    wait(callsign_started)
    assert coordinator.gate.owner == "callsign"
    coordinator.callsign_finished()


def test_rejected_callsign_releases_reservation_and_resumes() -> None:
    resumed = Event()
    coordinator = TronCaptureCoordinator(on_callsign_finished=resumed.set)
    assert not coordinator.request_callsign(lambda: False)
    assert coordinator.gate.owner is None
    wait(resumed)


def test_shutdown_cancels_and_reaps_tron_worker() -> None:
    coordinator = TronCaptureCoordinator()
    started = Event()
    exited = Event()

    def capture(stop: Event) -> None:
        started.set()
        stop.wait(2)
        exited.set()

    assert coordinator.start_tron(capture)
    wait(started)
    assert coordinator.shutdown(timeout_s=1)
    wait(exited)
    assert coordinator.gate.owner is None
    assert not coordinator.start_tron(capture)


def test_callsign_capture_starts_only_after_tron_callback_returns() -> None:
    coordinator = TronCaptureCoordinator()
    started = Event()
    allow_exit = Event()
    callsign_started = Event()

    def capture(stop: Event) -> None:
        started.set()
        allow_exit.wait(1)
        stop.wait(1)

    def start_callsign() -> bool:
        assert allow_exit.is_set()
        callsign_started.set()
        return True

    assert coordinator.start_tron(capture)
    wait(started)
    assert coordinator.request_callsign(start_callsign)
    assert not callsign_started.is_set()
    allow_exit.set()
    wait(callsign_started)
