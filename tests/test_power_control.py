"""Hardware-free tests for Settings power confirmation and OS requests."""

import subprocess
from concurrent.futures import Executor, Future
from dataclasses import dataclass

import pytest

from rolling_thunder.context_navigation import ContextId
from rolling_thunder.control_dispatcher import ControlDispatcher
from rolling_thunder.control_transport_health import TransportHealthSnapshot, TransportHealthState
from rolling_thunder.physical_controls import (
    ControlAction,
    ControlActionMapper,
    ControlInputEvent,
    MockControlSource,
)
from rolling_thunder.power_control import (
    LinuxSystemctlPowerAdapter,
    PowerAction,
    PowerConfirmationController,
    PowerGuardState,
    PowerInputProof,
    SettingsPowerEventInterceptor,
)
from rolling_thunder.settings_selection import SettingId


class AcceptAll:
    def accept(self, event: ControlInputEvent) -> bool:
        return True


class RecordingCommands:
    def __init__(self) -> None:
        self.actions: list[ControlAction] = []

    def execute(self, action: ControlAction) -> bool:
        self.actions.append(action)
        return True


class ImmediateExecutor(Executor):
    def submit(self, fn, /, *args, **kwargs):  # type: ignore[no-untyped-def]
        future: Future[object] = Future()
        future.set_result(fn(*args, **kwargs))
        return future


class HoldingExecutor(Executor):
    def __init__(self) -> None:
        self.work: list[tuple[object, tuple[object, ...], dict[str, object]]] = []

    def submit(self, fn, /, *args, **kwargs):  # type: ignore[no-untyped-def]
        self.work.append((fn, args, kwargs))
        return Future()


