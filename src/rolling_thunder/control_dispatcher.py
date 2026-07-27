"""Dispatch validated physical-control events through shared operator commands."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from rolling_thunder.physical_controls import (
    ControlAction,
    ControlActionMapper,
    ControlEventGate,
    ControlInputEvent,
    ControlSource,
)


class OperatorCommands(Protocol):
    """Approved application command boundary used by physical controls."""

    def execute(self, action: ControlAction) -> bool:
        """Execute one approved action and report whether it was accepted."""


@dataclass(frozen=True)
class ControlDispatchResult:
    """Summary of one nonblocking physical-control drain cycle."""

    drained: int = 0
    accepted: int = 0
    rejected: int = 0
    unknown: int = 0


class ControlDispatcher:
    """Map and safely dispatch currently available physical-control events."""

    def __init__(
        self,
        source: ControlSource,
        mapper: ControlActionMapper,
        gate: ControlEventGate,
        commands: OperatorCommands,
    ) -> None:
        self._source = source
        self._mapper = mapper
        self._gate = gate
        self._commands = commands

    def dispatch_available(self) -> ControlDispatchResult:
        """Drain available events without blocking and dispatch safe actions."""
        events = self._source.drain()
        accepted = 0
        rejected = 0
        unknown = 0

        for event in events:
            if not self._gate.accept(event):
                rejected += 1
                continue

            action = self._mapper.resolve(event)
            if action is None:
                unknown += 1
                continue

            if self._commands.execute(action):
                accepted += 1
            else:
                rejected += 1

        return ControlDispatchResult(
            drained=len(events),
            accepted=accepted,
            rejected=rejected,
            unknown=unknown,
        )
