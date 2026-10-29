"""Bounded session-aware dispatch without changing the legacy gate."""

from pathlib import Path

import pytest

from rolling_thunder.config import PhysicalControlsConfig
from rolling_thunder.control_recovery_gate import RecoveryControlEventGate
from rolling_thunder.control_source_factory import build_control_gate, build_control_source
from rolling_thunder.physical_controls import ControlEventGate, ControlInputEvent, MockControlSource
from rolling_thunder.recovering_control_source import RecoveringControlSource

N = "a" * 32


def event(nonce: str, seq: int, input_id: str = "voice-button") -> ControlInputEvent:
    return ControlInputEvent(input_id, f"{nonce}:{seq}", 0)


def test_current_session_and_watermark_reject_late_duplicate_and_unknown_input() -> None:
    current = [N]
    now = [1.0]
    gate = RecoveryControlEventGate(
        frozenset({"voice-button"}), lambda: current[0], 0.25, clock=lambda: now[0]
    )
    assert gate.accept(event(N, 1))
    assert not gate.accept(event(N, 1))
    assert not gate.accept(event(N, 2))
    now[0] = 2
    assert not gate.accept(event(N, 2))  # A suppressed sequence is never replayed.
    assert gate.accept(event(N, 3))
    assert not gate.accept(event(N, 4, "unknown"))
    current[0] = "b" * 32
    now[0] = 3
    assert not gate.accept(event(N, 99))
    assert gate.accept(event(current[0], 1))
    current[0] = None
    assert not gate.accept(event("b" * 32, 2))


def test_many_sessions_keep_only_current_watermark_and_known_input_repeat_times() -> None:
    current = [N]
    now = [0.0]
    gate = RecoveryControlEventGate(
        frozenset({"voice-button"}), lambda: current[0], 0, clock=lambda: now[0]
    )
    for i in range(1, 20_001):
        current[0] = f"{i:032x}"
        now[0] = i
        assert gate.accept(event(current[0], 1))
    assert all(not isinstance(v, (set, list)) for v in vars(gate).values())
    assert all(len(v) <= 1 for v in vars(gate).values() if isinstance(v, dict))


@pytest.mark.parametrize(
    "event_id", ["bad", f"{N}:0", f"{N}:01", f"{N}:-1", f"{N}:18446744073709551616"]
)
def test_malformed_ids_cannot_bypass_source_validation(event_id: str) -> None:
    gate = RecoveryControlEventGate(frozenset({"voice-button"}), lambda: N, 0)
    assert not gate.accept(ControlInputEvent("voice-button", event_id, 0))


def test_explicit_v2_factory_is_inert_and_legacy_gate_unchanged() -> None:
    config = PhysicalControlsConfig(
        enabled=True,
        transport="serial_v2",
        device=Path("/dev/fake"),
        mappings={"voice-button": "voice"},
    )
    source = build_control_source(config)
    assert isinstance(source, RecoveringControlSource)
    assert not source.snapshot.worker_running
    assert isinstance(build_control_gate(config, source), RecoveryControlEventGate)
    assert not build_control_gate(config, source).accept(event(N, 1))
    assert isinstance(build_control_gate(config, MockControlSource()), ControlEventGate)
    with pytest.raises(ValueError):
        PhysicalControlsConfig(enabled=True, transport="serial_v2")