class RejectingExecutor(Executor):
    def submit(self, fn, /, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("executor stopped")


class FakeOs:
    def __init__(self, error: Exception | None = None) -> None:
        self.actions: list[PowerAction] = []
        self.error = error

    def request(self, action: PowerAction) -> None:
        self.actions.append(action)
        if self.error is not None:
            raise self.error


@dataclass
class FakeBarrier:
    accepted: bool = True
    calls: list[float] | None = None

    def flush(self, timeout_s: float) -> bool:
        if self.calls is None:
            self.calls = []
        self.calls.append(timeout_s)
        return self.accepted


def proof(sequence: int, when: float, *, nonce: str = "a" * 32, generation: int = 1) -> PowerInputProof:
    return PowerInputProof(f"{nonce}:{sequence}", nonce, generation, when, when + 1)


def controller(*, now: list[float], os: FakeOs, barrier: FakeBarrier, guard=lambda: PowerGuardState()):
    value = PowerConfirmationController(
        os,
        barrier,
        guard,
        clock=lambda: now[0],
        executor=ImmediateExecutor(),
    )
    return value


def test_distinct_fresh_deliberate_second_press_submits_at_most_once() -> None:
    now = [1.0]
    os = FakeOs()
    value = controller(now=now, os=os, barrier=FakeBarrier())
    assert value.request_or_confirm(PowerAction.REBOOT, proof(1, 1.0))
    assert os.actions == []
    now[0] = 1.2
    assert value.request_or_confirm(PowerAction.REBOOT, proof(2, 1.2))
    assert os.actions == [PowerAction.REBOOT]
    assert value.state.pending
    assert not value.request_or_confirm(PowerAction.REBOOT, proof(3, 1.3))
    assert os.actions == [PowerAction.REBOOT]


def test_duplicate_stale_reconnected_canceled_and_expired_input_never_executes() -> None:
    now = [1.0]
    os = FakeOs()
    value = controller(now=now, os=os, barrier=FakeBarrier())
    assert value.request_or_confirm(PowerAction.SHUTDOWN, proof(1, 1.0))
    now[0] = 1.2
    assert not value.request_or_confirm(PowerAction.SHUTDOWN, proof(1, 1.0))
    assert os.actions == []
    assert value.request_or_confirm(PowerAction.SHUTDOWN, proof(2, 1.2))
    assert value.cancel()
    now[0] = 20.0
    assert not value.request_or_confirm(PowerAction.SHUTDOWN, proof(3, 1.3))
    assert os.actions == []
    now[0] = 21.0
    assert value.request_or_confirm(PowerAction.SHUTDOWN, proof(1, 21.0, nonce="b" * 32, generation=2))
    now[0] = 21.2
    assert not value.request_or_confirm(PowerAction.SHUTDOWN, proof(2, 21.2, nonce="c" * 32, generation=3))
    assert os.actions == []


def test_guard_or_preference_failure_leaves_runtime_open_and_reports_error() -> None:
    now = [1.0]
    os = FakeOs()
    value = controller(now=now, os=os, barrier=FakeBarrier(False))
    assert value.request_or_confirm(PowerAction.REBOOT, proof(1, 1.0))
    now[0] = 1.2
    assert value.request_or_confirm(PowerAction.REBOOT, proof(2, 1.2))
    assert os.actions == []
    assert value.state.last_error is not None

    blocked = controller(
        now=now,
        os=os,
        barrier=FakeBarrier(),
        guard=lambda: PowerGuardState(contact_commit_active=True),
    )
    assert not blocked.request_or_confirm(PowerAction.REBOOT, proof(3, 1.2))


def test_os_adapter_uses_only_fixed_noninteractive_vector() -> None:
    calls: list[tuple[object, dict[str, object]]] = []

    def runner(arguments, **kwargs):  # type: ignore[no-untyped-def]
        calls.append((arguments, kwargs))
        return type("Completed", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    adapter = LinuxSystemctlPowerAdapter(runner=runner)
    adapter.request(PowerAction.SHUTDOWN)
    assert calls == [
        (
            ["/usr/bin/systemctl", "--no-ask-password", "poweroff"],
            {"shell": False, "capture_output": True, "text": True, "timeout": 5.0, "check": False},
        )
    ]


def test_event_interceptor_requires_current_healthy_v2_session_and_expiry() -> None:
    now = [1.0]
    os = FakeOs()
    value = controller(now=now, os=os, barrier=FakeBarrier())
    nonce = "a" * 32
    health = TransportHealthSnapshot(TransportHealthState.HEALTHY, 7, None, 1.0, 1, None)
    snapshot = type("Snapshot", (), {"health": health, "session_nonce": nonce})()
    interceptor = SettingsPowerEventInterceptor(
        value,
        context=lambda: ContextId.SETTINGS,
        selection=lambda: SettingId.REBOOT,
        recovery_snapshot=lambda: snapshot,
        clock=lambda: now[0],
    )
    first = ControlInputEvent("b3", f"{nonce}:1", 1.0, expires_at_s=1.5)
    assert interceptor.intercept(first, ControlAction.PANEL_TERTIARY) is True
    assert os.actions == []
    now[0] = 1.2
    second = ControlInputEvent("b3", f"{nonce}:2", 1.2, expires_at_s=1.5)
    assert interceptor.intercept(second, ControlAction.PANEL_TERTIARY) is True
    assert os.actions == [PowerAction.REBOOT]

    legacy = ControlInputEvent("b3", "legacy", 1.3)
    assert interceptor.intercept(legacy, ControlAction.PANEL_TERTIARY) is False


def test_event_interceptor_cancel_consumes_b2_without_os_action() -> None:
    now = [1.0]
    os = FakeOs()
    value = controller(now=now, os=os, barrier=FakeBarrier())
    nonce = "a" * 32
    health = TransportHealthSnapshot(TransportHealthState.HEALTHY, 1, None, 1.0, 1, None)
    snapshot = type("Snapshot", (), {"health": health, "session_nonce": nonce})()
    interceptor = SettingsPowerEventInterceptor(
        value,
        context=lambda: ContextId.SETTINGS,
        selection=lambda: SettingId.SHUTDOWN,
        recovery_snapshot=lambda: snapshot,
        clock=lambda: now[0],
    )
    event = ControlInputEvent("b2", f"{nonce}:1", 1.0, expires_at_s=1.5)
    assert interceptor.intercept(event, ControlAction.PANEL_SECONDARY) is False
    assert os.actions == []


def test_power_rows_default_dispatch_movement_navigation_b1_and_press() -> None:
    now = [1.0]
    os = FakeOs()
    value = controller(now=now, os=os, barrier=FakeBarrier())
    nonce = "a" * 32
    health = TransportHealthSnapshot(TransportHealthState.HEALTHY, 1, None, 1.0, 1, None)
    snapshot = type("Snapshot", (), {"health": health, "session_nonce": nonce})()
    interceptor = SettingsPowerEventInterceptor(
        value,
        context=lambda: ContextId.SETTINGS,
        selection=lambda: SettingId.REBOOT,
        recovery_snapshot=lambda: snapshot,
    )
    commands = RecordingCommands()
    events = tuple(
        ControlInputEvent(name, f"{nonce}:{index}", 1.0, expires_at_s=2.0)
        for index, name in enumerate(("move", "next", "b1", "press"), 1)
    )
    source = MockControlSource(events)
    dispatcher = ControlDispatcher(
        source,
        ControlActionMapper(
            {
                "move": ControlAction.MOVE_NEXT,
                "next": ControlAction.NEXT_CONTEXT,
                "b1": ControlAction.PANEL_PRIMARY,
                "press": ControlAction.ACTIVATE_SELECTION,
            }
        ),
        AcceptAll(),
        commands,
        event_interceptor=interceptor,
    )

    result = dispatcher.dispatch_available()

    assert result.accepted == 4
    assert commands.actions == [
        ControlAction.MOVE_NEXT,
        ControlAction.NEXT_CONTEXT,
        ControlAction.PANEL_PRIMARY,
        ControlAction.ACTIVATE_SELECTION,
    ]
    assert os.actions == []


@pytest.mark.parametrize(
    "guard",
    [
        PowerGuardState(ft8_context_attached=True),
        PowerGuardState(ft8_busy=True),
        PowerGuardState(hardware_transmitting=True),
        PowerGuardState(ptt_alarm_or_inhibited=True),
        PowerGuardState(radio_transmitting=None),
        PowerGuardState(radio_transmitting=True),
        PowerGuardState(contact_commit_active=True),
        PowerGuardState(dmr_commit_active=True),
    ],
)
def test_every_published_guard_fact_blocks_power(guard: PowerGuardState) -> None:
    value = controller(now=[1.0], os=FakeOs(), barrier=FakeBarrier(), guard=lambda: guard)
    assert not value.request_or_confirm(PowerAction.REBOOT, proof(1, 1.0))


def test_guard_change_after_preference_barrier_prevents_os_request() -> None:
    blocked = [False]

    class ChangingBarrier:
        def flush(self, _timeout_s: float) -> bool:
            blocked[0] = True
            return True

    now = [1.0]
    os = FakeOs()
    value = controller(
        now=now,
        os=os,
        barrier=ChangingBarrier(),  # type: ignore[arg-type]
        guard=lambda: PowerGuardState(contact_commit_active=blocked[0]),
    )
    assert value.request_or_confirm(PowerAction.REBOOT, proof(1, 1.0))
    now[0] = 1.2
    assert value.request_or_confirm(PowerAction.REBOOT, proof(2, 1.2))
    assert os.actions == []
    assert "guard changed" in (value.state.last_error or "")


@pytest.mark.parametrize(
    "bad_proof",
    [
        PowerInputProof("nonce:1", "nonce", True, 1.0, 2.0),
        PowerInputProof("nonce:1", "nonce", 1, float("nan"), 2.0),
        PowerInputProof("nonce:1", "nonce", 1, float("inf"), 2.0),
        PowerInputProof("nonce:1", "nonce", 1, 1.1, 2.0),
        PowerInputProof("nonce:1", "nonce", 1, 0.0, 1.0),
    ],
)
def test_invalid_stale_future_and_nonfinite_proofs_fail_closed(
    bad_proof: PowerInputProof,
) -> None:
    value = controller(now=[1.0], os=FakeOs(), barrier=FakeBarrier())
    assert not value.request_or_confirm(PowerAction.REBOOT, bad_proof)


def test_unhealthy_session_cancels_even_when_identity_remains_populated() -> None:
    value = controller(now=[1.0], os=FakeOs(), barrier=FakeBarrier())
    assert value.request_or_confirm(PowerAction.REBOOT, proof(1, 1.0))
    value.retain_session("a" * 32, 1, TransportHealthState.STALE)
    assert value.state.action is None
    assert not value.state.available


def test_slow_dispatch_does_not_turn_close_together_events_into_confirmation() -> None:
    now = [1.0]
    os = FakeOs()
    value = controller(now=now, os=os, barrier=FakeBarrier())
    assert value.request_or_confirm(PowerAction.REBOOT, proof(1, 0.95))
    now[0] = 1.5
    assert not value.request_or_confirm(PowerAction.REBOOT, proof(2, 1.0))
    assert os.actions == []


def test_adapter_failure_timeout_and_malformed_action_are_deterministic() -> None:
    def failed_runner(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        return type("Completed", (), {"returncode": 1, "stdout": "", "stderr": "denied"})()

    with pytest.raises(RuntimeError, match="denied"):
        LinuxSystemctlPowerAdapter(runner=failed_runner).request(PowerAction.REBOOT)

    def timeout_runner(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise subprocess.TimeoutExpired("systemctl", 5.0)

    with pytest.raises(subprocess.TimeoutExpired):
        LinuxSystemctlPowerAdapter(runner=timeout_runner).request(PowerAction.REBOOT)
    with pytest.raises(TypeError):
        LinuxSystemctlPowerAdapter(runner=failed_runner).request("reboot")  # type: ignore[arg-type]


def test_queued_submission_is_at_most_once_and_submit_failure_clears_pending() -> None:
    now = [1.0]
    os = FakeOs()
    holding = HoldingExecutor()
    value = PowerConfirmationController(
        os,
        FakeBarrier(),
        lambda: PowerGuardState(),
        clock=lambda: now[0],
        executor=holding,
    )
    assert value.request_or_confirm(PowerAction.REBOOT, proof(1, 1.0))
    now[0] = 1.2
    assert value.request_or_confirm(PowerAction.REBOOT, proof(2, 1.2))
    assert not value.request_or_confirm(PowerAction.REBOOT, proof(3, 1.4))
    assert len(holding.work) == 1
    assert os.actions == []

    rejected = PowerConfirmationController(
        os,
        FakeBarrier(),
        lambda: PowerGuardState(),
        clock=lambda: now[0],
        executor=RejectingExecutor(),
    )
    assert rejected.request_or_confirm(PowerAction.SHUTDOWN, proof(4, 1.2))
    now[0] = 1.4
    assert not rejected.request_or_confirm(PowerAction.SHUTDOWN, proof(5, 1.4))
    assert not rejected.state.pending
    assert "worker unavailable" in (rejected.state.last_error or "")


def test_stopped_owner_refuses_a_queued_unsent_request() -> None:
    queued = []

    class HoldingExecutor(Executor):
        def submit(self, fn, /, *args, **kwargs):  # type: ignore[no-untyped-def]
            queued.append(lambda: fn(*args, **kwargs))
            return Future()

    now = [1.0]
    os = FakeOs()
    value = PowerConfirmationController(
        os, FakeBarrier(), lambda: PowerGuardState(),
        clock=lambda: now[0], executor=HoldingExecutor(),
    )
    assert value.request_or_confirm(PowerAction.REBOOT, proof(1, 1.0))
    now[0] = 1.2
    assert value.request_or_confirm(PowerAction.REBOOT, proof(2, 1.2))
    value.stop()
    queued[0]()
    assert os.actions == []
    assert "cleanup" in (value.state.last_error or "")
    assert not value.request_or_confirm(PowerAction.REBOOT, proof(3, 1.2))


def test_busy_guard_rejection_publishes_a_visible_reason() -> None:
    value = PowerConfirmationController(
        FakeOs(), FakeBarrier(),
        lambda: PowerGuardState(contact_commit_active=True),
        clock=lambda: 1.0, executor=ImmediateExecutor(),
    )
    assert not value.request_or_confirm(PowerAction.REBOOT, proof(1, 1.0))
    assert "blocked" in (value.state.last_error or "")


@pytest.mark.parametrize("connection,expected", [
    ("disconnected", False), ("connected", False),
    ("connecting", None), ("error", None),
])
def test_radio_off_allows_shutdown_only_with_other_local_owners_idle(connection, expected):
    from rolling_thunder.domain import RadioState
    from rolling_thunder.power_control import radio_power_guard

    state = RadioState(connection_state=connection)
    assert radio_power_guard(state) is expected
    guard = PowerGuardState(radio_transmitting=radio_power_guard(state))
    assert guard.safe is (expected is False)
    assert not PowerGuardState(
        radio_transmitting=radio_power_guard(state), hardware_transmitting=True,
    ).safe
    assert not PowerGuardState(
        radio_transmitting=radio_power_guard(state), ft8_busy=True,
    ).safe
    assert not PowerGuardState(
        radio_transmitting=radio_power_guard(state), contact_commit_active=True,
    ).safe


def test_disconnection_never_clears_retained_transmit_evidence():
    from rolling_thunder.domain import RadioState
    from rolling_thunder.power_control import radio_power_guard

    state = RadioState(connection_state="disconnected", transmitting=True)
    assert radio_power_guard(state) is True
    assert not PowerGuardState(radio_transmitting=radio_power_guard(state)).safe
